"""検索(`jgkg.api.queries.search_entities`)のテスト。

`tests/phase1_fixture.py`のfixtureに対して、`RdflibKGClient`経由で実行する
——`tests/test_competency_questions_phase1.py`の`kg`フィクスチャと同じ土台
(実ネットワーク無し)。値の出典・実在確認は同ファイルのdocstringを正とする。
"""
import phase1_fixture as fx
import pytest
from rdflib import Dataset

from jgkg.api.kgclient import RdflibKGClient
from jgkg.api.queries import SEARCH_MAX_LIMIT, search_entities

BASE = "https://jgkg.norr-tech.com"


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", BASE)
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def kg(tmp_path) -> Dataset:
    return fx.build_dataset(tmp_path / "out")


@pytest.fixture
def client(kg) -> RdflibKGClient:
    return RdflibKGClient(kg)


# =============================================================================
# 型混在(D-3ブリーフの壊し確認要求そのもの)+ 重複型のdedup
# =============================================================================


def test_search_returns_mixed_types_for_a_shared_substring(client):
    """「厚生労働省」はMinistry(厚生労働省そのもの)とLaw(題名に「厚生労働省令」
    を含むKOUSEIROUDOU_LAW_ID)の両方に部分一致する——型混在の正のコントロール。

    厚生労働省のURIは実際にはorg:GovernmentOrgan(houjin-bangou由来)と
    org:Ministry(ministry-codes由来)の2つのrdf:typeを持つ(D-3設計時に
    fixtureで実測)。dedupしなければMinistry/GovernmentOrganの重複2件が
    返ってしまう——ここでは「型混在」と「重複除去」を同時に確認する。
    """
    resp = search_entities(client, BASE, "厚生労働省", limit=20)
    by_type = {hit.type for hit in resp.results}
    assert "Ministry" in by_type, f"Ministryが無い(型混在の前提が崩れている): {resp.results}"
    assert "Law" in by_type, f"Lawが無い(型混在の前提が崩れている): {resp.results}"

    ministry_hits = [h for h in resp.results if h.id == f"{BASE}/id/org/{fx.KOUSEIROUDOU_BANGOU}"]
    assert len(ministry_hits) == 1, (
        f"重複型(GovernmentOrgan/Ministry)のdedupに失敗した: {ministry_hits}"
    )
    assert ministry_hits[0].type == "Ministry", "最も具体的な型(Ministry)が選ばれていない"
    assert ministry_hits[0].label == "厚生労働省"
    assert ministry_hits[0].id_path == f"org/{fx.KOUSEIROUDOU_BANGOU}", (
        "id_pathがget_entity_detailの期待する経路形と一致しない(裁定B59)"
    )

    law_hits = [h for h in resp.results if h.id == f"{BASE}/id/law/{fx.KOUSEIROUDOU_LAW_ID}"]
    assert len(law_hits) == 1, law_hits
    assert law_hits[0].type == "Law"
    assert law_hits[0].summary == fx.KOUSEIROUDOU_LAW_NUM, "Lawの要約は法令番号のはず"
    assert law_hits[0].id_path == f"law/{fx.KOUSEIROUDOU_LAW_ID}"


def test_search_single_type_result_when_substring_is_unique(client):
    """比較対象: 型混在ではない場合(WOLFSTYLE)が単一型で返ることの確認
    (上のテストの「型混在」が偶然ではなく、実際にクエリが型ごとに正しく
    振る舞っていることの負のコントロール)。
    """
    resp = search_entities(client, BASE, fx.WOLFSTYLE_NAME, limit=20)
    by_type = {hit.type for hit in resp.results}
    assert by_type == {"Organization"}, by_type


# =============================================================================
# 型ごとの要約(法令=法令番号、法人=所在地、事業=年度と府省)
# =============================================================================


def test_search_organization_summary_is_prefecture_and_city(client):
    resp = search_entities(client, BASE, fx.WOLFSTYLE_NAME, limit=20)
    hits = [h for h in resp.results if h.id == f"{BASE}/id/org/{fx.WOLFSTYLE_BANGOU}"]
    assert len(hits) == 1, hits
    assert hits[0].summary == "東京都中央区"


def test_search_budget_project_summary_is_fiscal_year_and_ministry(client):
    resp = search_entities(client, BASE, "地域医療体制強化推進事業", limit=20)
    hits = [h for h in resp.results if h.type == "BudgetProject"]
    assert len(hits) == 1, hits
    assert hits[0].summary == "2025年度・厚生労働省"


# =============================================================================
# 上限(既定は止まる側)
# =============================================================================


def test_search_truncated_is_false_when_limit_covers_all_matches(client):
    """壊し確認の前提: 「架空」は法令4件(tests/phase1_fixture.pyのlaw_title
    全て)+事業3件(project_nameが全て「(架空)...」)の計7件以上に一致する
    ——十分な数の正のコントロール。
    """
    resp = search_entities(client, BASE, "架空", limit=SEARCH_MAX_LIMIT)
    assert len(resp.results) >= 4, f"前提(複数件一致)が崩れている: {resp.results}"
    assert resp.truncated is False


def test_search_truncated_is_true_when_limit_is_smaller_than_matches(client):
    resp = search_entities(client, BASE, "架空", limit=2)
    assert resp.truncated is True, "候補が上限より多いのにtruncatedがFalseのままだった"
    assert len(resp.results) == 2


# =============================================================================
# 空虚な検査にしない(0件を素通りさせない)
# =============================================================================


def test_search_no_match_returns_empty_results_not_error(client):
    resp = search_entities(client, BASE, "存在しない検索語XYZ", limit=20)
    assert resp.results == []
    assert resp.truncated is False
