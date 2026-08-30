"""エンティティ詳細(`jgkg.api.queries.get_entity_detail`)のテスト。

`tests/phase1_fixture.py`のfixtureに対して、`RdflibKGClient`経由で実行する
(実ネットワーク無し)。対象はPROJECT_CORE(厚生労働省・FY2025・支出4件・
basisLaw1件——出典・関係の向き・グループ化・上限のすべてを1つの実体で
確認できる)。値の出典は`tests/phase1_fixture.py`のdocstringを正とする。
"""
import phase1_fixture as fx
import pytest
from rdflib import Dataset, URIRef

from jgkg.api.kgclient import RdflibKGClient
from jgkg.api.queries import get_entity_detail

BASE = "https://jgkg.norr-tech.com"
PROJECT_CORE_ID = f"budget/2025/{fx.PROJECT_CORE}"


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
# 存在しないエンティティ
# =============================================================================


def test_entity_detail_returns_none_for_nonexistent_entity(client):
    assert get_entity_detail(client, BASE, "org/0000000000000", limit=50) is None


# =============================================================================
# 属性(type/labelを除く。スキーマで決まる有限個なので上限を付けない)
# =============================================================================


def test_entity_detail_attributes_exclude_type_and_label(client):
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None
    assert detail.type == "BudgetProject"
    assert detail.label == "(架空)地域医療体制強化推進事業"
    assert detail.id_path == PROJECT_CORE_ID, (
        "id_pathは呼び出しに渡したid_pathと一致するはず(裁定B59: "
        "_id_pathがentity_uriから再導出しても値は変わらない)"
    )
    assert detail.attributes["projectId"] == [fx.PROJECT_CORE]
    assert detail.attributes["fiscalYear"] == ["2025"]
    assert detail.attributes["budgetAmount"] == ["100000000"]
    joined_predicates = set(detail.attributes)
    assert "type" not in joined_predicates
    assert "prefLabel" not in joined_predicates


# =============================================================================
# 関係の向きを両方(D-3ブリーフ) + 型別グループ化
# =============================================================================


def test_entity_detail_includes_both_outgoing_and_incoming_relationships(client):
    """PROJECT_COREはoutgoing 2件(所管府省=Ministry・根拠法令=Law)、
    incoming 4件(この事業からの支出=Expenditure。tests/phase1_fixture.py
    のPROJECT_CORE定義: 解決1/未解決1/束ね1/センチネル1の計4件)を持つ。
    """
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None

    assert "Ministry" in detail.relationships, detail.relationships
    assert len(detail.relationships["Ministry"]) == 1
    assert detail.relationships["Ministry"][0].direction == "outgoing"
    ministry_ref = detail.relationships["Ministry"][0].related
    assert ministry_ref.id == f"{BASE}/id/org/{fx.KOUSEIROUDOU_BANGOU}"
    assert ministry_ref.id_path == f"org/{fx.KOUSEIROUDOU_BANGOU}", (
        "関係の相手側(queries.py:383)のEntityRefにもid_pathが要る(裁定B59-(2))。"
        "SearchHitだけ直すと詳細→関係の相手→詳細の遷移に同じ欠陥が残る"
    )

    assert "Law" in detail.relationships, detail.relationships
    assert len(detail.relationships["Law"]) == 1
    assert detail.relationships["Law"][0].direction == "outgoing"
    law_ref = detail.relationships["Law"][0].related
    assert law_ref.id == f"{BASE}/id/law/{fx.OLD_KOUSEISHO_LAW_ID}"
    assert law_ref.id_path == f"law/{fx.OLD_KOUSEISHO_LAW_ID}"

    assert "Expenditure" in detail.relationships, detail.relationships
    assert len(detail.relationships["Expenditure"]) == 4, detail.relationships["Expenditure"]
    assert all(r.direction == "incoming" for r in detail.relationships["Expenditure"])

    directions = {r.direction for rels in detail.relationships.values() for r in rels}
    assert directions == {"outgoing", "incoming"}, "両方向のはずが片方しか無い"


def test_entity_detail_top_level_type_is_the_most_specific_when_dual_typed(client):
    """厚生労働省はorg:GovernmentOrgan/org:Ministryの重複型を持つ(検索側と
    同じ実測。tests/test_api_search.pyのコメント参照)。エンティティ詳細の
    typeフィールドも最も具体的な型(Ministry)を選ぶこと。
    """
    detail = get_entity_detail(client, BASE, f"org/{fx.KOUSEIROUDOU_BANGOU}", limit=50)
    assert detail is not None
    assert detail.type == "Ministry", detail.type
    assert detail.label == "厚生労働省"


# =============================================================================
# 各関係の出典(D-3ブリーフ「各関係に出典」。CQ7と同じ3項+グラフ)
# =============================================================================


def test_entity_detail_relationships_carry_provenance(client):
    """関係に出典が付く。**ただし埋め込みではなく`graphs`マップへのキー参照**
    (D-4の裁定2で正規化した)。
    """
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None
    graph_key = detail.relationships["Ministry"][0].graph
    assert graph_key == f"{BASE}/graph/rs-system/{fx.DAY.isoformat()}"
    prov = detail.graphs[graph_key]
    assert prov.graph == graph_key
    assert prov.source, "sourceが空"
    assert prov.fetched_on, "fetched_onが空"
    assert prov.license, "licenseが空"


def test_every_relationship_graph_key_exists_in_the_graphs_map(client):
    """**`models.py`が宣言した保証をテストで縛る**: 応答に現れるすべての
    `Relationship.graph` が `graphs` に存在すること(消費者はキーの不在を
    扱わなくてよい)。

    **空虚にしない**: 検査対象の辺が0件なら落ちる。
    """
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None
    keys = [rel.graph for rels in detail.relationships.values() for rel in rels]
    assert keys, "検査対象の関係が0件(前提が崩れている)"
    missing = sorted({k for k in keys if k not in detail.graphs})
    assert not missing, f"graphsマップに存在しないキーが関係から参照されている: {missing}"


def test_graphs_map_has_no_unreferenced_entries(client):
    """`graphs` に、どの関係からも参照されないグラフを入れない
    (**送る意味の無いデータを応答に混ぜない**。決定#33: 件数上限は
    外向き通信量のコスト対策でもある)。
    """
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None
    referenced = {rel.graph for rels in detail.relationships.values() for rel in rels}
    assert detail.graphs, "graphsが空(前提が崩れている)"
    unreferenced = sorted(set(detail.graphs) - referenced)
    assert not unreferenced, f"どの関係からも参照されないgraphsのエントリ: {unreferenced}"


def test_entity_detail_relationships_disappear_if_provenance_is_removed(kg, client):
    """壊し確認: 関係の出典(provenance)を外すと、その関係が応答から消えること。

    `queries.py`の関係クエリは`?g prov:wasDerivedFrom ...`等を**OPTIONALに
    していない**(CQ7と同じ設計)——このテストはその非OPTIONALな結合を
    実際に検査する。属性(スカラー値)はprovenanceと無関係の別クエリなので
    影響を受けないはず、という区別も同時に確認する。
    """
    before = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert before is not None
    assert before.relationships, "壊す前から関係が無い(前提が崩れている)"

    data_graph_uri = URIRef(f"{BASE}/graph/rs-system/{fx.DAY.isoformat()}")
    prov_graph = kg.graph(URIRef(f"{BASE}/graph/provenance"))
    removed = list(prov_graph.triples((data_graph_uri, None, None)))
    assert removed, "除去対象のprovenanceトリプルが見つからない(前提が崩れている)"
    for triple in removed:
        prov_graph.remove(triple)

    after = get_entity_detail(RdflibKGClient(kg), BASE, PROJECT_CORE_ID, limit=50)
    assert after is not None
    assert after.relationships == {}, f"provenanceを外したのに関係が残っている: {after.relationships}"
    assert after.attributes, "属性はprovenance非依存のはずが一緒に消えている"


# =============================================================================
# 上限(既定は止まる側。全エンドポイントに付ける——部分適用を避ける)
# =============================================================================


def test_entity_detail_relationships_not_truncated_when_limit_is_generous(client):
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None
    assert detail.relationships_truncated is False
    total = sum(len(v) for v in detail.relationships.values())
    assert total == 6, detail.relationships  # outgoing 2 + incoming 4


def test_entity_detail_relationships_truncate_with_a_small_limit(client):
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=2)
    assert detail is not None
    assert detail.relationships_truncated is True
    total = sum(len(v) for v in detail.relationships.values())
    assert total == 2, detail.relationships
