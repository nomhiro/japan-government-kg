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


def test_org_uri_rejects_fullwidth_digit_houjin_bangou():
    """全角数字13桁は拒否すること(裁定B22)。

    Pythonの`\\d`は既定でUnicode対応で全角数字(U+FF10-FF19)にもマッチする。
    実測: 全角の"９９９９９９９９９９９９９"は`\\d{13}`にマッチしつつ`int()`は
    ASCII表記("9999999999999")と同じ整数値にパースされる — つまり見た目も
    符号位置も違う2つの文字列が、dedup_organizationsのキー(`int(houjin_bangou)`)
    では同一視されてしまう(意図しない衝突)。`[0-9]`はASCII専用にする。
    """
    fullwidth = "９" * 13  # "9999999999999" の全角表記
    with pytest.raises(ValueError, match="13桁の数字"):
        uris.org_uri(fullwidth)


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


# =============================================================================
# 資金の流れ(裁定B97): 支出先ブロック・国自らが支出する間接経費
# =============================================================================


def test_expenditure_block_uri_is_keyed_by_the_rs_block_number_not_a_sequence():
    """ブロックのURIがRSのブロック番号("A"/"B")そのものから決まること。

    何があれば落ちるか: `expenditure_uri`と同じ連番方式にすると、5-2が
    「支出元ブロック='B'」と書いている辺を張るために行順→連番の対応表が
    必要になる。ここはブロック番号を直接URIに埋めることを固定する。
    """
    assert (
        uris.expenditure_block_uri("2025", "6494", "A")
        == f"{TEST_BASE}/id/budget/2025/6494/block/A"
    )


def test_expenditure_block_uri_distinguishes_blocks_within_the_same_project():
    """児童手当等交付金の2つの段(A=市町村 / B=児童手当受給者)が別ノードになること。

    同額(1,401,293,745,413円)が2ブロックに現れる実データなので、ここが
    同じURIに潰れると「段を区別して合計する」ことが原理的にできなくなる。
    """
    a = uris.expenditure_block_uri("2025", "6494", "A")
    b = uris.expenditure_block_uri("2025", "6494", "B")
    assert a != b


def test_expenditure_block_uri_is_keyed_by_project_and_fiscal_year_too():
    """ブロック番号は事業ごとに振り直されるので、事業/年度が違えば別ノードになること
    (budget.yaml の `blockId` docstring: 単独では一意でない)。
    """
    assert uris.expenditure_block_uri("2025", "6494", "A") != uris.expenditure_block_uri(
        "2025", "1406", "A"
    )
    assert uris.expenditure_block_uri("2025", "6494", "A") != uris.expenditure_block_uri(
        "2024", "6494", "A"
    )


def test_expenditure_block_uri_does_not_collide_with_an_expenditure_uri():
    """支出(連番)とブロック(`/block/`配下)のURI空間が交わらないこと。

    何があれば落ちるか: `/block/`を挟まずブロック番号を直付けする実装にすると、
    ブロック番号が数字のRS更新が来た瞬間に支出の連番と衝突する。
    """
    block_uris = {uris.expenditure_block_uri("2025", "1", b) for b in ("A", "B", "0", "1")}
    expenditure_uris = {uris.expenditure_uri("2025", "1", s) for s in range(4)}
    assert not (block_uris & expenditure_uris)


def test_indirect_cost_uri_is_keyed_by_the_item_name():
    """間接経費のURIが項目名から決まり、同じ事業の別項目が別ノードになること
    (実測: 2,432行すべてで(年度, 事業, 項目名)が一意)。
    """
    a = uris.indirect_cost_uri("2025", "1", "講師謝金")
    b = uris.indirect_cost_uri("2025", "1", "委員等旅費")
    assert a != b
    assert a.startswith(f"{TEST_BASE}/id/budget/2025/1/indirect-cost/")


def test_indirect_cost_uri_percent_encodes_the_item_name():
    """項目名は日本語の自由記述なので、URIに生のまま入らないこと。

    何があれば落ちるか: `quote(..., safe="")`を外すと、スラッシュを含む項目名
    (「旅費/謝金」のような書き方)がパスを1段増やして別の事業のURI空間に
    侵入し得る。
    """
    uri = uris.indirect_cost_uri("2025", "1", "旅費/謝金")
    assert "旅費" not in uri
    assert "/謝金" not in uri
    assert uri.rsplit("/", 1)[0] == f"{TEST_BASE}/id/budget/2025/1/indirect-cost"


def test_block_and_indirect_cost_uris_reject_empty_keys():
    with pytest.raises(ValueError):
        uris.expenditure_block_uri("2025", "1", "")
    with pytest.raises(ValueError):
        uris.indirect_cost_uri("2025", "1", "")
    with pytest.raises(ValueError):
        uris.expenditure_block_uri("", "1", "A")
    with pytest.raises(ValueError):
        uris.indirect_cost_uri("2025", "", "講師謝金")
