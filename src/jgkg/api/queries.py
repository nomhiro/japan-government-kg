"""検索・エンティティ詳細それぞれのSPARQLクエリ組み立てと、結果の解釈。

ルート(`app.py`)はここの`search_entities()`/`get_entity_detail()`しか呼ばない
——HTTP層とSPARQL/ドメインロジックを分けるため。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from jgkg.api.kgclient import KGClient, Row, sparql_iri, sparql_string_literal
from jgkg.api.models import (
    EntityDetailResponse,
    EntityRef,
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
        hits.append(SearchHit(id=entity, type=type_local, label=a.label, summary=summary))

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
    entity_uri = f"{base_uri}/id/{id_path}"
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
    related_info: dict[str, tuple[str, str | None]] = {}
    if related_uris:
        label_rows = client.query(_build_related_labels_query(base_uri, related_uris))
        acc: dict[str, tuple[list[str], str | None]] = {}
        for row in label_rows:
            uri = _value(row, "entity")
            if uri is None:
                continue
            types, label = acc.get(uri, ([], None))
            related_type = _value(row, "type")
            if related_type:
                types.append(_local_name(related_type))
            label = label or _value(row, "label")
            acc[uri] = (types, label)
        for uri, (types, label) in acc.items():
            related_info[uri] = (_most_specific_type(types), label)

    relationships: dict[str, list[Relationship]] = {}
    for row in kept_edges:
        other = _value(row, "other")
        if other is None:
            continue
        related_type, related_label = related_info.get(other, ("unknown", None))
        rel = Relationship(
            predicate=_local_name(_value(row, "p")),
            direction=_value(row, "direction") or "outgoing",
            related=EntityRef(id=other, type=related_type, label=related_label),
            provenance=Provenance(
                graph=_value(row, "g") or "",
                source=_value(row, "source") or "",
                fetched_on=_value(row, "fetchedOn") or "",
                license=_value(row, "license") or "",
            ),
        )
        # **型別にグループ化する(D-3ブリーフ)。** キーは相手側エンティティの
        # 型——「所管府省」と「根拠法令」のような述語別ではなく、Law/
        # Ministry/Expenditureのような相手の型別に束ねる方が、型別レイアウト
        # (仕様§9.2)のUIパネル構成に直接使える
        relationships.setdefault(related_type, []).append(rel)

    return EntityDetailResponse(
        id=entity_uri,
        type=type_local,
        label=own_label,
        attributes=attributes,
        relationships=relationships,
        relationships_limit=limit,
        relationships_truncated=truncated,
    )
