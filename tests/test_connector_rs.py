import csv
import datetime
import io
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from jgkg import lake
from jgkg.connectors import rs_system
from jgkg.transform import rs_columns

FIXTURES = Path(__file__).parent / "fixtures"
YEAR = 2025
DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _zip_of(csv_bytes: bytes, member: str) -> bytes:
    """RSの実配布と同じ形(zip内にCSVが1本だけ)でテスト用に包む。

    tests/zenken_rows.py の zipped() は法人番号全件データの配布形
    (zip + .asc署名)を写したもので、RSの実配布(zip内はCSV1本のみ、実測)とは
    形が違うため流用しない。ここに専用の最小ヘルパを持つ。
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, csv_bytes)
    return buf.getvalue()


def _header_of(sample_bytes: bytes) -> list[str]:
    """fixtureの1行目(ヘッダ)をBOM除去して読む。"""
    text = sample_bytes.decode("utf-8-sig")
    return next(csv.reader(io.StringIO(text)))


PAYEE_SAMPLE = (FIXTURES / "rs_sample.csv").read_bytes()
LAW_SAMPLE = (FIXTURES / "rs_law_sample.csv").read_bytes()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _zip_responder(payload_by_url: dict[str, bytes]):
    """URLごとに固定のzipバイト列を返すハンドラ。未登録URLは404。"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in payload_by_url:
            return httpx.Response(404)
        return httpx.Response(
            200, content=payload_by_url[url], headers={"content-type": "application/zip"}
        )

    return handler


# ============================================================
# fetch_group: 単一グループファイルの取得・保存
# ============================================================


def test_fetch_group_saves_snapshot_to_lake():
    """1本のグループファイルが、配布形態(zip)のまま保存されること。"""
    payload = _zip_of(PAYEE_SAMPLE, "5-1_RS_2025_支出先_支出情報.csv")
    url = rs_system.url_for("payee_payment_information", YEAR)
    client = _client(_zip_responder({url: payload}))

    result = rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)

    assert result.skipped is False
    assert result.snapshot.source_id == rs_system.SOURCE_ID
    filename = rs_system.filename_for("payee_payment_information", YEAR)
    assert lake.load(rs_system.SOURCE_ID, DAY, filename) == payload


def test_fetch_group_is_idempotent():
    """同じ取得日に2度呼んでも、2度目はネットワークに触れずスキップされる。"""
    payload = _zip_of(PAYEE_SAMPLE, "5-1_RS_2025_支出先_支出情報.csv")
    url = rs_system.url_for("payee_payment_information", YEAR)
    client = _client(_zip_responder({url: payload}))

    first = rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)
    assert first.skipped is False

    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("2度目の取得はネットワークに触れないはず")

    exploding_client = _client(_explode)
    second = rs_system.fetch_group(
        "payee_payment_information", YEAR, DAY, client=exploding_client
    )
    assert second.skipped is True
    assert second.snapshot.sha256 == first.snapshot.sha256


def test_fetch_group_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)


def test_fetch_group_raises_on_soft_404_html_response():
    """存在しない年度・ファイル名で、CloudFrontがHTTP 200 + SPAのindex.html
    シェルを返す実測済みの挙動を再現する(rs_system.py モジュールdocstring
    「既知の罠」参照)。ステータスコードだけを見て保存してはならない。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'<!doctype html><html lang="ja"><head></head><body>'
            b'<div id="root"></div></body></html>',
            headers={"content-type": "text/html"},
        )

    client = _client(handler)
    with pytest.raises(rs_system.UnexpectedResponseError):
        rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)

    # 誤った応答がスナップショットとして残っていないこと(サイレントに壊れていない)
    assert lake.list_snapshots(rs_system.SOURCE_ID) == []


def test_url_for_matches_the_url_verified_against_the_real_network():
    """2026-08-23 に実際に rssystem.go.jp へHEAD/GETして確認した実URLと一致すること。

    url_for() は urllib.parse.quote で組み立てる。この値がずれれば
    (例: quoteの safe引数やUnicode正規化が変わった場合)、実サーバーには
    通らないのに単体テストは気付かない。実測URLをここに固定して照合する。
    """
    assert rs_system.url_for("organization_information", 2025) == (
        "https://rssystem.go.jp/files/2025/rs/"
        "1-1_RS_2025_%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1_"
        "%E7%B5%84%E7%B9%94%E6%83%85%E5%A0%B1.zip"
    )


# ============================================================
# fetch_all: 複数グループファイルのオーケストレーション
# ============================================================


def test_fetch_all_fetches_every_requested_group_with_correct_filenames():
    groups = rs_system.FETCHED_GROUPS
    payload = _zip_of(PAYEE_SAMPLE, "dummy.csv")  # プラミング検証には内容は無関係
    payload_by_url = {rs_system.url_for(g, YEAR): payload for g in groups}
    client = _client(_zip_responder(payload_by_url))

    results = rs_system.fetch_all(YEAR, DAY, groups=groups, client=client)

    assert set(results.keys()) == set(groups)
    for group in groups:
        assert results[group].skipped is False
        filename = rs_system.filename_for(group, YEAR)
        assert lake.load(rs_system.SOURCE_ID, DAY, filename) == payload


def test_fetch_all_sleeps_between_files_but_not_before_the_first(monkeypatch):
    """ファイル間に待機を挟むこと(公共のCDNへの礼儀。このタスクのネットワーク特例が要求する)。"""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    groups = rs_system.FETCHED_GROUPS
    payload = _zip_of(PAYEE_SAMPLE, "dummy.csv")
    payload_by_url = {rs_system.url_for(g, YEAR): payload for g in groups}
    client = _client(_zip_responder(payload_by_url))

    rs_system.fetch_all(YEAR, DAY, groups=groups, client=client)

    assert sleeps == [rs_system.FILE_INTERVAL_SECONDS] * (len(groups) - 1)


# ============================================================
# rs_columns: 列対応の照合記録がfixtureの実データと矛盾しないこと
# ============================================================


def test_verify_header_accepts_the_real_fixture_header():
    header = _header_of(PAYEE_SAMPLE)
    rs_columns.verify_header("payee_payment_information", header)  # 例外にならない

    law_header = _header_of(LAW_SAMPLE)
    rs_columns.verify_header("policy_measure_laws_and_regulations", law_header)


def test_verify_header_rejects_wrong_column_count():
    header = _header_of(PAYEE_SAMPLE)[:-1]  # 1列減らす
    with pytest.raises(rs_columns.ColumnLayoutError):
        rs_columns.verify_header("payee_payment_information", header)


def test_verify_header_rejects_a_renamed_column():
    """列数は合っているが、列名が1つ違う(列がずれた実データを模す)。"""
    header = list(_header_of(PAYEE_SAMPLE))
    assert header[19] == "法人番号"  # 実データの実際の値(照合記録どおり)であることの確認
    header[19] = "法人番号_ずれた列名"  # 列がずれた実データを模す
    with pytest.raises(rs_columns.ColumnLayoutError):
        rs_columns.verify_header("payee_payment_information", header)


def test_fixture_rows_have_the_expected_recipient_houjin_bangou_presence():
    """fixtureが要求どおり、法人番号がある行・無い行の両方を含むこと。

    無い行のうち1件は構造的な空欄(ブロック行)、1件は実質的な欠落
    (その他支出先=TRUEの束ね)である(rs_columns.py 照合記録参照)。
    """
    reader = csv.reader(io.StringIO(PAYEE_SAMPLE.decode("utf-8-sig")))
    header = next(reader)
    idx_houjin = rs_columns.RS_FILES["payee_payment_information"].col[
        "recipient_houjin_bangou"
    ]
    idx_other = header.index("その他支出先")
    rows = list(reader)

    houjin_values = [row[idx_houjin].strip() for row in rows]
    assert any(v for v in houjin_values), "法人番号がある行が無い"
    assert any(not v for v in houjin_values), "法人番号が無い行が無い"
    assert any(row[idx_other] == "TRUE" for row in rows), (
        "「その他支出先」で束ねられた(実質的に法人番号が欠落する)行が無い"
    )


def test_fixture_law_rows_have_a_basis_law_with_egov_style_law_id():
    """fixtureの根拠法令行が、e-Govと同形式のlaw_idを持つこと(検証1の根拠)。"""
    reader = csv.reader(io.StringIO(LAW_SAMPLE.decode("utf-8-sig")))
    next(reader)  # header
    spec = rs_columns.RS_FILES["policy_measure_laws_and_regulations"]
    idx_text = spec.col["basis_law_text"]
    idx_id = spec.col["basis_law_id"]

    rows = list(reader)
    assert all(row[idx_text] for row in rows), "法令名が空の行がある"
    for row in rows:
        law_id = row[idx_id]
        # e-Gov law_id の実測形式(例: 322AC0000000120, 503AC0000000036):
        # 英数字15文字程度。厳密な文法検査ではなく、明らかに空・極端に短い値
        # (列がずれた場合に起きる)だけを弾く
        assert law_id.isalnum(), f"law_idが英数字ではない: {law_id!r}"
        assert len(law_id) >= 10, f"law_idが短すぎる: {law_id!r}"


# ============================================================
# rs_system と rs_columns の配線一貫性
# ============================================================


def test_all_fetched_groups_have_a_verified_column_spec():
    for group in rs_system.FETCHED_GROUPS:
        assert group in rs_columns.RS_FILES


def test_rs_col_entries_agree_with_the_per_file_column_spec():
    for logical_name, (group, idx) in rs_columns.RS_COL.items():
        spec = rs_columns.RS_FILES[group]
        assert 0 <= idx < spec.expected_columns
        assert spec.col[logical_name] == idx


def test_no_group_is_both_fetched_and_unverified():
    assert set(rs_system.FETCHED_GROUPS).isdisjoint(rs_columns.RS_UNVERIFIED_GROUPS)


def test_every_group_filename_is_accounted_for():
    """rs_system(全15本のファイル名)と rs_columns(確認済み5本+未確認10本)が
    1対1で対応していること(取りこぼし・重複registrationを防ぐ)。
    """
    all_groups = set(rs_system.RS_GROUP_FILENAMES.keys())
    accounted = set(rs_columns.RS_FILES.keys()) | set(rs_columns.RS_UNVERIFIED_GROUPS)
    assert all_groups == accounted


def test_column_layout_error_matches_organization_pys_base_class():
    """レビュー指摘6: organization.pyのColumnLayoutErrorと同じ基底クラス
    (ValueError)であること。docstringが「同じ考え方」と書いているのに
    実装がRuntimeErrorだった食い違いを、型として固定する。
    """
    assert issubclass(rs_columns.ColumnLayoutError, ValueError)
