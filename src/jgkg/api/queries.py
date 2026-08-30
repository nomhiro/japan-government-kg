"""検索・エンティティ詳細それぞれのSPARQLクエリ組み立てと、結果の解釈。

ルート(`app.py`)はここの`search_entities()`/`get_entity_detail()`しか呼ばない
——HTTP層とSPARQL/ドメインロジックを分けるため。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from jgkg.api.kgclient import (
    KGClient,
    Row,
    canonical_iri,
    sparql_iri,
    sparql_iri_for_canonical_uri,
    sparql_string_literal,
)
from jgkg.api.models import (
    EntityDetailResponse,
    EntityRef,
    GraphEdge,
    NeighborhoodResponse,
    PathResponse,
    Provenance,
    Relationship,
    SearchHit,
    SearchResponse,
)

# =============================================================================
# 上限(D-3ブリーフ「件数上限を必ず持つ」。仕様§9.1のhairball防止 +
# 決定#33のegressコスト対策——両方がここに効く)
# =============================================================================

#: 検索結果の既定・最大件数。検索ボックスの1画面に出す量として20を既定に、
#: 100を上限にした(仕様§9.2「検索ボックス起点」のUXで、それ以上は
#: 検索語を絞るべきという判断)。
SEARCH_DEFAULT_LIMIT = 20
SEARCH_MAX_LIMIT = 100

#: エンティティ詳細の関係一覧の既定・最大件数。検索結果より多めにしたのは、
#: 「この事業の支出一覧」のような1対多の関係パネルが検索候補一覧より
#: 広い面積で表示される想定(仕様§9.2「エンティティページ(型別レイアウト)」)
#: のため。それでも無制限にはしない(1つのBudgetProjectが数万件のExpenditure
#: を持つ実データがある——D-2実測の73,919件がまさにこの規模)。
ENTITY_RELATIONSHIPS_DEFAULT_LIMIT = 50
ENTITY_RELATIONSHIPS_MAX_LIMIT = 200

#: **上限を超えるlimitを渡されたら拒否する(黙って丸めない)。**
#: FastAPI側で`Query(ge=1, le=MAX)`を使うと、超過リクエストはこの関数まで
#: 到達せず422になる——「既定は止まる側」(設計書§6.3の作法)をAPIの
#: 入力検証にもそのまま適用した。黙って丸める実装は、利用者が「最大件数を
#: 要求したのに実は少なかった」ことに気づけないまま結果を全件だと
#: 誤解しうる——このプロジェクトが繰り返し扱う「報告が嘘をつく」欠陥型
#: (文書/応答が実態と異なる主張をし、訂正が読者に届かない)の入力側の鏡像
#: だと判断した。

# =============================================================================
# 検索対象の型(D-3ブリーフの例=法令/法人/事業をそのまま採用)
# =============================================================================

#: **ExpenditureとUnresolvedReferenceは意図的に除外する。**
#: - Expenditureは`skos:prefLabel`を持つ(支出先の表示名。emit.py参照)ため
#:   技術的には検索に混ぜられるが、73,919件あり固有の「名前を持つ物」では
#:   なく事業に紐づく事実(1明細)である。法人名で検索すると際限なく一致し、
#:   検索結果自体がhairball化する(仕様§9.1・決定#33のegressコスト対策と
#:   同じ理由をここでも適用した)
#: - UnresolvedReferenceは`skos:prefLabel`を持たないため、そもそも一致しない
#:   (emit.py確認済み)
_SEARCHABLE_TYPES: tuple[str, ...] = (
    "org:Organization",
    "org:GovernmentOrgan",
    "org:Ministry",
    "org:AbolishedGovernmentOrgan",
    "law:Law",
    "budget:BudgetProject",
)

#: 型の特定さの順位(先頭ほど具体的)。**なぜ必要か**: 名前付きグラフの
#: 和集合(union default graph)では、同じ実体が複数ソースから別々の
#: rdf:typeで記述されることがある——D-3設計時にfixtureで実測: 厚生労働省の
#: URI(`org_uri(houjinBangou)`)が houjin-bangou 由来の`org:GovernmentOrgan`と
#: ministry-codes 由来の`org:Ministry`を**両方**持っていた
#: (`emit.py`の「型は最も具体的なもの1つだけを出す」は1回のemit呼び出し
#: 内で言っているのであり、複数ソースを合わせた結果には及ばない)。
#: 検索結果・エンティティ詳細のtypeフィールドが1エンティティにつき1つの
#: 値であることを保証するため、複数のrdf:typeが観測されたらこの順位で
#: 1つに絞る(値を捨てるわけではなく、「どれを代表として見せるか」を決める)。
_TYPE_SPECIFICITY: tuple[str, ...] = (
    "AbolishedGovernmentOrgan",
    "Ministry",
    "GovernmentOrgan",
    "Organization",
    "LawRevision",
    "Law",
    "Expenditure",
    "BudgetProject",
    "UnresolvedReference",
)


def _local_name(uri: str) -> str:
    """完全なURIから短い型名/述語名を取り出す(例: `{base}/def/org#Ministry` → "Ministry")。

    APIの消費者には完全なURIより短い名前の方が扱いやすく、完全な語彙は
    `/def/`でいつでも辿れる(そちらが正——設計書§5.7「オントロジー自体を
    公開成果物として扱う」)。
    """
    for sep in ("#", "/"):
        if sep in uri:
            candidate = uri.rsplit(sep, 1)[-1]
            if candidate:
                return candidate
    return uri


def _most_specific_type(local_names: Iterable[str]) -> str:
    names = list(dict.fromkeys(local_names))  # 順序を保ちつつ重複を除く
    if not names:
        return "unknown"
    return min(
        names,
        key=lambda n: (
            _TYPE_SPECIFICITY.index(n) if n in _TYPE_SPECIFICITY else len(_TYPE_SPECIFICITY)
        ),
    )


def _prefixes(base_uri: str) -> str:
    """`emit.py`の`_ns()`と同じ方式(ベースURIを直書きしない。設定から組み立てる)。"""
    return (
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
        "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n"
        "PREFIX prov: <http://www.w3.org/ns/prov#>\n"
        "PREFIX dcterms: <http://purl.org/dc/terms/>\n"
        f"PREFIX core: <{base_uri}/def/core#>\n"
        f"PREFIX org: <{base_uri}/def/org#>\n"
        f"PREFIX law: <{base_uri}/def/law#>\n"
        f"PREFIX budget: <{base_uri}/def/budget#>\n"
    )


def _value(row: Row, key: str) -> str | None:
    term = row.get(key)
    return term.value if term is not None else None


def _id_path(base_uri: str, iri: str) -> str:
    """完全IRIから`id_path`(`/entity/{id_path}`が受け取る経路形)を導出する。

    `get_entity_detail`が組み立てる`entity_uri`(`kgclient.canonical_iri`
    参照)の逆演算。**この関数1本だけを、`id`を組み立てる3つの構築箇所
    (`SearchHit`・関係の相手側の`EntityRef`・`EntityDetailResponse`)全てから
    呼ぶ**(裁定B59)。箇所ごとに剥がし処理を手書きすると、このプロジェクトの
    再発欠陥1(導出すべき値を手書きしている)そのものになる。

    **この関数が防ぐのは「同じ`id`に対して箇所ごとに違う剥がし処理を書く」
    ことだけである(訂正。裁定B69)。** 以前のこの節は「id_pathが食い違う
    経路を構造的に塞ぐ」と書いていたが、これは偽だった——`id`を組み立てる
    側(`entity_uri`)自体が誤っていれば、この関数はその誤りを検出も訂正も
    せず、誤った`id`から一貫して誤った`id_path`を導出するだけである。
    実際に裁定B69では、`get_entity_detail`が応答の`id`を素の文字列結合
    (`f"{base_uri}/id/{id_path}"`)で組み立てていたため、`%`を含む
    id_pathでは`id`自体がKGに存在しないIRIになり、この関数はそれをそのまま
    剥がしていた——`id`が`canonical_iri`(`kgclient.py`)を通って正しく
    組み立てられるようになった今、この関数は入力される`id`が正しくなった
    ぶんだけ、自動的に正しい`id_path`を導出する。**この関数自体は
    裁定B69で何も変えていない**——直したのは`id`を組み立てる側である。

    このKGの全エンティティは`uris.py`(`org_uri`・`law_uri`・`budget_uri`等)が
    `{base_uri}/id/...`の形でしか生成しない。この前提が崩れるIRI(ベースURI
    配下の`/id/`を持たない)が来るのはデータ不整合であり、黙って見かけの値
    (例: フルIRIそのもの)を返すよりも、ここで例外にして大きく失敗させる方が
    安全側の選択である(このプロジェクトが繰り返し扱う「報告が嘘をつく」
    欠陥型の入力側の鏡像——上の上限コメント参照)。
    """
    prefix = f"{base_uri}/id/"
    if not iri.startswith(prefix):
        raise ValueError(f"ベースURI配下の/id/を持たないIRIからid_pathを導出できない: {iri!r}")
    return iri[len(prefix) :]


# =============================================================================
# 検索
# =============================================================================


def _build_search_query(base_uri: str, q: str, fetch_limit: int) -> str:
    values = " ".join(_SEARCHABLE_TYPES)
    return _prefixes(base_uri) + f"""
SELECT ?entity ?type ?label ?lawNum ?prefectureName ?cityName ?fiscalYear ?ministryName WHERE {{
  VALUES ?type {{ {values} }}
  ?entity a ?type ; skos:prefLabel ?label .
  FILTER(CONTAINS(LCASE(STR(?label)), LCASE({sparql_string_literal(q)})))
  OPTIONAL {{ ?entity law:lawNum ?lawNum }}
  OPTIONAL {{ ?entity org:prefectureName ?prefectureName }}
  OPTIONAL {{ ?entity org:cityName ?cityName }}
  OPTIONAL {{ ?entity budget:fiscalYear ?fiscalYear }}
  OPTIONAL {{ ?entity budget:ministry/skos:prefLabel ?ministryName }}
}}
ORDER BY ?label ?entity
LIMIT {fetch_limit}
"""


def _derive_summary(
    type_local: str,
    law_num: str | None,
    prefecture_name: str | None,
    city_name: str | None,
    fiscal_year: str | None,
    ministry_name: str | None,
) -> str | None:
    """型ごとの要約の判断根拠。

    D-3ブリーフが例として挙げた3種をそのまま採用する
    (「法令なら法令番号、法人なら所在地、事業なら年度と府省」)。
    **理由**: いずれも各型が実データとして既に持つフィールド
    (`schema/law.yaml`のlawNum・`schema/org.yaml`のprefectureName/cityName・
    `schema/budget.yaml`のfiscalYear/ministry)からそのまま組み立てられる
    ——これらとは別に「要約」専用の文字列をどこかで新たに手書きすると
    「導出すべき値を手書きしている」(このプロジェクトの再発欠陥1)になる。
    """
    if type_local == "Law":
        return law_num
    if type_local in ("Organization", "GovernmentOrgan", "Ministry", "AbolishedGovernmentOrgan"):
        parts = [p for p in (prefecture_name, city_name) if p]
        return "".join(parts) if parts else None
    if type_local == "BudgetProject":
        if fiscal_year and ministry_name:
            return f"{fiscal_year}年度・{ministry_name}"
        if fiscal_year:
            return f"{fiscal_year}年度"
        return ministry_name
    return None


@dataclass
class _SearchAccumulator:
    label: str | None = None
    types: list[str] = field(default_factory=list)
    law_num: str | None = None
    prefecture_name: str | None = None
    city_name: str | None = None
    fiscal_year: str | None = None
    ministry_name: str | None = None


def search_entities(client: KGClient, base_uri: str, q: str, limit: int) -> SearchResponse:
    """検索エンドポイントの本体。ルート(app.py)はこれを呼ぶだけにする。

    **`fetch_limit`を`limit`より大きく取る理由**: 同じentityが複数の型
    (`_TYPE_SPECIFICITY`参照)で重複してヒットすることがあるため、
    要求されたlimit件分の**異なる**entityを確実に確保するための安全域。
    実測では厚生労働省のような政府機関で最大2つの型が重複する
    (GovernmentOrgan/Ministry)ため2倍を安全域とした。**既知の限界**:
    これを超える重複(1entityが3つ以上の型で重複)が起きた場合、
    truncatedの判定を見誤る可能性がある(気になる点に記載)。

    **規模の限界(記録のみ。直さない——今回の範囲外)**: `_build_search_query`
    は`ORDER BY ?label ?entity`を持つため、LIMITの前に`_SEARCHABLE_TYPES`
    全体の`skos:prefLabel`を全走査する(裁定B60。`warmup.py`が温める領域も
    ここから導出する理由)。全文索引(Jena text/Lucene)を持たない現状の設計
    では、この1リクエストあたりの走査コストはKGの規模に対して線形に増える。
    """
    fetch_limit = 2 * (limit + 1)
    rows = client.query(_build_search_query(base_uri, q, fetch_limit))

    order: list[str] = []
    acc: dict[str, _SearchAccumulator] = {}
    for row in rows:
        entity = row["entity"].value  # type: ignore[union-attr]
        type_local = _local_name(row["type"].value)  # type: ignore[union-attr]
        if entity not in acc:
            order.append(entity)
            acc[entity] = _SearchAccumulator(label=_value(row, "label"))
        a = acc[entity]
        a.types.append(type_local)
        a.law_num = a.law_num or _value(row, "lawNum")
        a.prefecture_name = a.prefecture_name or _value(row, "prefectureName")
        a.city_name = a.city_name or _value(row, "cityName")
        a.fiscal_year = a.fiscal_year or _value(row, "fiscalYear")
        a.ministry_name = a.ministry_name or _value(row, "ministryName")

    truncated = len(order) > limit
    kept = order[:limit]
    hits = []
    for entity in kept:
        a = acc[entity]
        type_local = _most_specific_type(a.types)
        summary = _derive_summary(
            type_local, a.law_num, a.prefecture_name, a.city_name, a.fiscal_year, a.ministry_name
        )
        hits.append(
            SearchHit(
                id=entity,
                id_path=_id_path(base_uri, entity),
                type=type_local,
                label=a.label,
                summary=summary,
            )
        )

    return SearchResponse(query=q, results=hits, limit=limit, truncated=truncated)


# =============================================================================
# エンティティ詳細
# =============================================================================

#: attributes・relationshipsどちらにも出さない述語(type・labelは専用フィールド
#: で別に返すため、汎用の辞書に重複させない)。
#: **relationships側にも要る理由(実装中に実際に踏んだ欠陥)**: `rdf:type`の
#: 目的語(例: `budget:BudgetProject`というオントロジーのクラスURI)はリテラル
#: ではないため、これを除外しないと「関係の相手」としてオントロジーのクラス
#: そのものを指す偽の関係(`type="unknown"`)が紛れ込む——実測で発生し、
#: `tests/test_api_entity.py`の関係数アサートが検出した
_TYPE_AND_LABEL_PREDICATES = frozenset({
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
})


def _build_own_type_query(base_uri: str, entity_iri: str) -> str:
    return _prefixes(base_uri) + f"""
SELECT ?type ?label WHERE {{
  {entity_iri} a ?type .
  OPTIONAL {{ {entity_iri} skos:prefLabel ?label }}
}}
"""


def _build_attributes_query(base_uri: str, entity_iri: str) -> str:
    # **上限を付けない。** 属性はスキーマで決まる有限個の述語であり、
    # 関係(相手が別エンティティ、fan-outしうる)と違ってhairballの原因に
    # ならない——上限は「データ依存で際限なく増えうるもの」にだけ効かせる、
    # というD-3ブリーフの上限の趣旨(hairball防止)に合わせた区別
    excluded = " , ".join(f"<{p}>" for p in sorted(_TYPE_AND_LABEL_PREDICATES))
    return _prefixes(base_uri) + f"""
SELECT ?p ?o WHERE {{
  {entity_iri} ?p ?o .
  FILTER(isLiteral(?o))
  FILTER(?p NOT IN ({excluded}))
}}
ORDER BY ?p ?o
"""


def _build_relationship_edges_query(base_uri: str, entity_iri: str, fetch_limit: int) -> str:
    # **両方向を1つのUNIONクエリにまとめ、1つのLIMITで結果全体を絞る。**
    # outgoing/incomingを別クエリにして個別にLIMITすると、片方に上限を
    # 付け忘れるという「部分適用」(このプロジェクトの再発欠陥3)の型を
    # 作り込みやすい——1本のクエリ・1つのLIMITにすることで構造的に防ぐ
    excluded = " , ".join(f"<{p}>" for p in sorted(_TYPE_AND_LABEL_PREDICATES))
    return _prefixes(base_uri) + f"""
SELECT ?direction ?p ?other ?g ?source ?fetchedOn ?license WHERE {{
  {{
    GRAPH ?g {{ {entity_iri} ?p ?other }}
    FILTER(!isLiteral(?other))
    BIND("outgoing" AS ?direction)
  }} UNION {{
    GRAPH ?g {{ ?other ?p {entity_iri} }}
    BIND("incoming" AS ?direction)
  }}
  FILTER(?p NOT IN ({excluded}))
  ?g prov:wasDerivedFrom ?source ;
     prov:generatedAtTime ?fetchedOn ;
     dcterms:rights ?license .
}}
ORDER BY ?direction ?p ?other
LIMIT {fetch_limit}
"""


def _build_related_labels_query(base_uri: str, uris: Iterable[str]) -> str:
    values = " ".join(f"<{u}>" for u in uris)
    return _prefixes(base_uri) + f"""
SELECT ?entity ?type ?label WHERE {{
  VALUES ?entity {{ {values} }}
  OPTIONAL {{ ?entity a ?type }}
  OPTIONAL {{ ?entity skos:prefLabel ?label }}
}}
"""


def get_entity_detail(
    client: KGClient, base_uri: str, id_path: str, limit: int
) -> EntityDetailResponse | None:
    """エンティティ詳細エンドポイントの本体。存在しなければ`None`(呼び出し側が404にする)。"""
    # **素の文字列結合(f"{base_uri}/id/{id_path}")にしない(裁定B69)。**
    # id_pathはFastAPI/Starletteが既に1回URLデコードした生文字列であり、
    # %を含むIDでは素の結合とcanonical_iri(再エンコードする)が分岐する
    # ——応答のidがKGに存在しないIRIになる欠陥だった。応答のid(entity_uri)
    # とSPARQLクエリ(entity_iri)の両方をcanonical_iri/sparql_iri(内部で
    # canonical_iriを呼ぶだけ)という同じ1本の関数経由にすることで、
    # 二度と分岐しないようにする(kgclient.canonical_iriのdocstring参照)。
    entity_uri = canonical_iri(base_uri, id_path)
    entity_iri = sparql_iri(base_uri, id_path)

    own_rows = client.query(_build_own_type_query(base_uri, entity_iri))
    if not own_rows:
        return None
    own_types = [_local_name(_value(r, "type")) for r in own_rows if _value(r, "type")]
    own_label = next((_value(r, "label") for r in own_rows if _value(r, "label")), None)
    type_local = _most_specific_type(own_types)

    attribute_rows = client.query(_build_attributes_query(base_uri, entity_iri))
    attributes: dict[str, list[str]] = {}
    for row in attribute_rows:
        pred = _local_name(_value(row, "p"))
        value = _value(row, "o")
        if value is None:
            continue
        attributes.setdefault(pred, []).append(value)

    fetch_limit = limit + 1
    edge_rows = client.query(_build_relationship_edges_query(base_uri, entity_iri, fetch_limit))
    truncated = len(edge_rows) > limit
    kept_edges = edge_rows[:limit]

    related_uris = {_value(r, "other") for r in kept_edges if _value(r, "other")}
    related_refs = _hydrate_entity_refs(client, base_uri, related_uris)

    relationships: dict[str, list[Relationship]] = {}
    # **出典を辺ごとに複製せず、グラフのキーで参照する**(D-4の裁定2)。
    # 同じグラフ由来の辺が違う出典を主張することが構造的に不可能になり、
    # かつ同じ4つの文字列を辺の数だけ送らなくなる(決定#33: 件数上限は
    # 外向き通信量のコスト対策でもある)。`models.py`の`Relationship.graph`参照
    graphs: dict[str, Provenance] = {}
    for row in kept_edges:
        other = _value(row, "other")
        if other is None:
            continue
        related_ref = related_refs.get(other) or _unknown_entity_ref(base_uri, other)
        related_type = related_ref.type
        graph = _value(row, "g") or ""
        if graph and graph not in graphs:
            graphs[graph] = Provenance(
                graph=graph,
                source=_value(row, "source") or "",
                fetched_on=_value(row, "fetchedOn") or "",
                license=_value(row, "license") or "",
            )
        rel = Relationship(
            predicate=_local_name(_value(row, "p")),
            direction=_value(row, "direction") or "outgoing",
            related=related_ref,
            graph=graph,
        )
        # **型別にグループ化する(D-3ブリーフ)。** キーは相手側エンティティの
        # 型——「所管府省」と「根拠法令」のような述語別ではなく、Law/
        # Ministry/Expenditureのような相手の型別に束ねる方が、型別レイアウト
        # (仕様§9.2)のUIパネル構成に直接使える
        relationships.setdefault(related_type, []).append(rel)

    return EntityDetailResponse(
        id=entity_uri,
        # `id_path`引数をそのまま使わず、`_id_path`で`entity_uri`から再導出する
        # (裁定B59)。ただし`_id_path`が防ぐのは箇所ごとの手書きのばらつき
        # だけで、`entity_uri`自体が誤っていれば`id_path`も一貫して誤ったまま
        # 導出される(裁定B69の訂正。queries.pyの`_id_path`docstring参照)。
        # `entity_uri`を`canonical_iri`(kgclient.py)から組み立てることが、
        # 裁定B69での実際の修正(このEntityDetailResponse呼び出しの直前)。
        id_path=_id_path(base_uri, entity_uri),
        type=type_local,
        label=own_label,
        attributes=attributes,
        relationships=relationships,
        graphs=graphs,
        relationships_limit=limit,
        relationships_truncated=truncated,
    )


# =============================================================================
# 共通: ノードの型・ラベルの取得と、出典の取得
# =============================================================================


def _unknown_entity_ref(base_uri: str, uri: str) -> EntityRef:
    """型もラベルも引けなかったIRIの`EntityRef`。

    **黙って落とさない。** KGに`rdf:type`が無いIRIが関係の相手側に現れること
    はありうる(隔離されたソースの残骸など)——応答から消すと利用者には
    「そこには何も無い」と見えるので、`type="unknown"`として出す。
    """
    return EntityRef(id=uri, id_path=_id_path(base_uri, uri), type="unknown", label=None)


def _hydrate_entity_refs(
    client: KGClient, base_uri: str, uris: Iterable[str]
) -> dict[str, EntityRef]:
    """IRIの集合に対して型とラベルを**1回のクエリ**で引き、`EntityRef`にする。

    **1本にまとめる理由**: エンティティ詳細・近傍サブグラフ・パス探索の
    3箇所が同じことをする。箇所ごとに書くと、`id_path`の導出や「型は最も
    具体的なもの1つ」(`_most_specific_type`)の規則がばらつく——
    **裁定B59とB69がまさにその族の欠陥だった**(同じ値を2つの規則で作る)。
    """
    wanted = sorted({u for u in uris if u})
    if not wanted:
        return {}
    rows = client.query(_build_related_labels_query(base_uri, wanted))
    acc: dict[str, tuple[list[str], str | None]] = {}
    for row in rows:
        uri = _value(row, "entity")
        if uri is None:
            continue
        types, label = acc.get(uri, ([], None))
        type_uri = _value(row, "type")
        if type_uri:
            types.append(_local_name(type_uri))
        label = label or _value(row, "label")
        acc[uri] = (types, label)
    return {
        uri: EntityRef(
            id=uri,
            id_path=_id_path(base_uri, uri),
            type=_most_specific_type(types),
            label=label,
        )
        for uri, (types, label) in acc.items()
    }


def _build_provenance_query(base_uri: str, graph_uris: Iterable[str]) -> str:
    """名前付きグラフの集合に対して出典を**1回のクエリ**で引く。

    **探索の途中で出典を結合しない**(D-4)。`_build_relationship_edges_query`
    は出典を**必須で**結合しているため、`prov:wasDerivedFrom`等を持たない
    グラフの辺は**黙って消える**——エンティティ詳細の契約としてはそれでよいが
    (壊し確認のテストがその挙動を固定している)、**連結性の探索では
    辺が消えると経路が見つからなくなる。** そのため探索は軽いクエリ
    (`?direction ?p ?other ?g`だけ)で行い、出典は**最後に一度だけ**引く。
    グラフは7本程度なので1本のクエリで足りる。
    """
    values = " ".join(f"<{g}>" for g in sorted({g for g in graph_uris if g}))
    return _prefixes(base_uri) + f"""
SELECT ?g ?source ?fetchedOn ?license WHERE {{
  VALUES ?g {{ {values} }}
  ?g prov:wasDerivedFrom ?source ;
     prov:generatedAtTime ?fetchedOn ;
     dcterms:rights ?license .
}}
"""


def _hydrate_graphs(
    client: KGClient, base_uri: str, graph_uris: Iterable[str]
) -> dict[str, Provenance]:
    """グラフのキー → 出典のマップを作る(D-4の裁定2の正規化形)。

    **出典が引けなかったグラフも、キーだけは残さない** ——
    `models.py`が「応答に現れるすべての`graph`が`graphs`に存在する」と
    宣言しているため、引けなかったものは空文字列の`Provenance`で埋める。
    **黙って欠かすと消費者がキーの不在を扱わなければならなくなる。**
    """
    wanted = sorted({g for g in graph_uris if g})
    if not wanted:
        return {}
    rows = client.query(_build_provenance_query(base_uri, wanted))
    found: dict[str, Provenance] = {}
    for row in rows:
        g = _value(row, "g")
        if g is None:
            continue
        found[g] = Provenance(
            graph=g,
            source=_value(row, "source") or "",
            fetched_on=_value(row, "fetchedOn") or "",
            license=_value(row, "license") or "",
        )
    for g in wanted:
        if g not in found:
            found[g] = Provenance(graph=g, source="", fetched_on="", license="")
    return found


# =============================================================================
# 近傍サブグラフとパス探索(D-4。仕様§9.1の残る2用途)
# =============================================================================

#: 深さは**1か2のみ**。仕様§9.1が「指定ノードから深さ1-2のノード/エッジ」と
#: 書いている。3以上は拒否する(黙って2に丸めない——上のlimitの節と同じ理由)。
NEIGHBORHOOD_DEFAULT_DEPTH = 1
NEIGHBORHOOD_MAX_DEPTH = 2

#: 総ノード数・総エッジ数の上限。Sigma.js(仕様§9.2)で一画面に描いて
#: 意味が読める規模を既定にし、上限はその5倍に置いた。**「全体グラフの
#: 一括表示は実装しない」(§9.2)ため、上限を大きくする動機が無い。**
NEIGHBORHOOD_DEFAULT_NODE_LIMIT = 100
NEIGHBORHOOD_MAX_NODE_LIMIT = 500
NEIGHBORHOOD_DEFAULT_EDGE_LIMIT = 200
NEIGHBORHOOD_MAX_EDGE_LIMIT = 1000

#: **1ノードあたりの分岐数の上限。総数の上限だけでは足りない。**
#: 実データの府省は数千の辺を持つ(支出73,919件が事業と府省に集まる)——
#: 深さ2で総数上限だけを掛けると、**ハブ1個の隣接だけで上限を食い潰し、
#: 他の方向が1つも見えない**。利用者には「そこには何も無い」と見える
#: (このプロジェクトが繰り返し扱う「報告が嘘をつく」型)。
NEIGHBORHOOD_DEFAULT_FANOUT_LIMIT = 25
NEIGHBORHOOD_MAX_FANOUT_LIMIT = 100

#: パス探索の深さ。**法令↔法人の経路は「法令→府省→事業→支出→法人」で
#: 4ホップ**(設計書§1.2(C)の縦スライスそのもの)なので、既定を4に置いた。
#: 上限6は、その縦スライスに1〜2ホップの寄り道が入っても届く余裕。
PATH_DEFAULT_MAX_DEPTH = 4
PATH_MAX_MAX_DEPTH = 6

#: **訪問ノード数の予算**(hairball防止をAPI側で保証する。仕様§9.1)。
#: 双方向BFSなので、両側の訪問数の合計に効く。
PATH_DEFAULT_VISIT_BUDGET = 400
PATH_MAX_VISIT_BUDGET = 2000

#: パス探索の1ノードあたりの分岐数の上限。**これが効くと探索は不完全になり、
#: `exhaustive`は真になれない**(切ったのに「尽くした」と言うのは嘘である)。
PATH_DEFAULT_FANOUT_LIMIT = 50
PATH_MAX_FANOUT_LIMIT = 200


def _build_expansion_query(base_uri: str, entity_iri: str, fanout_limit: int) -> str:
    """1ホップ分の辺を**両方向**取る軽いクエリ(出典を結合しない)。

    **`_build_relationship_edges_query`を流用しない理由(2つ)**:

    **(1) あちらは出典を必須で結合している。** `?g prov:wasDerivedFrom ...`が
    OPTIONALでないため、**出典3項を持たないグラフの辺は黙って消える。**
    エンティティ詳細の契約としてはそれでよい(壊し確認のテストがその挙動を
    固定している)が、**連結性の探索で辺が消えると経路が見つからなくなる。**

    **(2) 探索中の出典の結合は無駄である。** 出典は最後に一度だけ引けばよい
    (`_hydrate_graphs`。グラフは7本程度)——D-4の裁定2で出典を正規化した
    ことが、ここで効いている。

    **目的語をベースURI配下の`/id/`名前空間に明示的に限定する。**
    `!isLiteral`だけでは語彙の項(`/def/`)や外部IRIも通る——
    実測では現状`/def/`を指すのは`rdf:type`だけ(除外済み)で等価だが、
    **規則として名前空間で縛る方が将来のデータに対して安全**である。
    """
    excluded = " , ".join(f"<{p}>" for p in sorted(_TYPE_AND_LABEL_PREDICATES))
    return _prefixes(base_uri) + f"""
SELECT ?direction ?p ?other ?g WHERE {{
  {{
    GRAPH ?g {{ {entity_iri} ?p ?other }}
    BIND("outgoing" AS ?direction)
  }} UNION {{
    GRAPH ?g {{ ?other ?p {entity_iri} }}
    BIND("incoming" AS ?direction)
  }}
  FILTER(?p NOT IN ({excluded}))
  FILTER(isIRI(?other))
  FILTER(STRSTARTS(STR(?other), "{base_uri}/id/"))
}}
ORDER BY ?direction ?p ?other
LIMIT {fanout_limit + 1}
"""


@dataclass(frozen=True)
class _Hop:
    """探索中の1本の辺。`GraphEdge`にする前の内部表現。"""

    source: str
    target: str
    predicate: str
    graph: str

    def other_than(self, uri: str) -> str:
        return self.target if self.source == uri else self.source


def _expand(
    client: KGClient, base_uri: str, uri: str, fanout_limit: int
) -> tuple[list[_Hop], bool]:
    """1ノードの隣接を取る。戻り値は`(辺, 分岐数の上限で切ったか)`。

    **フロンティアをVALUESで束ねて1クエリにしない。** 束ねると1つのLIMITが
    全体に効き、**ハブが予算を食い潰して他のノードが1本も寄与できない**
    ——それは仕様§9.1が「API側で保証する」と定めたhairball防止の失敗そのもの
    である。**1ノード1クエリにすれば、1ノードあたりの分岐数の上限が
    構造から出てくる。** 束ねるのは後の最適化であって最初の形ではない。
    """
    # **`sparql_iri`を使わない。** `uri`はSPARQLの結果として受け取った
    # **既に正準形の**完全IRIであり、`_id_path`で剥がして`sparql_iri`に渡すと
    # **セグメントごとに再エンコードされて二重エンコードになる**
    # (`%E5%8E%9A` -> `%25E5%258E%259A`)——D-4の実装中に実際に踏み、
    # `%`を含むノード(厚生省)の辺が1本も見つからなかった。
    # 裁定B59・B69と同じ族(同じ値を2つの規則で作る)が1層深いところにあった。
    # 使い分けの規則は`kgclient.sparql_iri_for_canonical_uri`のdocstringにある
    iri = sparql_iri_for_canonical_uri(uri)
    rows = client.query(_build_expansion_query(base_uri, iri, fanout_limit))
    truncated = len(rows) > fanout_limit
    hops: list[_Hop] = []
    for row in rows[:fanout_limit]:
        other = _value(row, "other")
        predicate = _value(row, "p")
        if other is None or predicate is None:
            continue
        outgoing = (_value(row, "direction") or "outgoing") == "outgoing"
        hops.append(
            _Hop(
                source=uri if outgoing else other,
                target=other if outgoing else uri,
                predicate=_local_name(predicate),
                graph=_value(row, "g") or "",
            )
        )
    return hops, truncated


def _entity_exists(client: KGClient, base_uri: str, id_path: str) -> EntityRef | None:
    """エンティティが存在すれば`EntityRef`を返す。無ければ`None`(呼び出し側が404)。"""
    iri = sparql_iri(base_uri, id_path)
    rows = client.query(_build_own_type_query(base_uri, iri))
    if not rows:
        return None
    uri = canonical_iri(base_uri, id_path)
    types = [_local_name(_value(r, "type")) for r in rows if _value(r, "type")]
    label = next((_value(r, "label") for r in rows if _value(r, "label")), None)
    return EntityRef(
        id=uri, id_path=_id_path(base_uri, uri), type=_most_specific_type(types), label=label
    )


def get_neighborhood(
    client: KGClient,
    base_uri: str,
    id_path: str,
    depth: int,
    node_limit: int,
    edge_limit: int,
    fanout_limit: int,
) -> NeighborhoodResponse | None:
    """近傍サブグラフの本体。存在しなければ`None`(呼び出し側が404にする)。"""
    center = _entity_exists(client, base_uri, id_path)
    if center is None:
        return None

    seen_nodes: dict[str, None] = {center.id: None}  # 挿入順を保つ集合
    hops: dict[_Hop, None] = {}  # 同じ辺が両端から2回出るので重複を除く
    fanout_truncated_nodes: list[str] = []
    nodes_truncated = False
    edges_truncated = False

    frontier = [center.id]
    for _level in range(depth):
        next_frontier: list[str] = []
        for node in frontier:
            if len(hops) >= edge_limit:
                edges_truncated = True
                break
            node_hops, hit_fanout = _expand(client, base_uri, node, fanout_limit)
            if hit_fanout:
                fanout_truncated_nodes.append(node)
            for hop in node_hops:
                if hop in hops:
                    continue
                if len(hops) >= edge_limit:
                    edges_truncated = True
                    break
                hops[hop] = None
                other = hop.other_than(node)
                if other in seen_nodes:
                    continue
                if len(seen_nodes) >= node_limit:
                    nodes_truncated = True
                    continue
                seen_nodes[other] = None
                next_frontier.append(other)
        frontier = next_frontier
        if not frontier:
            break

    refs = _hydrate_entity_refs(client, base_uri, seen_nodes)
    nodes = [refs.get(uri) or _unknown_entity_ref(base_uri, uri) for uri in seen_nodes]
    edges = [
        GraphEdge(source=h.source, target=h.target, predicate=h.predicate, graph=h.graph)
        for h in hops
    ]
    return NeighborhoodResponse(
        center=center,
        depth=depth,
        nodes=nodes,
        edges=edges,
        graphs=_hydrate_graphs(client, base_uri, (h.graph for h in hops)),
        node_limit=node_limit,
        edge_limit=edge_limit,
        fanout_limit=fanout_limit,
        nodes_truncated=nodes_truncated,
        edges_truncated=edges_truncated,
        fanout_truncated_nodes=sorted(set(fanout_truncated_nodes)),
    )


def find_path(
    client: KGClient,
    base_uri: str,
    from_path: str,
    to_path: str,
    max_depth: int,
    visit_budget: int,
    fanout_limit: int,
) -> PathResponse | None:
    """パス探索の本体。両端のどちらかが存在しなければ`None`(呼び出し側が404)。

    **SPARQLの可変長パス(`*`/`+`)を使わない。** あれは「到達可能か」しか
    返さず、**経路そのものを返さない** ——仕様§9.1が要求するのは
    「2エンティティ間の**経路**」である。884,052クアッドに対する無制限の
    列挙は危険なので、**API層で境界付きの双方向BFS**を行う。

    **辺の向きを無視して探索する(`undirected=True`)。**
    実測: `UnresolvedReference`は出る辺771本・**入る辺0本**、
    `Expenditure`の`project`は法令↔法人の経路にとって「逆向き」——
    **向きを守って探索するとほとんど何も見つからない。**
    """
    start = _entity_exists(client, base_uri, from_path)
    goal = _entity_exists(client, base_uri, to_path)
    if start is None or goal is None:
        return None

    # 各側で「そのノードへ来た辺」を覚える(経路の復元用)
    came: tuple[dict[str, _Hop | None], dict[str, _Hop | None]] = (
        {start.id: None},
        {goal.id: None},
    )
    frontiers: tuple[list[str], list[str]] = ([start.id], [goal.id])
    visited = {start.id, goal.id}
    fanout_truncated = False
    searched_depth = 0
    budget_exhausted = False
    meeting: str | None = None

    if start.id == goal.id:
        meeting = start.id

    while meeting is None and searched_depth < max_depth:
        # 小さい方のフロンティアを広げる(双方向BFSの定石。訪問数を抑える)
        side = 0 if len(frontiers[0]) <= len(frontiers[1]) else 1
        if not frontiers[side]:
            break
        searched_depth += 1
        next_frontier: list[str] = []
        for node in frontiers[side]:
            if len(visited) >= visit_budget:
                budget_exhausted = True
                break
            node_hops, hit_fanout = _expand(client, base_uri, node, fanout_limit)
            if hit_fanout:
                fanout_truncated = True
            for hop in node_hops:
                other = hop.other_than(node)
                if other in came[side]:
                    continue
                came[side][other] = hop
                if other in came[1 - side]:
                    meeting = other
                    break
                if len(visited) >= visit_budget:
                    budget_exhausted = True
                    break
                visited.add(other)
                next_frontier.append(other)
            if meeting is not None or budget_exhausted:
                break
        frontiers = (next_frontier, frontiers[1]) if side == 0 else (frontiers[0], next_frontier)
        if meeting is not None or budget_exhausted:
            break

    depth_limited = meeting is None and searched_depth >= max_depth
    # **片側のフロンティアが空になれば、その側の到達可能集合を尽くしたことに
    # なるので、経路は存在しない**(双方向BFSの性質)。「両方が空」を条件に
    # すると、辺を1本も持たないノード(実データの`LawRevision` 9,550件。
    # 観察O10)を始点にしたときに「尽くした」と言えなくなる ——
    # **正しく言えるときに言わないのも、応答が実態とずれることである。**
    frontiers_empty = not frontiers[0] or not frontiers[1]
    # **切ったのに「尽くした」と言わない。** 予算切れ・深さ打ち切り・
    # 分岐数の上限のいずれかが効いていたら、探索は不完全である
    exhaustive = (
        meeting is None
        and not budget_exhausted
        and not depth_limited
        and not fanout_truncated
        and frontiers_empty
    )

    node_uris: list[str] = []
    path_hops: list[_Hop] = []
    if meeting is not None:
        forward: list[_Hop] = []
        cursor = meeting
        while (hop := came[0].get(cursor)) is not None:
            forward.append(hop)
            cursor = hop.other_than(cursor)
        forward.reverse()
        backward: list[_Hop] = []
        cursor = meeting
        while (hop := came[1].get(cursor)) is not None:
            backward.append(hop)
            cursor = hop.other_than(cursor)
        path_hops = forward + backward
        node_uris = [start.id]
        cursor = start.id
        for hop in path_hops:
            cursor = hop.other_than(cursor)
            node_uris.append(cursor)

    refs = _hydrate_entity_refs(client, base_uri, node_uris)
    return PathResponse(
        start=start,
        goal=goal,
        nodes=[refs.get(u) or _unknown_entity_ref(base_uri, u) for u in node_uris],
        edges=[
            GraphEdge(source=h.source, target=h.target, predicate=h.predicate, graph=h.graph)
            for h in path_hops
        ],
        graphs=_hydrate_graphs(client, base_uri, (h.graph for h in path_hops)),
        found=meeting is not None,
        max_depth=max_depth,
        visit_budget=visit_budget,
        visited=len(visited),
        searched_depth=searched_depth,
        budget_exhausted=budget_exhausted,
        depth_limited=depth_limited,
        fanout_limit=fanout_limit,
        fanout_truncated=fanout_truncated,
        exhaustive=exhaustive,
        undirected=True,
    )
