"""近傍サブグラフ(`/neighborhood/{id}`)とパス探索(`/path`)のテスト(D-4)。

**アプリ層(`TestClient`)で書く。** 裁定B59-(5)とB69が示したとおり、
`:path`ルートコンバータとStarletteのデコードを含めて初めて出る欠陥がある
——関数を直接呼ぶテストでは出ない。

**入力の選び方に注意する(観察O14)。** このセッションで「アサーションは
正しいのに、入力に何を選んだかで欠陥を素通りさせた」ことが3回起きた。
ここでは意図的に:
- **`%`を含むIRI**を持つノード(`AbolishedGovernmentOrgan` = 厚生省)
- **辺を1本も持たない**ノード(`LawRevision`。実データで9,550件。観察O10)
- **次数の大きいノード**(ハブ。分岐数の上限が効く)
を選ぶ。
"""
from __future__ import annotations

import phase1_fixture as fx
import pytest
from fastapi.testclient import TestClient
from rdflib import Dataset

from jgkg.api.app import create_app
from jgkg.api.kgclient import RdflibKGClient
from jgkg.api.queries import (
    NEIGHBORHOOD_MAX_DEPTH,
    PATH_MAX_MAX_DEPTH,
)

BASE = "https://jgkg.norr-tech.com"

#: 次数6のハブ(fixtureで最大)。厚生労働省・FY2025・basisLaw有・支出3件+sentinel1件
HUB_PROJECT = f"budget/2025/{fx.PROJECT_CORE}"
#: 厚生労働省(次数5)
MINISTRY = f"org/{fx.KOUSEIROUDOU_BANGOU}"
#: 支出先法人(resolvedな受け取り手)
RECIPIENT_ORG = f"org/{fx.WOLFSTYLE_BANGOU}"
#: 厚生労働省令(この事業のbasisLaw)
LAW = f"law/{fx.KOUSEIROUDOU_LAW_ID}"
#: **`%`を含むIRIを持つノード**(次数2)。`uris.py`が名称をpercent-encodeする
ABOLISHED = f"org/abolished/{fx.OLD_KOUSEISHO_NAME}"


@pytest.fixture(autouse=True)
def _allow_loopback(allow_loopback_for_asgi_testclient):
    """`TestClient`のためのループバック限定の抜け穴を要求する。

    定義は`tests/conftest.py`に1本化されている(`test_api_app.py`と共有)。
    """
    yield


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
def client(kg) -> TestClient:
    return TestClient(create_app(client=RdflibKGClient(kg), base_uri=BASE))


def _percent_nodes(kg) -> list[str]:
    """fixtureの実行時グラフにある`%`含みIRIを数える(空虚なテストにしないため)。"""
    prefix = f"{BASE}/id/"
    found = set()
    for s, _p, o, _g in kg.quads((None, None, None, None)):
        for term in (s, o):
            t = str(term)
            if t.startswith(prefix) and "%" in t:
                found.add(t)
    return sorted(found)


# =============================================================================
# 近傍サブグラフ
# =============================================================================


def test_neighborhood_depth_one_returns_center_and_its_neighbors(client):
    r = client.get(f"/neighborhood/{HUB_PROJECT}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["center"]["id"] == f"{BASE}/id/{HUB_PROJECT}"
    assert body["depth"] == 1
    assert body["edges"], "辺が0本(前提が崩れている)"
    ids = {n["id"] for n in body["nodes"]}
    assert body["center"]["id"] in ids, "中心がnodesに含まれていない"
    assert f"{BASE}/id/{MINISTRY}" in ids, "深さ1で府省に届いていない"


def test_neighborhood_depth_two_reaches_further_than_depth_one(client):
    one = client.get(f"/neighborhood/{HUB_PROJECT}", params={"depth": 1}).json()
    two = client.get(f"/neighborhood/{HUB_PROJECT}", params={"depth": 2}).json()
    assert len(two["nodes"]) > len(one["nodes"]), (
        "深さ2が深さ1よりノードを増やしていない(探索が広がっていない)"
    )
    assert f"{BASE}/id/{RECIPIENT_ORG}" in {n["id"] for n in two["nodes"]}, (
        "深さ2で支出先法人に届いていない"
    )


def test_neighborhood_fanout_limit_appears_in_the_response(client):
    """**分岐数の上限が効いたことが応答に現れる。**

    総数の上限だけではハブ1個が予算を食い潰し、利用者には「そこには何も
    無い」と見える(このプロジェクトが繰り返し扱う「報告が嘘をつく」型)。
    """
    r = client.get(f"/neighborhood/{HUB_PROJECT}", params={"depth": 1, "fanout_limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fanout_limit"] == 2
    assert body["fanout_truncated_nodes"] == [f"{BASE}/id/{HUB_PROJECT}"], (
        "分岐数の上限で切ったのに、それが応答に現れていない"
    )
    assert len(body["edges"]) <= 2


def test_neighborhood_fanout_limit_is_not_reported_when_it_does_not_bite(client):
    """壊し確認の対: 上限が効かないときは`fanout_truncated_nodes`が空であること。

    これが無いと「常に切ったと言う」実装でも上のテストが通ってしまう。
    """
    body = client.get(
        f"/neighborhood/{HUB_PROJECT}", params={"depth": 1, "fanout_limit": 100}
    ).json()
    assert body["fanout_truncated_nodes"] == [], body["fanout_truncated_nodes"]


def test_neighborhood_node_limit_appears_in_the_response(client):
    body = client.get(
        f"/neighborhood/{HUB_PROJECT}", params={"depth": 2, "node_limit": 2}
    ).json()
    assert body["nodes_truncated"] is True, "ノード数の上限で切ったのに応答に現れていない"
    assert len(body["nodes"]) <= 2


def test_neighborhood_edge_limit_appears_in_the_response(client):
    body = client.get(
        f"/neighborhood/{HUB_PROJECT}", params={"depth": 2, "edge_limit": 1}
    ).json()
    assert body["edges_truncated"] is True, "エッジ数の上限で切ったのに応答に現れていない"
    assert len(body["edges"]) <= 1


def test_every_neighborhood_edge_graph_key_exists_in_the_graphs_map(client):
    body = client.get(f"/neighborhood/{HUB_PROJECT}", params={"depth": 2}).json()
    keys = [e["graph"] for e in body["edges"]]
    assert keys, "検査対象の辺が0本(前提が崩れている)"
    missing = sorted({k for k in keys if k not in body["graphs"]})
    assert not missing, f"graphsに存在しないキーが辺から参照されている: {missing}"
    for prov in body["graphs"].values():
        assert prov["source"], f"出典のsourceが空: {prov}"
        assert prov["fetched_on"], f"出典のfetched_onが空: {prov}"
        assert prov["license"], f"出典のlicenseが空: {prov}"


def test_neighborhood_graphs_map_has_no_unreferenced_entries(client):
    body = client.get(f"/neighborhood/{HUB_PROJECT}", params={"depth": 2}).json()
    referenced = {e["graph"] for e in body["edges"]}
    assert body["graphs"], "graphsが空(前提が崩れている)"
    unreferenced = sorted(set(body["graphs"]) - referenced)
    assert not unreferenced, f"どの辺からも参照されないgraphsのエントリ: {unreferenced}"


def test_every_neighborhood_node_composes_with_entity_detail(client, kg):
    """**裁定B59/B69と同じ合成ゲートを近傍サブグラフにも適用する。**

    近傍の各ノードの`id_path`を`/entity/{それ}`に渡して200が返り、
    `id`が一致すること。**`%`を含むノードを必ず含める**(観察O14。
    このセッションで「入力の選び方」で欠陥を3回素通りさせた)。
    """
    body = client.get(f"/neighborhood/{HUB_PROJECT}", params={"depth": 2}).json()
    nodes = body["nodes"]
    assert nodes, "ノードが0件(前提が崩れている)"

    checked_percent = 0
    for node in nodes:
        r = client.get(f"/entity/{node['id_path']}")
        assert r.status_code == 200, f"{node['id_path']!r} -> {r.status_code}: {r.text}"
        assert r.json()["id"] == node["id"], (
            f"近傍のノードのidと、詳細が返すidが食い違う: "
            f"{node['id']!r} vs {r.json()['id']!r}"
        )
        if "%" in node["id_path"]:
            checked_percent += 1

    total_percent = len(_percent_nodes(kg))
    assert total_percent > 0, "fixtureに%含みIRIが無い(前提が崩れている)"
    assert checked_percent > 0, (
        f"%を含むノードを1件も検査していない(fixtureには{total_percent}件ある)"
        "——入力の選び方で欠陥を素通りさせる形(観察O14)"
    )


def _edgeless_percent_node_id_path(kg) -> str:
    """fixtureから**「辺を1本も持たず、かつ`%`を含む」IRI**のid_pathを導出する。

    **手書きしない(再発欠陥1: 導出すべき値を手書きしている)。**
    percent-encodeされた並びを書き写すのは特に壊れやすく、実際に
    controllerが一度書き写して間違えた。**fixtureの実行時グラフから探す。**

    実データでは`LawRevision`が9,550件この形である(観察O10)。
    """
    from rdflib import RDF, URIRef
    from rdflib.namespace import SKOS

    prefix = f"{BASE}/id/"
    typed: set[str] = set()
    linked: set[str] = set()
    for s, p, o, _g in kg.quads((None, None, None, None)):
        if p == RDF.type and str(s).startswith(prefix):
            typed.add(str(s))
        if p in (RDF.type, SKOS.prefLabel):
            continue
        if not isinstance(o, URIRef):
            continue
        if str(s).startswith(prefix) and str(o).startswith(prefix):
            linked.add(str(s))
            linked.add(str(o))
    candidates = sorted(u for u in typed - linked if "%" in u)
    assert candidates, "fixtureに「辺が無く%を含む」IRIが無い(このテストの前提)"
    return candidates[0][len(prefix) :]


def test_neighborhood_of_an_edgeless_node_has_no_edges(client, kg):
    """**観察O10の形をテストで固定する。**

    `LawRevision`は辺を1本も持たない(実データで9,550件)。
    **近傍が空であることは「データが無い」のではなく「辺が無い」である**
    ——`NeighborhoodResponse`のdocstringがこの限界を明記している。
    **fixtureが将来辺を持ったら、前提の変化としてここが落ちる。**
    """
    id_path = _edgeless_percent_node_id_path(kg)
    r = client.get(f"/neighborhood/{id_path}", params={"depth": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edges"] == [], f"辺を持たないはずのノードに辺がある: {body['edges']}"
    assert [n["id"] for n in body["nodes"]] == [body["center"]["id"]], (
        "辺が無いのに中心以外のノードがある"
    )
    assert body["graphs"] == {}, "辺が0本なのにgraphsが空でない"
    assert body["fanout_truncated_nodes"] == [], "切っていないのに切ったと言っている"


def test_neighborhood_404_for_unknown_entity(client):
    r = client.get("/neighborhood/org/0000000000000")
    assert r.status_code == 404, r.text


def test_neighborhood_rejects_depth_over_the_maximum(client):
    """**黙って丸めず拒否する**(`/search`のlimit超過が422を返すのと同じ作法)。"""
    r = client.get(
        f"/neighborhood/{HUB_PROJECT}", params={"depth": NEIGHBORHOOD_MAX_DEPTH + 1}
    )
    assert r.status_code == 422, r.text


def test_neighborhood_rejects_limits_over_the_maximum(client):
    for param in ("node_limit", "edge_limit", "fanout_limit"):
        r = client.get(f"/neighborhood/{HUB_PROJECT}", params={param: 10_000})
        assert r.status_code == 422, f"{param}: {r.status_code} {r.text}"


# =============================================================================
# パス探索
# =============================================================================


def test_path_from_law_to_organization_is_found(client):
    """仕様§9.1が例に挙げた「法令↔法人」の経路。"""
    r = client.get("/path", params={"from": LAW, "to": RECIPIENT_ORG})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True, body
    assert body["nodes"][0]["id"] == f"{BASE}/id/{LAW}"
    assert body["nodes"][-1]["id"] == f"{BASE}/id/{RECIPIENT_ORG}"
    assert len(body["edges"]) == len(body["nodes"]) - 1, "辺の本数がノード列と噛み合っていない"


def test_path_traverses_against_edge_direction(client):
    """**辺の向きに逆らって進むことを実際に確認する。**

    fixtureの構造(controllerが実測):

        Law <--basisLaw-- BudgetProject <--project-- Expenditure --recipient--> Organization

    **法令から法人へ行くには`basisLaw`と`project`を逆向きに辿るしかない。**
    向きを守って探索する実装ではこの経路が見つからない
    (実データでも`UnresolvedReference`は出る辺771本・入る辺0本で、
    向きを守るとほとんど何も見つからない)。
    """
    body = client.get("/path", params={"from": LAW, "to": RECIPIENT_ORG}).json()
    assert body["found"] is True
    assert body["undirected"] is True, "undirectedが応答に出ていない"

    node_ids = [n["id"] for n in body["nodes"]]
    # 辺はノード列より1本少ない(n-1本)。`node_ids[:-1]`と`node_ids[1:]`で
    # 連続する組にしてから突き合わせる
    backward = [
        e
        for e, src, dst in zip(body["edges"], node_ids[:-1], node_ids[1:], strict=True)
        if e["source"] == dst and e["target"] == src
    ]
    assert backward, (
        "経路が1本も逆向きの辺を使っていない —— このfixtureでは"
        "法令→法人が逆向きを含むはずで、前提が崩れている"
    )


def test_path_to_itself_is_found_with_no_edges(client):
    body = client.get("/path", params={"from": LAW, "to": LAW}).json()
    assert body["found"] is True
    assert body["edges"] == []
    assert [n["id"] for n in body["nodes"]] == [f"{BASE}/id/{LAW}"]


def test_path_not_found_distinguishes_depth_limit_from_exhaustion(client):
    """**「見つからなかった」と「無い」を応答の形で区別する。**

    空の結果だけを返すと利用者は後者だと読む(このプロジェクトが繰り返し
    重い欠陥として扱う「報告が嘘をつく」型)。
    """
    shallow = client.get(
        "/path", params={"from": LAW, "to": RECIPIENT_ORG, "max_depth": 1}
    ).json()
    assert shallow["found"] is False
    assert shallow["depth_limited"] is True, "深さで打ち切ったのに応答に現れていない"
    assert shallow["exhaustive"] is False, (
        "深さで打ち切ったのに「尽くした」と主張している —— これは嘘である"
    )


def test_path_not_found_reports_budget_exhaustion(client):
    """予算切れが応答に現れ、`exhaustive`が真にならないこと。"""
    body = client.get(
        "/path",
        params={"from": LAW, "to": RECIPIENT_ORG, "max_depth": 6, "visit_budget": 2},
    ).json()
    assert body["found"] is False
    assert body["budget_exhausted"] is True, "予算を使い切ったのに応答に現れていない"
    assert body["exhaustive"] is False
    assert body["visit_budget"] == 2


def test_path_reports_exhaustive_when_the_start_has_no_edges(client, kg):
    """**正しく「無い」と言えるときは言う。**

    `LawRevision`は辺を1本も持たない(観察O10)ので、そこからの経路は
    **深さや予算に関係なく存在しない** —— 片側のフロンティアが即座に
    空になるため、探索を尽くしたと言える。
    **`exhaustive=True`はここでだけ立つ**(上の2つのテストでは立たない)。
    """
    revision = _edgeless_percent_node_id_path(kg)
    detail = client.get(f"/entity/{revision}")
    assert detail.status_code == 200, f"前提(このLawRevisionが存在する)が崩れている: {detail.text}"

    resp = client.get(
        "/path",
        params={"from": revision, "to": RECIPIENT_ORG, "max_depth": 6, "visit_budget": 2000},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["found"] is False
    assert body["budget_exhausted"] is False, body
    assert body["depth_limited"] is False, body
    assert body["fanout_truncated"] is False, body
    assert body["exhaustive"] is True, (
        "辺を1本も持たないノードからの探索は尽くせるのに「尽くした」と言っていない"
    )


def test_path_404_for_unknown_endpoints(client):
    assert client.get("/path", params={"from": LAW, "to": "org/0000000000000"}).status_code == 404
    assert client.get("/path", params={"from": "org/0000000000000", "to": LAW}).status_code == 404


def test_path_rejects_max_depth_over_the_maximum(client):
    r = client.get(
        "/path", params={"from": LAW, "to": RECIPIENT_ORG, "max_depth": PATH_MAX_MAX_DEPTH + 1}
    )
    assert r.status_code == 422, r.text


def test_every_path_edge_graph_key_exists_in_the_graphs_map(client):
    body = client.get("/path", params={"from": LAW, "to": RECIPIENT_ORG}).json()
    keys = [e["graph"] for e in body["edges"]]
    assert keys, "経路の辺が0本(前提が崩れている)"
    missing = sorted({k for k in keys if k not in body["graphs"]})
    assert not missing, f"graphsに存在しないキーが辺から参照されている: {missing}"


def test_path_through_a_percent_encoded_node_composes_with_entity_detail(client):
    """**`%`を含むノードを経路に含め、そのノードから詳細に遷移できること**
    (裁定B69と同じ合成ゲートをパス探索にも適用する。観察O14)。

    厚生省(`AbolishedGovernmentOrgan`。IRIがpercent-encodeされている)は
    `succeededBy`で厚生労働省に繋がっている。
    """
    body = client.get("/path", params={"from": ABOLISHED, "to": MINISTRY}).json()
    assert body["found"] is True, body
    percent_nodes = [n for n in body["nodes"] if "%" in n["id_path"]]
    assert percent_nodes, f"経路に%を含むノードが無い: {[n['id_path'] for n in body['nodes']]}"
    for node in percent_nodes:
        r = client.get(f"/entity/{node['id_path']}")
        assert r.status_code == 200, f"{node['id_path']!r} -> {r.status_code}"
        assert r.json()["id"] == node["id"], (
            f"経路のノードのidと詳細が返すidが食い違う: {node['id']!r} vs {r.json()['id']!r}"
        )


def test_path_accepts_a_percent_encoded_id_in_either_form(client, kg):
    """**クエリパラメータとパスセグメントで、ハンドラに届く形が違う。**

    controllerの実測(2026-08-30):

    | 送り方 | ハンドラが受け取る |
    |---|---|
    | パスに生のまま補間 | デコード済み(日本語) |
    | パスに正しくエンコード | **同じ**(パスは二重にデコードされる) |
    | クエリを`params=`で渡す | **正準形のまま**(`%E4%BB%A4...`) |
    | クエリをURLに直接埋める | デコード済み |

    `canonical_iri`は「デコードされた形」を受け取って再エンコードする設計
    なので、**正準形のまま届くクエリ経由では二重エンコードになり一致しない**
    ——実際に`%`を含むノードで404になった(裁定B59・B69と同じ族が3層目)。
    `/path`のルートで`unquote`を1回かけて正規化したことを、ここで固定する。

    **3通りの送り方すべてで同じIRIに収束すること。**
    片方だけ通る状態に戻ったらここが落ちる。
    """
    from urllib.parse import unquote

    id_path = _edgeless_percent_node_id_path(kg)
    assert "%" in id_path, "検査対象が%を含まない(このテストの前提)"

    # (1) 正しいクライアント: httpxが`%`を`%25`にエンコードする
    by_params = client.get("/path", params={"from": id_path, "to": RECIPIENT_ORG, "max_depth": 2})
    assert by_params.status_code == 200, f"params=経由が404: {by_params.text}"

    # (2) URLに直接埋める(`%`がそのまま飛ぶ)
    by_url = client.get(f"/path?from={id_path}&to={RECIPIENT_ORG}&max_depth=2")
    assert by_url.status_code == 200, f"URL直接埋め込みが404: {by_url.text}"

    # (3) デコード済みの形を渡す(日本語のまま)
    by_decoded = client.get(
        "/path", params={"from": unquote(id_path), "to": RECIPIENT_ORG, "max_depth": 2}
    )
    assert by_decoded.status_code == 200, f"デコード形が404: {by_decoded.text}"

    starts = {r.json()["start"]["id"] for r in (by_params, by_url, by_decoded)}
    assert len(starts) == 1, f"送り方によってstartのidが違う(同じIRIに収束していない): {starts}"
    assert "%" in next(iter(starts)), f"startのidが正準形(エンコード済み)になっていない: {starts}"


# =============================================================================
# 不変条件: すべての辺の端点が nodes にある(ダングリングエッジを許さない)
# =============================================================================


@pytest.mark.parametrize(
    ("depth", "node_limit", "edge_limit", "fanout_limit"),
    [
        (1, 100, 200, 25),  # どの上限も効かない
        (1, 2, 200, 25),  # **ノード数の上限が効く**(ダングリングエッジが出ていた組)
        (1, 200, 2, 25),  # エッジ数の上限が効く
        (1, 200, 200, 2),  # 分岐数の上限が効く
        (2, 3, 200, 25),  # 深さ2でノード数の上限が効く
        (2, 200, 3, 25),  # 深さ2でエッジ数の上限が効く
        (2, 4, 5, 2),  # 3つ全部が効く
    ],
)
def test_neighborhood_edges_never_dangle(client, depth, node_limit, edge_limit, fanout_limit):
    """**応答のすべての辺の source と target が nodes にあること。**

    **これはタスクレビューが実証した欠陥である。** `node_limit` に達したとき、
    以前の実装は辺を確定した**後**に相手ノードの上限を判定していたため、
    **`nodes` に無いノードを指す辺が残った**(ハブが6辺・node_limit=2 で
    6辺中5辺がダングリング)。

    **`nodes_truncated` は正直に真を返していた** —— 打ち切りの報告は正しいのに
    **返したグラフ自体が壊れていた。** 既存の上限のテストは
    `len(nodes) <= 2` とフラグしか見ておらず、この不整合を検出しなかった
    (「アサーションは正しいが不完全」——観察O14と同じ族)。

    **上限の組み合わせを掃く**のは、1つの組み合わせだけを見て
    「不変条件が成り立つ」と結論しないため(裁定B55の「1回で結論しない」の
    構造版)。
    """
    r = client.get(
        f"/neighborhood/{HUB_PROJECT}",
        params={
            "depth": depth,
            "node_limit": node_limit,
            "edge_limit": edge_limit,
            "fanout_limit": fanout_limit,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    node_ids = {n["id"] for n in body["nodes"]}
    dangling = [
        e for e in body["edges"] if e["source"] not in node_ids or e["target"] not in node_ids
    ]
    assert not dangling, (
        f"nodes に無いノードを指す辺がある(depth={depth} node_limit={node_limit} "
        f"edge_limit={edge_limit} fanout_limit={fanout_limit}): "
        f"{[(e['source'], e['predicate'], e['target']) for e in dangling[:3]]}"
    )
    # 上限の範囲内であること(切ったなら上限以下)
    assert len(body["nodes"]) <= node_limit
    assert len(body["edges"]) <= edge_limit


def test_neighborhood_dangling_edge_check_is_not_vacuous(client):
    """上のパラメトリックな検査が**実際に辺を検査している**ことを固定する。

    すべての組み合わせで `edges` が空なら、上のテストは何も検査していない
    (このプロジェクトの再発欠陥2: 空虚なテスト)。
    """
    counts = []
    for node_limit, edge_limit, fanout_limit in [(100, 200, 25), (2, 200, 25), (200, 2, 25)]:
        body = client.get(
            f"/neighborhood/{HUB_PROJECT}",
            params={
                "depth": 1,
                "node_limit": node_limit,
                "edge_limit": edge_limit,
                "fanout_limit": fanout_limit,
            },
        ).json()
        counts.append(len(body["edges"]))
    assert all(c > 0 for c in counts), (
        f"辺が0本の組み合わせがある —— 上の不変条件の検査が空虚になる: {counts}"
    )


def test_neighborhood_marks_a_graph_whose_provenance_is_missing(kg):
    """**出典が引けないグラフを`available=False`で明示すること。**

    近傍サブグラフの1ホップ展開は、探索を軽くするため出典を**必須で結合しない**
    (必須にすると`prov:wasDerivedFrom`等を持たないグラフの辺が黙って消え、
    連結性が壊れる)。そのため出典が引けないグラフがありうる。

    **タスクレビューの指摘**: この分岐は当初テストで一度も踏まれておらず、
    「実データに一度も当てていない層は緑でも未検証」(再発欠陥9)だった。
    しかも空文字列だけを返す実装は**「出典が無い」ことを黙って隠して**おり、
    仕様§9.2「全表示要素に一次資料へのリンクと取得日時を出す」に対して
    UIが空のリンクを描くことになる。

    **壊し確認の形で書く**: provenanceグラフから対象グラフの記述を実際に外し、
    (a) 辺が消えないこと (b) `available=False` が立つこと の両方を見る。
    """
    from rdflib import URIRef

    from jgkg.api.kgclient import RdflibKGClient

    base_ok = TestClient(create_app(client=RdflibKGClient(kg), base_uri=BASE))
    before = base_ok.get(f"/neighborhood/{HUB_PROJECT}", params={"depth": 1}).json()
    assert before["edges"], "壊す前から辺が無い(前提が崩れている)"
    assert all(p["available"] for p in before["graphs"].values()), (
        f"壊す前から available=False のグラフがある: {before['graphs']}"
    )
    target_graph = before["edges"][0]["graph"]

    # provenanceグラフから、その名前付きグラフについての記述を全て外す
    prov_graph = kg.graph(URIRef(f"{BASE}/graph/provenance"))
    removed = list(prov_graph.triples((URIRef(target_graph), None, None)))
    assert removed, f"除去対象のprovenanceトリプルが見つからない: {target_graph}"
    for triple in removed:
        prov_graph.remove(triple)

    after = TestClient(create_app(client=RdflibKGClient(kg), base_uri=BASE)).get(
        f"/neighborhood/{HUB_PROJECT}", params={"depth": 1}
    ).json()

    # (a) 辺は消えない —— 探索は出典を必須にしていない
    assert after["edges"], "出典を外したら辺が消えた(連結性の探索が壊れている)"
    keys = {e["graph"] for e in after["edges"]}
    assert target_graph in keys, "対象グラフの辺が消えた"

    # (b) 引けなかったことが応答に現れる
    prov = after["graphs"][target_graph]
    assert prov["available"] is False, (
        f"出典が引けないのに available=True のまま(黙って隠している): {prov}"
    )
    assert prov["source"] == ""
    assert prov["graph"] == target_graph, "キーだけ落として消費者に不在を扱わせていない"
