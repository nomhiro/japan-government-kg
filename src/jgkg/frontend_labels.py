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

**列挙型の許容値(`resolved`/`bundled`等)はここに含まれない**
(裁定B78の(2)注記: labelsタスクの範囲外で、まだ日本語表示名を持たない)。
アプリはこれらを未翻訳のまま表示し、controllerへの報告事項とする
(D-5ブリーフの指示どおり、ここで手書きの対応表を作らない)。
"""
from __future__ import annotations

from pathlib import Path

from rdflib import RDF, Graph, URIRef
from rdflib.namespace import DCTERMS

#: この型を持つ主語だけを対象にする。オントロジー自身(owl:Ontology)や
#: SHACL由来の生成物には`dcterms:title`が付くことがあるが対象外
#: (`queries.py`の`_local_name`が返すのは型名・述語名のローカル名だけ)。
_CLASS = "http://www.w3.org/2002/07/owl#Class"
_OBJECT_PROPERTY = "http://www.w3.org/2002/07/owl#ObjectProperty"
_DATATYPE_PROPERTY = "http://www.w3.org/2002/07/owl#DatatypeProperty"
_RELEVANT_TYPES = frozenset({_CLASS, _OBJECT_PROPERTY, _DATATYPE_PROPERTY})


def extract_labels(owl_path: Path) -> dict[str, dict[str, str]]:
    """`owl_path`(Turtle)から`{"types": {...}, "predicates": {...}}`を導出する。

    キーはハッシュURIのフラグメント(`queries.py`の`_local_name`と同じ
    切り出し方)。クラスは"types"、Object/DatatypePropertyは"predicates"に
    入れる——同じローカル名がクラスと述語の両方に現れることは無いはずだが、
    名前空間を分けておけば衝突しても互いを上書きしない。
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
        if _CLASS in rdf_types:
            types[local] = str(title)
        else:
            predicates[local] = str(title)

    return {"types": dict(sorted(types.items())), "predicates": dict(sorted(predicates.items()))}
