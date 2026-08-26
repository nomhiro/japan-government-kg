"""jgkg.fetch(取得段のディスパッチャCLI。最終レビューO3)のテスト。

**実ネットワークを含めない**(仕様§10)。コネクタ自身のテスト
(test_connector_*.py)がhttpx.MockTransportで検証済みなので、ここでは
コネクタの`fetch`/`fetch_all`を直接差し替えて「正しい引数で呼ばれるか・
正しく拒否するか」だけを検証する(ディスパッチの責務に絞る)。
"""
import datetime
import io
import sys
from collections.abc import Callable

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


class ConnectorCalledUnexpectedly(Exception):
    """「呼ばれてはならない」スタブが実際に呼ばれたことを示す専用の例外型。

    **A-1レビュー指摘への対応。** 以前は`AssertionError`に日本語の文言を
    持たせ、`fetch.py`の`except Exception`を経由したあとcapsysで捕捉した
    出力を部分文字列一致で検査していた——検出が**文言の一致**に依存して
    いた(別の理由での失敗が偶然同じ部分文字列を含めば「検出した」と
    誤認しうる)。ここでは専用の例外型と`calls`リストの2つを組み合わせ、
    `assert calls == []`という**型・文言に依存しない**判定で「呼ばれたか」
    そのものを検査する(このスタブが実際に踏んだ事故——A-1壊し確認4での
    実ネットワークアクセス——を二度と検出漏れさせないためのテスト)。
    """


def _forbidden(calls: list) -> Callable:
    """呼ばれたら`calls`に記録してから`ConnectorCalledUnexpectedly`を投げるスタブ。

    呼び出し側は`assert calls == []`で「呼ばれなかったこと」を検査する
    (`fetch.py`側が例外をどう処理するかに関係なく判定できる)。
    """
    def stub(*args, **kwargs):
        calls.append((args, kwargs))
        raise ConnectorCalledUnexpectedly(
            f"呼ばれてはならないコネクタが呼ばれた: args={args!r} kwargs={kwargs!r}"
        )
    return stub


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
    out = capsys.readouterr().out
    assert "取得完了" in out
    # A-1レビュー指摘: 単一ファイルの源はsource_idを2回表示しない
    # ("egov-law (egov-law): ..."という冗長な体裁にしない)
    assert "egov-law (egov-law)" not in out
    assert "egov-law: 取得完了" in out


def test_dispatches_rs_system_with_the_year(monkeypatch, capsys):
    calls = []

    def stub_fetch_all(year, fetched_on):
        calls.append((year, fetched_on))
        return {"organization_information": _stub_result("rs-system", fetched_on)}

    monkeypatch.setattr(fetch_module.rs_system, "fetch_all", stub_fetch_all)

    rc = fetch_module.main(
        ["--source", "rs-system", "--year", "2025", "--fetched-on", "2026-08-20"]
    )
    assert rc == 0
    # rs-systemはgroup名がsource_idと異なるため、単一ファイルの源とは違い
    # 括弧内の表示が残ってよい(むしろ無いと5本のどれかが分からなくなる)
    assert "rs-system (organization_information)" in capsys.readouterr().out
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
    calls: list = []
    # そもそもDISPATCHにministry-codesは無いが、念のため他の源が
    # 誤って呼ばれていないことも保証する
    monkeypatch.setattr(fetch_module.egov_law, "fetch", _forbidden(calls))

    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "ministry-codes"])

    assert exc_info.value.code != 0
    assert calls == []
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
    calls: list = []
    monkeypatch.setattr(fetch_module.egov_law, "fetch", _forbidden(calls))

    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "egov-law", "--year", "2025"])

    assert exc_info.value.code != 0
    assert calls == []
    assert "rs-system 以外" in capsys.readouterr().err


def test_rs_system_without_year_is_rejected(monkeypatch, capsys):
    """**この検査を外すと`args.year`が`None`のまま`rs_system.fetch_all`に渡り、

    実在のrssystem.go.jpへ`.../files/None/rs/...`という実URLで本物の
    ネットワークアクセスが発生する(壊し確認で実際に踏んだ。詳細は報告書)。
    そのため、この検査が外れても実ネットワークに触れないよう、コネクタを
    明示的に「呼ばれてはならない」スタブに差し替えておく。
    """
    calls: list = []
    monkeypatch.setattr(fetch_module.rs_system, "fetch_all", _forbidden(calls))

    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main(["--source", "rs-system"])

    assert exc_info.value.code != 0
    assert calls == []
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

    calls: list = []
    monkeypatch.setattr(fetch_module.houjin_bangou, "fetch", _forbidden(calls))

    rc = fetch_module.main(["--source", "houjin-bangou"])
    assert rc == 1
    assert calls == []
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

    calls: list = []
    monkeypatch.setattr(fetch_module.egov_law, "fetch", _forbidden(calls))

    rc = fetch_module.main(["--source", "egov-law", "--fetched-on", "2026-08-20"])
    assert rc == 1
    assert calls == []
    err = capsys.readouterr().err
    assert "既にコミット済みのスナップショットがある" in err
    # エラー文言のパスが実際のlake_dir設定を反映していること(手書きの
    # "data/lake"文字列に戻すとJGKG_LAKE_DIRを変えた実行環境で誤ったパスを
    # 案内してしまう。このテスト自身がtmp_lakeフィクスチャでJGKG_LAKE_DIRを
    # 変えているため、既定値"data/lake"が出たら検出できる)
    assert get_settings().lake_dir in err
    assert "data/lake/egov-law" not in err
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


def test_dispatches_a_law_id_fetch_with_the_resolved_fetched_on(monkeypatch, capsys):
    """`--law-id 412CO0000000315`(C-1)。`--source`とは独立した軸。"""
    calls = []

    def stub_fetch_law_data(law_id, fetched_on):
        calls.append((law_id, fetched_on))
        snap = lake.save("egov-law", fetched_on, f"law_data_{law_id}.json", b"stub")
        return FetchResult(snapshot=snap, skipped=False)

    monkeypatch.setattr(fetch_module.egov_law, "fetch_law_data", stub_fetch_law_data)

    rc = fetch_module.main(
        ["--law-id", "412CO0000000315", "--fetched-on", "2026-08-20"]
    )
    assert rc == 0
    assert calls == [("412CO0000000315", DAY)]
    assert "取得完了" in capsys.readouterr().out


def test_multiple_law_ids_are_all_fetched(monkeypatch):
    calls = []

    def stub_fetch_law_data(law_id, fetched_on):
        calls.append(law_id)
        snap = lake.save("egov-law", fetched_on, f"law_data_{law_id}.json", b"stub")
        return FetchResult(snapshot=snap, skipped=False)

    monkeypatch.setattr(fetch_module.egov_law, "fetch_law_data", stub_fetch_law_data)

    rc = fetch_module.main(
        ["--law-id", "412CO0000000315", "--law-id", "410AC0000000103",
         "--fetched-on", "2026-08-20"]
    )
    assert rc == 0
    assert calls == ["412CO0000000315", "410AC0000000103"]


def test_source_and_law_id_can_be_combined_in_one_invocation(monkeypatch):
    """`--source`(全件メタデータ)と`--law-id`(法令1件本文)は独立した軸であり、
    同じ呼び出しで両方指定できること。
    """
    source_calls, law_id_calls = [], []
    monkeypatch.setattr(
        fetch_module.egov_law, "fetch",
        lambda fetched_on: (source_calls.append(fetched_on), _stub_result("egov-law", fetched_on))[1],
    )

    def stub_fetch_law_data(law_id, fetched_on):
        law_id_calls.append((law_id, fetched_on))
        snap = lake.save("egov-law", fetched_on, f"law_data_{law_id}.json", b"stub")
        return FetchResult(snapshot=snap, skipped=False)

    monkeypatch.setattr(fetch_module.egov_law, "fetch_law_data", stub_fetch_law_data)

    rc = fetch_module.main(
        ["--source", "egov-law", "--law-id", "412CO0000000315", "--fetched-on", "2026-08-20"]
    )
    assert rc == 0
    assert source_calls == [DAY]
    assert law_id_calls == [("412CO0000000315", DAY)]


def test_neither_source_nor_law_id_is_rejected(capsys):
    """`--source`も`--law-id`も無い呼び出しは拒否されること(既存の

    test_no_source_given_is_rejectedと同じ意図だが、ゲートを`--source`単独の
    真偽値から`--source`と`--law-id`のORに変えたことそのものを検査する)。
    """
    with pytest.raises(SystemExit) as exc_info:
        fetch_module.main([])
    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "--law-id" in err


def test_law_id_overwrite_guard_rejects_without_the_flag(monkeypatch, capsys):
    lake.save("egov-law", DAY, "law_data_412CO0000000315.json", b"existing-snapshot-stub")

    calls: list = []
    monkeypatch.setattr(fetch_module.egov_law, "fetch_law_data", _forbidden(calls))

    rc = fetch_module.main(
        ["--law-id", "412CO0000000315", "--fetched-on", "2026-08-20"]
    )
    assert rc == 1
    assert calls == []
    assert "既にコミット済みのスナップショットがある" in capsys.readouterr().err


def test_law_id_fetch_is_not_blocked_by_an_unrelated_existing_bulk_metadata_snapshot(
    monkeypatch,
):
    """何があれば落ちるか: law-id向けの事前検査を`_already_fetched`

    (source_id + fetched_on単位、粗い)のまま流用すると、`--source egov-law`の
    一括メタデータが同じ日に既にある場合、無関係な`--law-id`の取得まで
    「既に取得済み」として誤って拒否される。実際に取りたい
    law_data_412CO0000000315.jsonはまだ存在しないので、これは誤検出。
    """
    lake.save("egov-law", DAY, "laws.jsonl", b"unrelated-bulk-metadata-snapshot")

    calls = []

    def stub_fetch_law_data(law_id, fetched_on):
        calls.append(law_id)
        snap = lake.save("egov-law", fetched_on, f"law_data_{law_id}.json", b"stub")
        return FetchResult(snapshot=snap, skipped=False)

    monkeypatch.setattr(fetch_module.egov_law, "fetch_law_data", stub_fetch_law_data)

    rc = fetch_module.main(
        ["--law-id", "412CO0000000315", "--fetched-on", "2026-08-20"]
    )
    assert rc == 0
    assert calls == ["412CO0000000315"]


# =============================================================================
# 壊し確認: Windowsの既定コンソール(cp932)で成功メッセージが落ちない
# =============================================================================


def test_a_success_message_with_an_em_dash_does_not_crash_on_a_cp932_console(monkeypatch):
    """何があれば落ちるか: 2026-08-26のC-1実取得で実際に踏んだ

    `UnicodeEncodeError`(Windowsの既定コンソールcp932は成功メッセージの
    区切りに使うem dash「—」をエンコードできない)。取得自体は成功し
    レイクへの保存も完了していたのに、その後の出力整形だけでCLI全体が
    非0終了(実際には未処理の例外で落ちる)していた。

    pytestの既定の`capsys`はこの制約を持たない(実コンソールのcp932を
    経由しない)ため、それだけでは検出できない。`sys.stdout`をcp932で
    エンコードする実物の`TextIOWrapper`に差し替えて実際の失敗条件を再現する。
    """
    cp932_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp932", errors="strict")
    monkeypatch.setattr(sys, "stdout", cp932_stdout)

    def stub_fetch_law_data(law_id, fetched_on):
        snap = lake.save("egov-law", fetched_on, f"law_data_{law_id}.json", b"stub")
        return FetchResult(snapshot=snap, skipped=False)

    monkeypatch.setattr(fetch_module.egov_law, "fetch_law_data", stub_fetch_law_data)

    rc = fetch_module.main(
        ["--law-id", "412CO0000000315", "--fetched-on", "2026-08-20"]
    )
    assert rc == 0

    cp932_stdout.flush()
    cp932_stdout.buffer.seek(0)
    out = cp932_stdout.buffer.read().decode("cp932")
    assert "取得完了" in out
    # em dashはcp932で表現できないので、reconfigure後はbackslashreplaceで
    # `—`のような形にエスケープされる(クラッシュしないことが本質で、
    # 見た目の劣化は許容する)
    assert "\\u2014" in out


# =============================================================================
# 壊し確認5: sources.py に登録されているが DISPATCH に結線されていない源
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
