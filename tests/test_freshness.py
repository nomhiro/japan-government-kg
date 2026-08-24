import datetime

import pytest

from jgkg import freshness, lake, sources
from jgkg.connectors import houjin_bangou

TODAY = datetime.date(2026, 8, 24)


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _source(source_id: str, expected_cadence_days: int | None) -> sources.Source:
    return sources.Source(
        id=source_id,
        name=source_id,
        url="https://example.test",
        license="テスト用ライセンス",
        license_url="https://example.test/license",
        frequency="monthly",
        access="bulk",
        expected_cadence_days=expected_cadence_days,
    )


def test_report_flags_a_source_past_its_cadence():
    lake.save("houjin-bangou", TODAY - datetime.timedelta(days=40), houjin_bangou.FILENAME, b"x")
    registry = {"houjin-bangou": _source("houjin-bangou", 31)}

    result = freshness.report(TODAY, registry)

    assert len(result) == 1
    assert result[0].source_id == "houjin-bangou"
    assert result[0].days_since_last_fetch == 40
    assert result[0].expected_cadence_days == 31


def test_report_omits_a_source_within_its_cadence():
    lake.save("houjin-bangou", TODAY - datetime.timedelta(days=10), houjin_bangou.FILENAME, b"x")
    registry = {"houjin-bangou": _source("houjin-bangou", 31)}

    assert freshness.report(TODAY, registry) == []


def test_report_boundary_exactly_at_cadence_is_not_yet_stale():
    """超過日数がちょうどcadenceと等しい(境界)場合は、まだ「新鮮」であること。

    何があれば落ちるか: 判定を `>=` にすると、この境界ちょうどの日に
    「まだ間に合っている」ソースを誤ってstaleにしてしまう。
    """
    lake.save("houjin-bangou", TODAY - datetime.timedelta(days=31), houjin_bangou.FILENAME, b"x")
    registry = {"houjin-bangou": _source("houjin-bangou", 31)}

    assert freshness.report(TODAY, registry) == []


def test_report_one_day_past_the_boundary_is_stale():
    lake.save("houjin-bangou", TODAY - datetime.timedelta(days=32), houjin_bangou.FILENAME, b"x")
    registry = {"houjin-bangou": _source("houjin-bangou", 31)}

    result = freshness.report(TODAY, registry)
    assert [s.source_id for s in result] == ["houjin-bangou"]
    assert result[0].days_since_last_fetch == 32


def test_report_flags_a_tracked_source_that_was_never_fetched():
    """cadence追跡対象だがレイクに1件も記録が無いソースを、新鮮扱いしないこと。

    何があれば落ちるか: `lake.latest` が None を返す場合を「対象外」として
    スキップすると、一度も取得されていないegov-lawのような状態が
    「全部新鮮」の中に紛れて消える(このタスクで踏みやすい欠陥の型4)。
    """
    registry = {"egov-law": _source("egov-law", 31)}

    result = freshness.report(TODAY, registry)

    assert len(result) == 1
    assert result[0].source_id == "egov-law"
    assert result[0].last_fetched_on is None
    assert result[0].days_since_last_fetch is None


def test_report_ignores_sources_without_a_cadence_even_if_never_fetched():
    """cadence未設定(無期限)のソースは、レイクに記録が無くてもstaleにしないこと。"""
    registry = {"ministry-codes": _source("ministry-codes", None)}
    assert freshness.report(TODAY, registry) == []


def test_report_raises_for_an_empty_registry_instead_of_reporting_all_fresh():
    """ソースが1つも登録されていない状態で「全部新鮮」(空リスト)を返さないこと。

    task-10-brief.md「このタスクで踏みやすい欠陥の型」4番そのもの。
    何があれば落ちるか: `{}` を渡したときに素直に `[]` を返す実装に戻すと、
    「監視対象が無い」と「監視した結果、全部新鮮だった」が同じ戻り値になり、
    設定漏れ(sources.pyが空になった等)を検出できなくなる。
    """
    with pytest.raises(ValueError, match="鮮度監視の対象ソースが1つも登録されていない"):
        freshness.report(TODAY, {})


def test_report_does_not_raise_when_a_nonempty_registry_has_no_cadence_tracked_source():
    """非空のregistryだがcadenceを持つソースが1つも無い(=無期限のみ)場合は、

    「1つも登録されていない」罠とは別の状態として、例外にせず空リストを返すこと。
    """
    registry = {
        "ministry-codes": _source("ministry-codes", None),
        "other-ref": _source("other-ref", None),
    }
    assert freshness.report(TODAY, registry) == []


def test_report_is_sorted_by_source_id():
    lake.save("egov-law", TODAY - datetime.timedelta(days=100), "laws.jsonl", b"x")
    lake.save("houjin-bangou", TODAY - datetime.timedelta(days=100), houjin_bangou.FILENAME, b"x")
    registry = {
        "houjin-bangou": _source("houjin-bangou", 31),
        "egov-law": _source("egov-law", 31),
    }

    result = freshness.report(TODAY, registry)
    assert [s.source_id for s in result] == ["egov-law", "houjin-bangou"]


def test_report_over_the_real_registry_does_not_raise():
    """既定(実際のsources.SOURCES)を使った呼び出しが、設定漏れ例外を起こさないこと。

    houjin-bangou/egov-law/rs-systemがcadenceを持つ実際の登録内容を確認する
    (実運用でこの関数が使われる形そのもの)。
    """
    result = freshness.report(TODAY)
    # 4ソースとも登録されているが、レイクは空(tmp_lakeフィクスチャ)なので
    # cadence追跡対象3つ(houjin-bangou/egov-law/rs-system)が全部「未取得」で
    # staleに入るはず(参照表ministry-codesは対象外)
    assert {s.source_id for s in result} == {"houjin-bangou", "egov-law", "rs-system"}
    assert all(s.last_fetched_on is None for s in result)
