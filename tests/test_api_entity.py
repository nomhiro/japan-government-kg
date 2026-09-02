"""エンティティ詳細(`jgkg.api.queries.get_entity_detail`)のテスト。

`tests/phase1_fixture.py`のfixtureに対して、`RdflibKGClient`経由で実行する
(実ネットワーク無し)。対象はPROJECT_CORE(厚生労働省・FY2025・支出4件・
basisLaw1件——出典・関係の向き・グループ化・上限のすべてを1つの実体で
確認できる)。値の出典は`tests/phase1_fixture.py`のdocstringを正とする。
"""
import datetime

import phase1_fixture as fx
import pytest
from rdflib import Dataset, Literal, URIRef

from jgkg.api.kgclient import RdflibKGClient
from jgkg.api.queries import get_entity_detail

BASE = "https://jgkg.norr-tech.com"
PROJECT_CORE_ID = f"budget/2025/{fx.PROJECT_CORE}"
#: 厚生労働省。**属性の出典グラフ(houjin-bangou)が関係の出典グラフ
#: (rs-system/egov-law/egov-law-data)のいずれとも重ならない**——
#: `test_every_attribute_graph_key_exists_in_the_graphs_map`が
#: `_hydrate_graphs`の追加マージ(queries.pyの`get_entity_detail`)を
#: 実際に運動させるために、PROJECT_COREではなくこちらを使う(PROJECT_CORE
#: の属性グラフはrs-system一本で、関係のrs-systemと重なってしまい、
#: マージを外しても偶然通ってしまう)
MINISTRY_ID = f"org/{fx.KOUSEIROUDOU_BANGOU}"


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
    # **裁定B82(4a): 属性の値は`AttributeValue`(値+出典グラフキーの一覧)**
    # であり、素の`str`ではない——`.value`で値を取り出す
    assert [v.value for v in detail.attributes["projectId"]] == [fx.PROJECT_CORE]
    assert [v.value for v in detail.attributes["fiscalYear"]] == ["2025"]
    assert [v.value for v in detail.attributes["budgetAmount"]] == ["100000000"]
    joined_predicates = set(detail.attributes)
    assert "type" not in joined_predicates
    assert "prefLabel" not in joined_predicates


# =============================================================================
# 属性の出典(裁定B82(4a): 仕様§9.2の未達を直す。関係と同じCQ7の3項+グラフ)
# =============================================================================


def test_entity_detail_attributes_carry_provenance(client):
    """属性にも出典が付く。関係と同じ、`graphs`マップへのキー参照
    (単数ではなく`graphs: list[str]`——理由は`models.py`の`AttributeValue`)。

    **空虚にしない**: 「1件以上出典を持つ」ではなく、出典を持つ属性の
    **値の件数**をアサートする(PROJECT_COREのbudget属性4件: projectId・
    projectName・fiscalYear・budgetAmount。`src/jgkg/rdf/emit.py`の
    `emit_budget`が`BudgetProject`に書く非除外リテラルの全量と一致する)。
    """
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None

    graph_key = detail.attributes["fiscalYear"][0].graphs[0]
    assert graph_key == f"{BASE}/graph/rs-system/{fx.DAY.isoformat()}"
    prov = detail.graphs[graph_key]
    assert prov.graph == graph_key
    assert prov.source, "sourceが空"
    assert prov.fetched_on, "fetched_onが空"
    assert prov.license, "licenseが空"

    values_with_provenance = [
        av
        for values in detail.attributes.values()
        for av in values
        if av.graphs
    ]
    assert len(values_with_provenance) == 4, detail.attributes  # projectId/projectName/fiscalYear/budgetAmount
    assert all(prov_key in detail.graphs for av in values_with_provenance for prov_key in av.graphs)


def test_every_attribute_graph_key_exists_in_the_graphs_map(client):
    """**`models.py`が宣言した保証をテストで縛る**(関係と同じ形。
    `test_every_relationship_graph_key_exists_in_the_graphs_map`参照):
    応答に現れるすべての`AttributeValue.graphs`のキーが`graphs`に
    存在すること。

    **MINISTRY_IDを使う理由**: PROJECT_COREだと属性の出典グラフ
    (rs-system)が関係の出典グラフとたまたま重なり、`get_entity_detail`の
    `_hydrate_graphs`追加マージ(属性専用の経路)を1行も通らなくても
    このテストが偶然通ってしまう(壊し確認で実際に確認した。気になる点参照)。
    MINISTRY_IDは属性の出典(houjin-bangou)が関係の出典(rs-system等)と
    重ならないため、マージが無いと確実に落ちる。

    **空虚にしない**: 検査対象の属性出典が0件なら落ちる。
    """
    detail = get_entity_detail(client, BASE, MINISTRY_ID, limit=50)
    assert detail is not None
    keys = [g for values in detail.attributes.values() for av in values for g in av.graphs]
    assert keys, "検査対象の属性の出典グラフが0件(前提が崩れている)"
    missing = sorted({k for k in keys if k not in detail.graphs})
    assert not missing, f"graphsマップに存在しないキーが属性から参照されている: {missing}"


def test_entity_detail_attribute_provenance_marks_availability_false_when_missing(kg, client):
    """壊し確認: 属性の出典グラフからprovenanceの記述を外すと、
    (a) 属性は消えない (b) その出典が`available=False`になる。

    `tests/test_api_graph.py`の
    `test_neighborhood_marks_a_graph_whose_provenance_is_missing`と同じ形。
    関係は出典を必須で結合しているため出典が無ければ関係自体が消える
    (`test_entity_detail_relationships_disappear_if_provenance_is_removed`)
    ——属性は必須結合しない選択にした(裁定B82(4a)。`queries.py`の
    `_build_attributes_query`docstring参照)ため、挙動が違う。ここで固定する。
    """
    before = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert before is not None
    assert before.attributes, "壊す前から属性が無い(前提が崩れている)"
    assert all(p.available for p in before.graphs.values()), (
        f"壊す前からavailable=Falseのグラフがある: {before.graphs}"
    )

    target_graph = before.attributes["fiscalYear"][0].graphs[0]

    prov_graph = kg.graph(URIRef(f"{BASE}/graph/provenance"))
    removed = list(prov_graph.triples((URIRef(target_graph), None, None)))
    assert removed, f"除去対象のprovenanceトリプルが見つからない: {target_graph}"
    for triple in removed:
        prov_graph.remove(triple)

    after = get_entity_detail(RdflibKGClient(kg), BASE, PROJECT_CORE_ID, limit=50)
    assert after is not None
    assert after.attributes.get("fiscalYear"), (
        "provenanceを外したのに属性が消えている(黙って落としてはいけない。裁定B82(4a))"
    )
    prov = after.graphs[target_graph]
    assert prov.available is False, f"出典が引けないのにavailable=Trueのまま: {prov}"
    assert prov.source == ""
    assert prov.graph == target_graph, "キーだけ落として消費者に不在を扱わせていない"


def test_entity_detail_attribute_value_not_duplicated_when_multiple_graphs_assert_it(kg, client):
    """同じ値が複数の名前付きグラフから主張される場合、値の行は複製されない
    (裁定B82(4a): `AttributeValue.graphs`は複数キーを持てる)。

    **fixtureにこの状況が無い**(tests/phase1_fixture.pyのPROJECT_COREの
    budget属性は`rs-system`1本からしか主張されない)。実データ(Fuseki
    884,052クアッド。2026-09-02実測)では`org:cityName`・`org:houjinBangou`
    等の属性値を複数の名前付きグラフが同じ値で主張する組が実在すると
    確認済みなので、ここでは`fx.ROGUE_REVISION_URI`と同じ「直接注入」の
    作法で、その状況をfixtureに追加してから検査する。
    """
    from jgkg.rdf.provenance import provenance_graph
    from jgkg.uris import budget_uri, graph_uri

    entity_uri = URIRef(budget_uri("2025", fx.PROJECT_CORE))
    mirror_day = fx.DAY + datetime.timedelta(days=1)
    mirror_graph_uri = URIRef(graph_uri("rs-system", mirror_day))
    kg.graph(mirror_graph_uri).add(
        (entity_uri, URIRef(f"{BASE}/def/budget#fiscalYear"), Literal(2025))
    )
    prov_graph = kg.graph(URIRef(f"{BASE}/graph/provenance"))
    for triple in provenance_graph(str(mirror_graph_uri), "rs-system", mirror_day):
        prov_graph.add(triple)

    detail = get_entity_detail(RdflibKGClient(kg), BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None
    fiscal_year_values = detail.attributes["fiscalYear"]
    assert len(fiscal_year_values) == 1, (
        f"同じ値が複数グラフから主張されて値の行が複製された: {fiscal_year_values}"
    )
    assert fiscal_year_values[0].value == "2025"
    original_graph = f"{BASE}/graph/rs-system/{fx.DAY.isoformat()}"
    assert set(fiscal_year_values[0].graphs) == {original_graph, str(mirror_graph_uri)}, (
        fiscal_year_values[0].graphs
    )


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
    """`graphs` に、どの関係**または属性**からも参照されないグラフを入れない
    (**送る意味の無いデータを応答に混ぜない**。決定#33: 件数上限は
    外向き通信量のコスト対策でもある)。

    **裁定B82(4a)で「関係」から「関係または属性」に直した**——属性にも
    出典が付くようになったため、属性だけが参照するグラフ(このKGでは
    budget属性が指す`rs-system`)を「関係からは参照されない」という理由で
    未参照と誤判定してはならない。
    """
    detail = get_entity_detail(client, BASE, PROJECT_CORE_ID, limit=50)
    assert detail is not None
    referenced = {rel.graph for rels in detail.relationships.values() for rel in rels}
    referenced |= {g for values in detail.attributes.values() for av in values for g in av.graphs}
    assert detail.graphs, "graphsが空(前提が崩れている)"
    unreferenced = sorted(set(detail.graphs) - referenced)
    assert not unreferenced, f"どの関係・属性からも参照されないgraphsのエントリ: {unreferenced}"


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
