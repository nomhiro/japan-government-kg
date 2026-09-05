"""オントロジーの日本語表示名(`dcterms:title`。裁定B78)をフロントエンド向けに抜き出す本体。

**`scripts/export-frontend-labels.py`はこのモジュールを呼ぶだけの薄いCLIにする。**
理由は`scripts/verify-site.py`/`jgkg.site_verify`と同じ——ハイフンを含む
スクリプトファイルはPythonの`import`文で読めないため、テスト可能な本体は
ここに置く。

**手書きしない理由(裁定B78の(4))**: 表示名は`schema/*.yaml`に足された
`title:`が生成規則(`schema_lang.py`)を通って`schema/generated/*.owl.ttl`に
`dcterms:title "…"@ja`として現れる——アプリはそれを読むだけで、対応表を
別に持たない。API(`src/jgkg/api/queries.py`の`_local_name`)が返す型名・
述語名は、このオントロジーのハッシュURI(`{base}/def/{module}#{名前}`)の
フラグメントと**同じ文字列**なので、フラグメントをキーにするだけで両者は
必ず一致する。

**ビルド時に取り込む(実行時にAPI経由で取得しない)理由**: (1) 起動時に
`/def/all.owl.ttl`を取得してブラウザ側でTurtleを解析する処理と依存
(パーサのバンドル)を増やしたくない——このプロジェクトの原則1
「本体はオントロジーとKG、アプリは検証装置」により投資を絞る。
(2) `schema/generated/`は既にコミットする方針(設計書§5.1)で、このJSONは
そこから導出した副産物にすぎない。

**この選択が生む結合(気になる点として明示する)**: オントロジーの
`title:`が変わっても、このJSONを再生成してフロントエンドを再ビルドしない
限り画面の表示名は追随しない。CIは`scripts/generate-frontend-types.sh`を
再実行して差分が無いことを確認する(schema/generated/のregen-diff
チェックと同じ形)ことでこの追随漏れを検出する。

**列挙型の許容値(`resolved`/`bundled`等)は`enumValues`に入る**
(裁定B82(4b)。labelsタスク〔裁定B78〕当時は未着手だったため、上の段落は
当時それを明記していた)。

**設計判断: 裸のリテラルではなく述語のローカル名で名前空間を分ける。**
値そのもの(例: `"resolved"`)を直接キーにする対応表も作れるが、**別の
列挙型が同じリテラルを持てば衝突する**(2つの意味が1つのキーを取り合い、
どちらかが誤った表示名を出す——例外は投げない静かな欠陥になる)。
今回対象の2つの列挙型(`RecipientMatchCategoryEnum`・
`UnresolvedReasonEnum`)は値が8件すべて相異なるため、裸のリテラル対応でも
**現時点では**動く。しかし将来別の列挙型が増えたときにこの前提が
静かに崩れる——「導出すべき値を手書きする」の変種として再発しうる
(裁定B66が列挙値のIRIをそもそも`#`1つに直したのも同じ「衝突を構造的に
防ぐ」判断)。そこで**述語IRI→(`rdfs:range`)→列挙型IRI→
(`rdfs:subClassOf`の逆向き)→許容値IRI→`dcterms:title`**という、
オントロジー自身が持つ曖昧さの無い経路を辿り、**述語のローカル名を
キーにした**`{値: 表示名}`を返す。同じ値文字列を持つ列挙型が増えても、
述語ごとに名前空間が分かれているので衝突しない。

**「述語IRI→列挙型IRI」の対応をJSONの別キーとして書き出さない判断**:
この対応もオントロジーから機械的に導出できるが、フロントエンドが必要とする
最終形は「この述語のこの値の表示名」であり、経由するのは列挙型IRIという
中間結果に過ぎない。ここ(ビルド時・Python側)で一度だけ`rdfs:range`を
辿って`{述語ローカル名: {値: 表示名}}`まで解決してしまえば、フロントエンドは
2段の結合をランタイムで行う必要が無くなる——`labels.ts`の`enumValueLabel`は
`predicates`/`types`と同じ1段引きで済む。
"""
from __future__ import annotations

from pathlib import Path

from rdflib import RDF, RDFS, Graph, URIRef
from rdflib.namespace import DCTERMS

#: この型を持つ主語だけを対象にする。オントロジー自身(owl:Ontology)や
#: SHACL由来の生成物には`dcterms:title`が付くことがあるが対象外
#: (`queries.py`の`_local_name`が返すのは型名・述語名のローカル名だけ)。
_CLASS = "http://www.w3.org/2002/07/owl#Class"
_OBJECT_PROPERTY = "http://www.w3.org/2002/07/owl#ObjectProperty"
_DATATYPE_PROPERTY = "http://www.w3.org/2002/07/owl#DatatypeProperty"
_RELEVANT_TYPES = frozenset({_CLASS, _OBJECT_PROPERTY, _DATATYPE_PROPERTY})


def extract_labels(owl_path: Path) -> dict[str, dict]:
    """`owl_path`(Turtle)から`{"types": {...}, "predicates": {...}, "enumValues": {...}}`を導出する。

    `types`/`predicates`のキーはハッシュURIのフラグメント(`queries.py`の
    `_local_name`と同じ切り出し方)。クラスは"types"、Object/Datatype
    Propertyは"predicates"に入れる——同じローカル名がクラスと述語の両方に
    現れることは無いはずだが、名前空間を分けておけば衝突しても互いを
    上書きしない。`enumValues`は`_enum_value_labels`(モジュールdocstring
    参照)。

    **列挙型の許容値(`a owl:Class`。裁定B66)は"types"に入れない。**
    許容値もクラスとして宣言されているため、フィルタしないと`_local_name`が
    返さない形(フラグメントに`/`を含む`EnumName/値`)のキーが"types"に
    紛れ込む——`queries.py`が返す型名と一致しないキーなので、
    `typeLabel`(labels.ts)から永遠に引けない死んだエントリになる。
    """
    g = Graph()
    g.parse(owl_path, format="turtle")

    types: dict[str, str] = {}
    predicates: dict[str, str] = {}
    for s in set(g.subjects()):
        if not isinstance(s, URIRef):
            continue
        title = g.value(s, DCTERMS.title)
        if title is None:
            continue
        rdf_types = {str(t) for t in g.objects(s, RDF.type)}
        if not (rdf_types & _RELEVANT_TYPES):
            continue
        if "#" not in str(s):
            continue
        local = str(s).rsplit("#", 1)[-1]
        if "/" in local:
            continue  # 列挙型の許容値(enumValuesが別途持つ)
        if _CLASS in rdf_types:
            types[local] = str(title)
        else:
            predicates[local] = str(title)

    return {
        "types": dict(sorted(types.items())),
        "predicates": dict(sorted(predicates.items())),
        "enumValues": _enum_value_labels(g),
    }


def _enum_value_labels(g: Graph) -> dict[str, dict[str, str]]:
    """述語のローカル名をキーにした`{値: 表示名}`を、`rdfs:range`/`rdfs:subClassOf`から導出する。

    手で列挙しない。`g`にある全ての`(述語, rdfs:range)`の組から、
    範囲が列挙型であるものだけを辿る——「範囲が列挙型かどうか」自体も
    `rdfs:subClassOf`で範囲を指す許容値IRIが1件以上あるかで判定するので、
    どの述語が列挙型を範囲に持つかを手書きで列挙する必要が無い。

    許容値IRIの見分け方(裁定B66): `{enum_uri}/{値}`という形(単一の`#`の
    後に`/`が入る)を持つことを条件にする——列挙型ではない普通のクラスが
    `rdfs:subClassOf`で他のクラスを指す場合(継承)と区別するため。
    """
    enum_values: dict[str, dict[str, str]] = {}
    for predicate, range_cls in g.subject_objects(RDFS.range):
        if not isinstance(predicate, URIRef) or "#" not in str(predicate):
            continue
        values: dict[str, str] = {}
        for value_iri in g.subjects(RDFS.subClassOf, range_cls):
            frag = str(value_iri).rsplit("#", 1)[-1]
            if "/" not in frag:
                continue  # 列挙型の許容値ではない、ただの継承関係
            title = g.value(value_iri, DCTERMS.title)
            if title is None:
                continue
            values[frag.split("/", 1)[-1]] = str(title)
        if values:
            pred_local = str(predicate).rsplit("#", 1)[-1]
            enum_values[pred_local] = dict(sorted(values.items()))
    return dict(sorted(enum_values.items()))
