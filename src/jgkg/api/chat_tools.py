"""チャット(E-2)がLLMに渡す5つの道具の定義と実体(裁定B92裁定1)。

**この5つに限る。生のSPARQLは渡さない。** `search_entities`/`get_entity`/
`get_neighborhood`/`find_path`は`queries.py`の既存関数を**そのまま**呼ぶ
(HTTPを自分で叩き直さない)。`get_ontology`だけがこのタスクの新規道具で、
`schema/generated/{module}.owl.ttl`をそのまま返す(`/def/*`へ外部HTTPで
取りに行かない——同じ内容がリポジトリ内にあり、コンテナにも焼かれている)。

**モジュール名は`site.module_names()`から導出する(手で列挙しない)。**
`tests/test_api_chat.py`の壊し確認がこれを固定する。

**id_path/from_id/to_idは呼び出し前に`unquote`で1回正規化する。**
これらの値はLLMが前の道具応答(`EntityRef.id_path`。既にパーセントエンコード
済み)から受け取ったものであり、`app.py`の`/path`ルートが`from`/`to`という
クエリパラメータに対して行っている正規化(`unquote`を1回かけてパス
パラメータ経由と同じ「デコード済み」の形にする)と**同じ理由**で必要になる
——ここは`/entity/{id:path}`・`/neighborhood/{id:path}`のような
Starlette自身のパス変換を経由せず、`queries.py`の関数を直接呼ぶため、
その1回のデコードをこちらで代わりに行う。やらないと`%`を含むid_path
(`LawRevision`・`UnresolvedReference`・`AbolishedGovernmentOrgan`)が
二重エンコードされ、実在するエンティティが0件として返る
(裁定B59・B69と同じ族。kgclient.pyの`canonical_iri`/`sparql_iri_for_canonical_uri`
のdocstring参照)。
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from jgkg.api.kgclient import KGClient
from jgkg.api.models import EntityRef, Provenance
from jgkg.api.queries import (
    ENTITY_RELATIONSHIPS_DEFAULT_LIMIT,
    NEIGHBORHOOD_DEFAULT_EDGE_LIMIT,
    NEIGHBORHOOD_DEFAULT_FANOUT_LIMIT,
    NEIGHBORHOOD_DEFAULT_NODE_LIMIT,
    NEIGHBORHOOD_MAX_DEPTH,
    PATH_DEFAULT_FANOUT_LIMIT,
    PATH_DEFAULT_MAX_DEPTH,
    PATH_DEFAULT_VISIT_BUDGET,
    SEARCH_MAX_LIMIT,
    find_path,
    get_entity_detail,
    get_neighborhood,
    search_entities,
)
from jgkg.site import module_names

TOOL_NAMES = (
    "search_entities",
    "get_entity",
    "get_neighborhood",
    "find_path",
    "get_ontology",
)


def build_tool_schemas(generated_dir: Path) -> list[dict[str, object]]:
    """Chat Completionsの`tools`パラメータに渡すJSON Schema定義。

    **`get_ontology`の`module`の`enum`を`site.module_names()`から作る。**
    手書きの一覧(`["core","org","law","budget","all"]`等)にすると、
    モジュールが増減しても追随しない——このプロジェクトの再発欠陥1
    (導出すべき値の手書き)そのものになる。
    """
    modules = module_names(generated_dir)
    return [
        {
            "type": "function",
            "function": {
                "name": "search_entities",
                "description": (
                    "KG内の法令・府省・法人・予算事業をラベルの部分一致で検索する。"
                    "まず何を調べればよいか分からないときの入口。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "description": "検索語(部分一致・大文字小文字を無視)"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": SEARCH_MAX_LIMIT,
                            "description": f"返す件数の上限(既定20・最大{SEARCH_MAX_LIMIT})",
                        },
                    },
                    "required": ["q"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_entity",
                "description": (
                    "1つのエンティティの属性・関係(相手の型別)・出典を取得する。"
                    "id_pathは検索結果や他の道具の応答が返す`id_path`をそのまま渡す。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id_path": {"type": "string", "description": "エンティティの経路形ID"},
                    },
                    "required": ["id_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_neighborhood",
                "description": (
                    "1つのエンティティを中心とした近傍サブグラフ(ノード・辺)を取得する。"
                    "つながりの形(誰が/何を/どこで等)を見るときに使う。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id_path": {"type": "string", "description": "中心にするエンティティの経路形ID"},
                        "depth": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": NEIGHBORHOOD_MAX_DEPTH,
                            "description": f"深さ(1または{NEIGHBORHOOD_MAX_DEPTH})",
                        },
                    },
                    "required": ["id_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_path",
                "description": (
                    "2つのエンティティの間の経路(法令↔法人など)を探す。"
                    "見つからなくても`exhaustive`が真でない限り「無い」ことは意味しない。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_id": {"type": "string", "description": "始点の経路形ID"},
                        "to_id": {"type": "string", "description": "終点の経路形ID"},
                    },
                    "required": ["from_id", "to_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_ontology",
                "description": (
                    "オントロジー(語彙)そのもの——クラス・プロパティの定義・"
                    "説明文(skos:definition等)——をTurtleで取得する。"
                    "エンティティの実データではなく、KGの設計・語彙の意味を"
                    "確認したいときに使う。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "module": {
                            "type": "string",
                            "enum": modules,
                            "description": "取得するモジュール名",
                        },
                    },
                    "required": ["module"],
                },
            },
        },
    ]


@dataclass
class ToolInvocationResult:
    """道具1回の呼び出し結果。`result_count`は呼び出し履歴(監査)にそのまま出す。"""

    result_count: int
    #: モデルに`role="tool"`として返す本文(JSON文字列、または`get_ontology`の生Turtle)。
    content: str


@dataclass
class _CollectedSource:
    ref: EntityRef
    graph_keys: set[str] = field(default_factory=set)


class SourceCollector:
    """道具の応答から「実際に使われたエンティティと出典」を機械的に集める。

    **LLMに聞かない。** 出典はこのプロジェクトの核(裁定B92裁定2)——
    「道具が0件を返したのに答えに出典が付く」ことが構造的に起こらないよう、
    出典の集合は道具の戻り値そのものから作る(LLMの発言や自己申告からは作らない)。
    """

    def __init__(self, base_uri: str) -> None:
        self._sources: dict[str, _CollectedSource] = {}
        self._graphs: dict[str, Provenance] = {}
        self._ontology_modules: set[str] = set()
        # 語彙モジュールの引用URLを組み立てるためのベースURI(裁定B94)。
        # **文字列を直書きしない** —— `jgkg.base_uri --check` が
        # 実際のベースURIとのずれを検出する対象に入っている
        self._base_uri = base_uri.rstrip("/")

    def add_ref(self, ref: EntityRef, graph_keys: Iterable[str] = ()) -> None:
        entry = self._sources.get(ref.id)
        if entry is None:
            entry = _CollectedSource(ref=ref)
            self._sources[ref.id] = entry
        entry.graph_keys.update(g for g in graph_keys if g)

    def add_graph_key(self, entity_id: str, graph_key: str) -> None:
        if not graph_key:
            return
        entry = self._sources.get(entity_id)
        if entry is not None:
            entry.graph_keys.add(graph_key)

    def add_graphs(self, graphs: dict[str, Provenance]) -> None:
        self._graphs.update(graphs)

    def add_ontology_module(self, module: str) -> None:
        """**語彙モジュールを読んだことを記録する(裁定B94)。**

        `get_ontology` だけで答えた回に `sources` が空になり、画面上
        「出典なし」に見えていた——**しかし `/def/{module}` は恒久的で
        参照可能な公開URI**(裁定B81)であり、**語彙から答えたなら
        語彙を引用できる。**

        **`ChatSource`(政府データ)と混ぜない。** あちらは一次資料URL・
        取得日・ライセンス(PDL1.0)を持つが、こちらは**我々自身が公開した
        語彙定義**で、それらを持たない。混ぜると
        「政府が出した情報」と「我々の語彙」の区別が消える。
        """
        self._ontology_modules.add(module)

    def finalize(
        self,
    ) -> tuple[list[dict[str, object]], dict[str, Provenance], list[dict[str, object]]]:
        sources = [
            {
                "id": c.ref.id,
                "id_path": c.ref.id_path,
                "type": c.ref.type,
                "label": c.ref.label,
                "graphs": sorted(c.graph_keys),
            }
            for c in self._sources.values()
        ]
        used_graph_keys = {g for c in self._sources.values() for g in c.graph_keys}
        graphs = {k: v for k, v in self._graphs.items() if k in used_graph_keys}
        # **語彙モジュールは別立てで返す(裁定B94)。** `sources` に混ぜない理由は
        # `add_ontology_module` のdocstring参照(政府データの出典とは種類が違う)。
        # **タイトルは持たせない。** 毎リクエストでTurtleを解析するのは無駄で、
        # 対応表を手書きするのは再発欠陥1(導出すべき値の手書き)になる。
        # `module` と**参照可能なURL**で引用は完結する(`/def/budget` を開けば
        # そこに語彙の定義とタイトルがある。裁定B81・B84で本番確認済み)。
        ontology_sources = [
            {"module": m, "url": f"{self._base_uri}/def/{m}"}
            for m in sorted(self._ontology_modules)
        ]
        return sources, graphs, ontology_sources


def run_tool(
    name: str,
    arguments: dict[str, object],
    *,
    kg_client: KGClient,
    base_uri: str,
    generated_dir: Path,
    collector: SourceCollector,
    neighborhood_node_limit: int = NEIGHBORHOOD_DEFAULT_NODE_LIMIT,
) -> ToolInvocationResult:
    """道具を1回実行する。未知の道具名・不正な引数はValueErrorにする
    (呼び出し側`chat.py`がこれを捉えて「壊れた呼び出し」として履歴に残す)。
    """
    if name == "search_entities":
        return _run_search_entities(arguments, kg_client, base_uri, collector)
    if name == "get_entity":
        return _run_get_entity(arguments, kg_client, base_uri, collector)
    if name == "get_neighborhood":
        return _run_get_neighborhood(
            arguments, kg_client, base_uri, collector, neighborhood_node_limit
        )
    if name == "find_path":
        return _run_find_path(arguments, kg_client, base_uri, collector)
    if name == "get_ontology":
        return _run_get_ontology(arguments, generated_dir, collector)
    raise ValueError(f"未知の道具: {name!r}")


def _error_result(message: str) -> ToolInvocationResult:
    return ToolInvocationResult(result_count=0, content=json.dumps({"error": message}, ensure_ascii=False))


def _run_search_entities(
    arguments: dict[str, object], kg_client: KGClient, base_uri: str, collector: SourceCollector
) -> ToolInvocationResult:
    q = arguments.get("q")
    if not isinstance(q, str) or not q:
        return _error_result("qは空でない文字列が必要")
    limit = arguments.get("limit", 20)
    if not isinstance(limit, int) or not (1 <= limit <= SEARCH_MAX_LIMIT):
        return _error_result(f"limitは1から{SEARCH_MAX_LIMIT}までの整数が必要(渡された値: {limit!r})")

    result = search_entities(kg_client, base_uri, q, limit)
    for hit in result.results:
        # 検索は出典(名前付きグラフ)を返さない(queries.pyのSearchHit参照)。
        # graph_keysを渡さない=出典なしとして扱う(捏造しない)
        collector.add_ref(hit)
    return ToolInvocationResult(
        result_count=len(result.results), content=result.model_dump_json()
    )


def _run_get_entity(
    arguments: dict[str, object], kg_client: KGClient, base_uri: str, collector: SourceCollector
) -> ToolInvocationResult:
    id_path = arguments.get("id_path")
    if not isinstance(id_path, str) or not id_path:
        return _error_result("id_pathは空でない文字列が必要")

    result = get_entity_detail(kg_client, base_uri, unquote(id_path), ENTITY_RELATIONSHIPS_DEFAULT_LIMIT)
    if result is None:
        return ToolInvocationResult(result_count=0, content=json.dumps({"found": False}))

    own_graph_keys = {
        g for values in result.attributes.values() for av in values for g in av.graphs
    }
    own_ref = EntityRef(id=result.id, id_path=result.id_path, type=result.type, label=result.label)
    collector.add_ref(own_ref, own_graph_keys)
    for rels in result.relationships.values():
        for rel in rels:
            collector.add_ref(rel.related, {rel.graph} if rel.graph else ())
            collector.add_graph_key(result.id, rel.graph)
    collector.add_graphs(result.graphs)
    return ToolInvocationResult(result_count=1, content=result.model_dump_json())


def _run_get_neighborhood(
    arguments: dict[str, object],
    kg_client: KGClient,
    base_uri: str,
    collector: SourceCollector,
    node_limit: int = NEIGHBORHOOD_DEFAULT_NODE_LIMIT,
) -> ToolInvocationResult:
    id_path = arguments.get("id_path")
    if not isinstance(id_path, str) or not id_path:
        return _error_result("id_pathは空でない文字列が必要")
    depth = arguments.get("depth", 1)
    if not isinstance(depth, int) or not (1 <= depth <= NEIGHBORHOOD_MAX_DEPTH):
        return _error_result(f"depthは1から{NEIGHBORHOOD_MAX_DEPTH}までの整数が必要(渡された値: {depth!r})")

    result = get_neighborhood(
        kg_client,
        base_uri,
        unquote(id_path),
        depth,
        # **画面より小さい上限をLLMに使う(裁定B94)。**
        # トークン消費の主要因は呼び出し回数ではなく1回の情報量である。
        # 打ち切りは応答のフラグに現れるのでLLMは正しく「打ち切られた」と言える
        node_limit,
        NEIGHBORHOOD_DEFAULT_EDGE_LIMIT,
        NEIGHBORHOOD_DEFAULT_FANOUT_LIMIT,
    )
    if result is None:
        return ToolInvocationResult(result_count=0, content=json.dumps({"found": False}))

    for node in result.nodes:
        collector.add_ref(node)
    for edge in result.edges:
        collector.add_graph_key(edge.source, edge.graph)
        collector.add_graph_key(edge.target, edge.graph)
    collector.add_graphs(result.graphs)
    return ToolInvocationResult(result_count=len(result.nodes), content=result.model_dump_json())


def _run_find_path(
    arguments: dict[str, object], kg_client: KGClient, base_uri: str, collector: SourceCollector
) -> ToolInvocationResult:
    from_id = arguments.get("from_id")
    to_id = arguments.get("to_id")
    if not isinstance(from_id, str) or not from_id or not isinstance(to_id, str) or not to_id:
        return _error_result("from_id/to_idはいずれも空でない文字列が必要")

    result = find_path(
        kg_client,
        base_uri,
        unquote(from_id),
        unquote(to_id),
        PATH_DEFAULT_MAX_DEPTH,
        PATH_DEFAULT_VISIT_BUDGET,
        PATH_DEFAULT_FANOUT_LIMIT,
    )
    if result is None:
        return ToolInvocationResult(result_count=0, content=json.dumps({"found": False}))

    for node in result.nodes:
        collector.add_ref(node)
    for edge in result.edges:
        collector.add_graph_key(edge.source, edge.graph)
        collector.add_graph_key(edge.target, edge.graph)
    collector.add_graphs(result.graphs)
    # **`found=False`でも0件にしない。** 探索そのものは成功しており
    # (`nodes`は空でも`visited`等の診断情報がある)、「見つからなかった」を
    # 「呼び出しが壊れた」と混同させないため、経路のノード数を件数にする
    return ToolInvocationResult(result_count=len(result.nodes), content=result.model_dump_json())


def _run_get_ontology(
    arguments: dict[str, object], generated_dir: Path, collector: SourceCollector
) -> ToolInvocationResult:
    module = arguments.get("module")
    if not isinstance(module, str) or not module:
        return _error_result("moduleは空でない文字列が必要")
    valid_modules = module_names(generated_dir)
    if module not in valid_modules:
        return _error_result(f"未知のモジュール: {module!r}(有効な値: {valid_modules})")

    path = generated_dir / f"{module}.owl.ttl"
    text = path.read_text(encoding="utf-8")
    # **読んだ語彙は引用できる(裁定B94)。** 出典の集合は道具の戻り値から
    # 機械的に作る——ここも同じ規律で、LLMの自己申告には依存しない
    collector.add_ontology_module(module)
    return ToolInvocationResult(result_count=1, content=text)
