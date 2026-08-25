"""jgkg.fetch(取得段のディスパッチャCLI。最終レビューO3)のテスト。

**実ネットワークを含めない**(仕様§10)。コネクタ自身のテスト
(test_connector_*.py)がhttpx.MockTransportで検証済みなので、ここでは
コネクタの`fetch`/`fetch_all`を直接差し替えて「正しい引数で呼ばれるか・
正しく拒否するか」だけを検証する(ディスパッチの責務に絞る)。
"""
import datetime

import pytest

from jgkg import fetch as fetch_module
from jgkg import lake, sources
from jgkg.config import get_settings
from jgkg.connectors.base import FetchResult

DAY = datetime.date(2026, 8, 20)


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _stub_result(source_id: str, day: datetime.date) -> FetchResult:
    """スタブのコネクタが返す、実際に保存を伴う`FetchResult`(skipped=False)。

    冪等スキップ(skipped=True)を模す場面は、既存のSnapshotを先に
    `lake.save`で作ってから個別に`FetchResult(snapshot=existing, skipped=True)`
    を組み立てる(このヘルパーは使わない——「既存のものを指す」ことが
    本質であり、新規保存とは別の形だから)。
    """
    snap = lake.save(source_id, day, "dummy.bin", b"stub")
    return FetchResult(snapshot=snap, skipped=False)


# =============================================================================
# ディスパッチ: 正しい引数でコネクタが呼ばれること
# =============================================================================


def test_dispatches_egov_law_with_the_resolved_fetched_on(monkeypatch, capsys):
    calls = []

    def stub_fetch(fetched_on):
        calls.append(fetched_on)
        return _stub_result("egov-law", fetched_on)

    monkeypatch.setattr(fetch_module.egov_law, "fetch", stub_fetch)

    rc = fetch_module.main(["--source", "egov-law", "--fetched-on", "2026-08-20"])
    assert rc == 0
    assert calls == [DAY]
    assert "取得完了" in capsys.readouterr().out


def test_dispatches_rs_system_with_the_year(monkeypatch):
    calls = []

    def stub_fetch_all(year, fetched_on):
        calls.append((year, fetched_on))
        return {"organization_information": _stub_result("rs-system", fetched_on)}

    monkeypatch.setattr(fetch_module.rs_system, "fetch_all", stub_fetch_all)

    rc = fetch_module.main(
        ["--source", "rs-system", "--year", "2025", "--fetched-on", "2026-08-20"]
    )
    assert rc == 0
    assert calls == [(2025, DAY)]


def test_dispatches_houjin_bangou_with_the_configured_url(monkeypatch):
    monkeypatch.setenv("JGKG_HOUJIN_BANGOU_URL", "https://example.test/zenken.zip")
    get_settings.cache_clear()
    calls = []

    def stub_fetch(url, fetched_on):
        calls.append((url, fetched_on))
        return _stub_result("houjin-bangou", fetched_on)

    monkeypatch.setattr(fetch_module.houjin_bangou, "fetch", stub_fetch)

    rc = fetch_module.main(["--source", "houjin-bangou", "--fetched-on", "2026-08-20"])
    assert rc == 0
    assert calls == [("https://example.test/zenken.zip", DAY)]


def test_multiple_sources_in_one_invocation_both_get_called(monkeypatch):
    """`--source egov-law --source rs-system --year 2025`(ブリーフの「複数可」例)。"""
    egov_calls, rs_calls = [], []
    monkeypatch.setattr(
        fetch_module.egov_law, "fetch",
        lambda fetched_on: (egov_calls.append(fetched_on), _stub_result("egov-law", fetched_on))[1],
    )
    monkeypatch.setattr(
        fetch_module.rs_system, "fetch_all",
        lambda year, fetched_on: (
            rs_calls.append((year, fetched_on)),
            {"organization_information": _stub_result("rs-system", fetched_on)},
        )[1],
    )

    rc = fetch_module.main(
        ["--source", "egov-law", "--source", "rs-system", "--year", "2025",
         "--fetched-on", "2026-08-20"]
    )
    assert rc == 0
    assert egov_calls == [DAY]
    assert rs_calls == [(2025, DAY)]


# =============================================================================
# 壊し確認1: --source ministry-codes は非0終了する(取得を試みない)
# =============================================================================


def test_ministry_codes_is_rejected_without_attempting_any_fetch(monkeypatch, capsys):
    """何があれば落ちるか: `source.local_path`の検査を外すと、DISPATCHに

    ministry-codesが無いため KeyError で落ちるか、あるいは黙って何もせず
    exit 0 になる——いずれも「成功したように見せない」を満たさない。
    """
    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("ministry-codes はコネクタを呼んではならない")

    # そもそもDISPATCHにministry-codesは無いが、念のため他の源が
    # 誤って呼ばれていないことも保証する
    monkeypatch.setattr(fetch_module.egov_law, "fetch", _must_not_be_called)

    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "ministry-codes"])

    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "取得対象ではない" in err
    assert "data/reference/ministry-codes.csv" in err


# =============================================================================
# 壊し確認2: --year の誤用(rs-system以外への付与・rs-systemへの欠落)
# =============================================================================


def test_year_flag_on_a_non_rs_system_source_is_rejected(monkeypatch, capsys):
    """何があれば落ちるか: `--year`を黙って無視する実装に戻すと、egov-lawに

    対して`--year`を打っても何もエラーにならず成功してしまう(壊し確認で
    実際に踏んだ。しかも実装済みの本物の`egov_law.fetch`が実行され、
    e-Gov法令APIへの実ネットワークアクセスが発生した——報告書参照)。
    そのため、この検査が外れても実ネットワークに触れないよう、コネクタを
    明示的に「呼ばれてはならない」スタブに差し替えておく。
    """
    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("--year の誤用が通ったのに egov_law.fetch を呼んではならない")

    monkeypatch.setattr(fetch_module.egov_law, "fetch", _must_not_be_called)

    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "egov-law", "--year", "2025"])

    assert exc_info.value.code != 0
    assert "rs-system 以外" in capsys.readouterr().err


def test_rs_system_without_year_is_rejected(monkeypatch, capsys):
    """**この検査を外すと`args.year`が`None`のまま`rs_system.fetch_all`に渡り、

    実在のrssystem.go.jpへ`.../files/None/rs/...`という実URLで本物の
    ネットワークアクセスが発生する(壊し確認で実際に踏んだ。詳細は報告書)。
    そのため、この検査が外れても実ネットワークに触れないよう、コネクタを
    明示的に「呼ばれてはならない」スタブに差し替えておく。
    """
    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("--year が無いのに rs_system.fetch_all を呼んではならない")

    monkeypatch.setattr(fetch_module.rs_system, "fetch_all", _must_not_be_called)

    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "rs-system"])

    assert exc_info.value.code != 0
    assert "--year が必要" in capsys.readouterr().err


# =============================================================================
# 壊し確認3: JGKG_HOUJIN_BANGOU_URL 未設定(または空)時のエラー
# =============================================================================


def test_houjin_bangou_url_unset_gives_an_actionable_error(monkeypatch, capsys):
    """未設定(空文字列)のとき、**何をすればよいか分かる文言**でエラーになること。

    **`monkeypatch.delenv`ではなく`monkeypatch.setenv(..., "")`を使う。**
    このリポジトリの実際の`.env`(gitignore対象・非コミット)には実在の
    URLが書かれていることがあり、`delenv`だけでは環境変数を消しても
    pydantic-settingsが`.env`ファイルを直接読んで値を復元してしまう
    (このマシンで実際にそうなることを確認した)。`setenv(..., "")`で
    明示的に空文字列を注入すれば、`.env`の内容に関係なく再現できる。
    """
    monkeypatch.setenv("JGKG_HOUJIN_BANGOU_URL", "")
    get_settings.cache_clear()

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("URLが無いのにコネクタを呼んではならない")

    monkeypatch.setattr(fetch_module.houjin_bangou, "fetch", _must_not_be_called)

    rc = fetch_module.main(["--source", "houjin-bangou"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "JGKG_HOUJIN_BANGOU_URL" in err
    assert "houjin-bangou.nta.go.jp/download/zenken" in err
    assert "selDlFileNo" in err


# =============================================================================
# 壊し確認4: 上書き拒否ガード(フラグ無しで拒否・フラグ有りで通る。両方向)
# =============================================================================


def test_overwrite_guard_rejects_without_the_flag_and_the_connector_is_never_called(
    monkeypatch, capsys
):
    lake.save("egov-law", DAY, "laws.jsonl", b"existing-snapshot-stub")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("既存スナップショットがあるのにコネクタを呼んではならない")

    monkeypatch.setattr(fetch_module.egov_law, "fetch", _must_not_be_called)

    rc = fetch_module.main(["--source", "egov-law", "--fetched-on", "2026-08-20"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "既にコミット済みのスナップショットがある" in err
    assert "--allow-overwrite" in err


def test_overwrite_guard_lets_the_idempotent_skip_through_with_the_flag(monkeypatch):
    """`--allow-overwrite`を付けると、既存スナップショットがあっても

    コネクタの呼び出しまでは進む(コネクタ自身の冪等スキップ——
    test_connector_egov.test_fetch_is_idempotent と同じ経路——が働き、
    実際に上書きされることは無い)。
    """
    existing = lake.save("egov-law", DAY, "laws.jsonl", b"existing-snapshot-stub")

    def stub_fetch(fetched_on):
        # 本物のegov_law.fetchが冪等スキップで返すのと同じ形(skipped=True)を模す
        return FetchResult(snapshot=existing, skipped=True)

    monkeypatch.setattr(fetch_module.egov_law, "fetch", stub_fetch)

    rc = fetch_module.main(
        ["--source", "egov-law", "--fetched-on", "2026-08-20", "--allow-overwrite"]
    )
    assert rc == 0


def test_overwrite_guard_does_not_block_a_different_fetched_on_date(monkeypatch):
    """同じ源でも別の日付なら、ガードは無関係(そもそも別ディレクトリ)。"""
    lake.save("egov-law", DAY, "laws.jsonl", b"existing-snapshot-stub")

    other_day = datetime.date(2026, 8, 21)
    calls = []
    monkeypatch.setattr(
        fetch_module.egov_law, "fetch",
        lambda fetched_on: (calls.append(fetched_on), _stub_result("egov-law", fetched_on))[1],
    )

    rc = fetch_module.main(["--source", "egov-law", "--fetched-on", "2026-08-21"])
    assert rc == 0
    assert calls == [other_day]


# =============================================================================
# その他
# =============================================================================


def test_no_source_given_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main([])
    assert exc_info.value.code != 0


def test_unregistered_source_is_rejected_by_argparse_choices(capsys):
    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "no-such-source"])
    assert exc_info.value.code != 0


def test_one_source_failing_does_not_prevent_the_other_from_being_attempted(monkeypatch):
    """1つの源の取得失敗が、他の源の取得を止めないこと(取得は源ごとに独立)。"""
    def _explode(fetched_on):
        raise RuntimeError("egov-lawの取得が失敗した(模擬)")

    rs_calls = []
    monkeypatch.setattr(fetch_module.egov_law, "fetch", _explode)
    monkeypatch.setattr(
        fetch_module.rs_system, "fetch_all",
        lambda year, fetched_on: (
            rs_calls.append((year, fetched_on)),
            {"organization_information": _stub_result("rs-system", fetched_on)},
        )[1],
    )

    rc = fetch_module.main(
        ["--source", "egov-law", "--source", "rs-system", "--year", "2025",
         "--fetched-on", "2026-08-20"]
    )
    assert rc == 1  # 全体としては失敗を報告する
    assert rs_calls == [(2025, DAY)]  # が、rs-systemは実際に試みられている


# =============================================================================
# sources.py に登録されているが DISPATCH に結線されていない源(利用者の
# 入力ミスではなく、このリポジトリ側の欠陥として区別する経路)
# =============================================================================


def test_a_registered_but_undispatched_source_gives_a_repo_bug_error_not_a_crash(
    monkeypatch, capsys
):
    """何があれば落ちるか: このテストが無いと、`unwired`検査を削除しても

    (`choices=sorted(sources.SOURCES)`はmain()の中で毎回評価されるため)
    502件のテストは全部greenのまま——将来ソースが増えてDISPATCHへの追加を
    忘れたとき、利用者が打ったコマンドが`KeyError`という生の例外で
    落ちる(このリポジトリ側の結線漏れだと分からない形で)。fake-sourceを
    一時的にレジストリへ注入し、「登録されているのに使えない」を経路として
    再現する(要修正7と同じ理屈: mutation testingで実際に検出する)。
    """
    fake = sources.Source(
        id="fake-source",
        name="テスト用の未結線ソース",
        url="https://example.test/fake-source",
        license="dummy",
        license_url="https://example.test/license",
        frequency="ondemand",
        access="api",
    )
    monkeypatch.setitem(sources.SOURCES, "fake-source", fake)

    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "fake-source"])

    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "結線されていない" in err
    assert "fake-source" in err
