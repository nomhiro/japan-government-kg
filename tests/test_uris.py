import datetime

import pytest

from jgkg import uris
from jgkg.config import Settings

# 既定値と異なるベースURIを使い、設定が実際に読まれていることを証明する。
# .invalid は予約TLDなので、誤って本物のホストを指すことがない。
TEST_BASE = "https://uri-test.invalid/kg"


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", TEST_BASE)
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_org_uri_uses_houjin_bangou():
    assert uris.org_uri("6000012070001") == f"{TEST_BASE}/id/org/6000012070001"


def test_org_uri_rejects_malformed_houjin_bangou():
    with pytest.raises(ValueError):
        uris.org_uri("12345")


def test_law_uri_and_version_uri():
    assert uris.law_uri("507M60000100010") == f"{TEST_BASE}/id/law/507M60000100010"
    assert uris.law_version_uri("507M60000100010", datetime.date(2026, 8, 1)) == (
        f"{TEST_BASE}/id/law/507M60000100010/20260801"
    )


def test_law_version_uri_distinguishes_same_date_by_amendment_law_num():
    """同一施行日の改正2件が、改正法令番号込みで別々のURIになること(レビュー指摘10)。

    何があれば落ちるか: `amendment_law_num` を鍵に加え忘れると、この2つの
    呼び出しが同じURIを返し、`emit_laws` が1ノードに2件の改正を合流させる。
    """
    day = datetime.date(2026, 4, 1)
    first = uris.law_version_uri("507M60000100010", day, "令和八年厚生労働省令第一号")
    second = uris.law_version_uri("507M60000100010", day, "令和八年厚生労働省令第二号")

    assert first != second, "改正法令番号が違うのに同じURIになった"
    assert first == (
        f"{TEST_BASE}/id/law/507M60000100010/20260401_"
        "%E4%BB%A4%E5%92%8C%E5%85%AB%E5%B9%B4%E5%8E%9A%E7%94%9F%E5%8A%B4%E5%83%8D%E7%9C%81%E4%BB%A4%E7%AC%AC%E4%B8%80%E5%8F%B7"
    )


def test_law_version_uri_falls_back_to_date_only_when_amendment_law_num_is_absent():
    """改正法令番号が無い場合は従来どおり日付のみのURI(後方互換)。"""
    assert uris.law_version_uri("507M60000100010", datetime.date(2026, 8, 1), None) == (
        f"{TEST_BASE}/id/law/507M60000100010/20260801"
    )


def test_unresolved_jurisdiction_uri_is_keyed_by_law_id_and_name():
    """law_id と name の両方が材料になること。

    何があれば落ちるか: name だけで鍵にすると、同じ旧省庁名を指す別の法令が
    同一のURIに収束し、CQ9が数えたい「法令ごとの件数」が測れなくなる
    """
    a = uris.unresolved_jurisdiction_uri("326M50000400100", "大蔵省")
    b = uris.unresolved_jurisdiction_uri("331M50000400200", "大蔵省")
    assert a != b
    assert a == f"{TEST_BASE}/id/unresolved/jurisdiction/326M50000400100/%E5%A4%A7%E8%94%B5%E7%9C%81"


def test_unresolved_jurisdiction_uri_rejects_empty_parts():
    with pytest.raises(ValueError):
        uris.unresolved_jurisdiction_uri("", "大蔵省")
    with pytest.raises(ValueError):
        uris.unresolved_jurisdiction_uri("326M50000400100", "")


def test_graph_uri_encodes_source_and_date():
    assert uris.graph_uri("houjin-bangou", datetime.date(2026, 8, 1)) == (
        f"{TEST_BASE}/graph/houjin-bangou/2026-08-01"
    )


def test_term_uri_uses_fragment():
    assert uris.term_uri("org", "所管") == f"{TEST_BASE}/def/org#所管"


def test_base_uri_trailing_slash_is_normalized(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://uri-test.invalid/kg/")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    assert Settings().base_uri == "https://uri-test.invalid/kg"


# =============================================================================
# budget_uri / expenditure_uri(Task 7 brief §URI規約、B-S2)
# =============================================================================


def test_budget_uri_uses_fiscal_year_and_project_id():
    assert uris.budget_uri("2025", "828") == f"{TEST_BASE}/id/budget/2025/828"


def test_budget_uri_distinguishes_the_same_project_across_fiscal_years():
    """`project_id` 単独では同一性が決まらないこと(budget.yaml の projectId docstring)。

    同じ事業(project_id)でも予算年度が違えば別のBudgetProjectノードになる。
    """
    a = uris.budget_uri("2025", "159")
    b = uris.budget_uri("2023", "159")
    assert a != b


def test_budget_uri_rejects_empty_parts():
    with pytest.raises(ValueError):
        uris.budget_uri("", "828")
    with pytest.raises(ValueError):
        uris.budget_uri("2025", "")


def test_expenditure_uri_nests_under_the_budget_project_by_sequence():
    assert uris.expenditure_uri("2025", "1", 0) == f"{TEST_BASE}/id/budget/2025/1/0"
    first = uris.expenditure_uri("2025", "1", 0)
    second = uris.expenditure_uri("2025", "1", 1)
    assert first != second


def test_expenditure_uri_rejects_a_negative_sequence():
    with pytest.raises(ValueError):
        uris.expenditure_uri("2025", "1", -1)


def test_unresolved_budget_ministry_uri_is_keyed_by_project_not_just_name():
    """同じ未突合の府省名を指す別の事業が、1ノードに収束しないこと。"""
    a = uris.unresolved_budget_ministry_uri("2025", "1", "存在しない省")
    b = uris.unresolved_budget_ministry_uri("2025", "2", "存在しない省")
    assert a != b


def test_unresolved_budget_ministry_uri_is_distinct_from_the_reference_table_axis():
    """`unresolved_ministry_uri`(参照表の突合失敗)と同じ名称でも別のURIになること。

    2つは別の軸(参照表の1行 vs 個々の予算事業)の未解決なので、
    衝突してはならない。
    """
    from jgkg.uris import unresolved_ministry_uri

    a = uris.unresolved_budget_ministry_uri("2025", "1", "存在しない省")
    b = unresolved_ministry_uri("存在しない省")
    assert a != b


def test_unresolved_basis_law_uri_is_keyed_by_project():
    a = uris.unresolved_basis_law_uri("2025", "1", "大蔵省令")
    b = uris.unresolved_basis_law_uri("2025", "2", "大蔵省令")
    assert a != b


def test_unresolved_recipient_uri_nests_under_the_expenditure():
    uri = uris.unresolved_recipient_uri("2025", "1", 0, "その他")
    assert uri.startswith(uris.expenditure_uri("2025", "1", 0))


def test_unresolved_uri_helpers_reject_empty_parts():
    with pytest.raises(ValueError):
        uris.unresolved_budget_ministry_uri("", "1", "省")
    with pytest.raises(ValueError):
        uris.unresolved_basis_law_uri("2025", "", "省")
    with pytest.raises(ValueError):
        uris.unresolved_recipient_uri("2025", "1", 0, "")
