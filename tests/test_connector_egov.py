import datetime
import json
import time
from pathlib import Path

import httpx
import pytest

from jgkg import lake
from jgkg.connectors import egov_law

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# 実応答から5件(全体宇宙)に縮めたfixture。law本体は無編集の実在の法令(R45)。
# page1が3件・page2が2件で、続き番号(offset)で繋がる(実際にそう取得した)
PAGE1 = _load_fixture("egov_laws_page1.json")
PAGE2 = _load_fixture("egov_laws_page2.json")
FIXTURE_LAW_1, FIXTURE_LAW_2, FIXTURE_LAW_3 = PAGE1["laws"]
FIXTURE_LAW_4, FIXTURE_LAW_5 = PAGE2["laws"]

DAY = datetime.date(2026, 8, 1)
DAY2 = datetime.date(2026, 8, 2)


def client_returning(pages: dict[int, dict]) -> httpx.Client:
    """offsetをキーに応答するスタブ httpx.Client。

    未登録のoffsetには「もう無い」体のページ(count=0, next_offset=None)を返す。
    2ページ目が存在しない状況を、HTTPエラーではなく「ページングが早期終了した」
    形で再現するため。IncompleteSnapshotErrorが検出すべきなのはこちらの欠落で、
    HTTPエラー(test_fetch_raises_on_http_error)とは別の失敗経路として扱う。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        page = pages.get(
            offset, {"total_count": 0, "count": 0, "next_offset": None, "laws": []}
        )
        return httpx.Response(200, json=page)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pagination_sums_to_total_count(monkeypatch):
    """ページを繋いだ行数が total_count と一致しなければ例外になること。

    何があれば落ちるか: next_offset の見落とし・打ち切りで全件スナップショットが
    欠けたとき。「取れただけ保存」は差分検出(Task 10)を静かに壊すので許さない。
    """
    monkeypatch.setattr(egov_law, "PAGE_INTERVAL_SECONDS", 0)

    pages = {
        0: {"total_count": 5, "count": 3, "next_offset": 3,
            "laws": [FIXTURE_LAW_1, FIXTURE_LAW_2, FIXTURE_LAW_3]},
        3: {"total_count": 5, "count": 2, "next_offset": None,
            "laws": [FIXTURE_LAW_4, FIXTURE_LAW_5]},
    }
    client = client_returning(pages)
    result = egov_law.fetch(DAY, client=client)
    assert result.skipped is False
    saved = lake.path_of("egov-law", DAY, egov_law.FILENAME).read_text(encoding="utf-8")
    assert len(saved.splitlines()) == 5

    broken = client_returning({0: pages[0]})  # 2ページ目を返さない
    with pytest.raises(egov_law.IncompleteSnapshotError):
        egov_law.fetch(DAY2, client=broken)

    # 失敗した取得はスナップショットを残さない(部分データがコミットされない)。
    # DAY2向けのlaws.jsonlが存在しなければ、後で再取得を試みても妨げられない
    remaining = lake.list_snapshots("egov-law")
    assert len(remaining) == 1
    assert remaining[0].sha256 == result.snapshot.sha256
    assert remaining[0].fetched_on == DAY


def test_fetch_saves_real_fixture_laws_as_jsonl(monkeypatch):
    """実fixtureの5件が、パース・変換されずそのままJSONLとして保存されること。"""
    monkeypatch.setattr(egov_law, "PAGE_INTERVAL_SECONDS", 0)
    client = client_returning({0: PAGE1, PAGE1["next_offset"]: PAGE2})
    result = egov_law.fetch(DAY, client=client)

    assert result.skipped is False
    saved_lines = lake.path_of("egov-law", DAY, egov_law.FILENAME).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(saved_lines) == 5

    saved_laws = [json.loads(line) for line in saved_lines]
    saved_law_ids = {law["law_info"]["law_id"] for law in saved_laws}
    assert saved_law_ids == {
        law["law_info"]["law_id"] for law in PAGE1["laws"] + PAGE2["laws"]
    }

    # ラベルを信用せず生値をそのまま保持している実例(実測済み):
    # 太政官布告がlaw_num_type=CabinetOrderに分類されている。コネクタは
    # これを分類・訂正せずそのまま通す(分類はTask 4の仕事)
    taiseikan = next(
        law for law in saved_laws if law["law_info"]["law_id"] == "105DF0000000337"
    )
    assert taiseikan["law_info"]["law_num_type"] == "CabinetOrder"
    assert "太政官布告" in taiseikan["law_info"]["law_num"]


def test_lines_are_sorted_keys_for_determinism(monkeypatch):
    """JSONLの各行は、ネストしたlaw_infoを含めキーがソートされていること。

    何があれば落ちるか: sort_keys を忘れると、同じデータでも辞書のキー順が
    不定になり、sha256が実行ごとに変わって差分検出(Task 10)が
    「毎回変更あり」になる。
    """
    monkeypatch.setattr(egov_law, "PAGE_INTERVAL_SECONDS", 0)
    client = client_returning({0: PAGE1, PAGE1["next_offset"]: PAGE2})
    egov_law.fetch(DAY, client=client)

    saved_lines = lake.path_of("egov-law", DAY, egov_law.FILENAME).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(saved_lines) == 5

    for line in saved_lines:
        top_level = json.loads(line, object_pairs_hook=list)
        top_keys = [k for k, _ in top_level]
        assert top_keys == sorted(top_keys), line

        law_info_pairs = next(v for k, v in top_level if k == "law_info")
        law_info_keys = [k for k, _ in law_info_pairs]
        assert law_info_keys == sorted(law_info_keys), line


def test_fetch_is_idempotent(monkeypatch):
    """同じ取得日に2度呼んでも例外にならず、2度目はネットワークに触れずスキップされる。

    冪等性は設計書§11.1の要件。中断からの再開を可能にする。
    """
    monkeypatch.setattr(egov_law, "PAGE_INTERVAL_SECONDS", 0)
    client = client_returning({0: PAGE1, PAGE1["next_offset"]: PAGE2})
    first = egov_law.fetch(DAY, client=client)
    assert first.skipped is False

    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("2度目の取得はネットワークに触れないはず")

    exploding_client = httpx.Client(transport=httpx.MockTransport(_explode))
    second = egov_law.fetch(DAY, client=exploding_client)
    assert second.skipped is True
    assert second.snapshot.sha256 == first.snapshot.sha256


def test_fetch_raises_on_http_error():
    """HTTPエラーはIncompleteSnapshotErrorに化けず、そのまま伝播すること。

    件数不一致(サーバーは正常に応答したが総数に届かない)と、通信そのものの
    失敗は別の失敗経路として区別する(隠さない)。
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        egov_law.fetch(DAY, client=client)


def test_sleeps_between_pages(monkeypatch):
    """ページ間に0.5秒以上の待機を挟むこと(公共APIへの礼儀。このタスクの特例が要求する)。

    何があれば落ちるか: 待機を削ると、全件実取得(Task 11)で短時間に
    大量リクエストを送ることになる。
    """
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    client = client_returning({0: PAGE1, PAGE1["next_offset"]: PAGE2})
    egov_law.fetch(DAY, client=client)

    # 2ページ(offset 0 → 3)なので、ページ間の待機は1回だけ
    assert sleeps == [egov_law.PAGE_INTERVAL_SECONDS]
    assert egov_law.PAGE_INTERVAL_SECONDS >= 0.5
