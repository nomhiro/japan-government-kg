"""生成されたOWL/SHACLの後処理: 日本語タグ付けと出力の正準化。

linkml==1.11.1 の gen-owl / gen-shacl には言語タグを付けるCLIオプションが無い
(公式ドキュメントには記載があるが、どのリリース版にも未実装)。設計書§5.7が
求める「日本語の用語定義」を満たすため、生成後にタグを付け直す。

タグを付けるのは定義文(skos:definition / sh:description)だけにする。
rdfs:label はスキーマの要素名(houjinBangou 等のASCII識別子)なので、
日本語として印を付けるのは誤りになる。

**さらに、生成物を入力が同じなら常にバイト単位で同一の出力にする(正準化)。**
gen-owl / gen-shacl は入力(schema/*.yaml)を一切変えずに再実行するだけで
出力が変わる。原因は2つ確認している(いずれもドキュメントではなく実測で
確認済み):

1. ブランクノード(`owl:Restriction` / `sh:property` の各要素)のラベルが
   プロセスごとにランダムであり、`PYTHONHASHSEED` を固定しても変わらない
   (rdflibのBNodeラベル自体がプロセスごとの乱数のため)。
2. `sh:ignoredProperties` のようなRDFリスト(`( a b c )`)は、要素の並び順
   そのものがグラフ構造の一部であり、ブランクノードのラベルを揃えるだけの
   `rdflib.compare.to_canonical_graph` では解決しない。要素の並び順に意味が
   無いリストであることを確認した上で、明示的に辞書順へ正規化する。

これが崩れると、設計書§5.1(生成物をコミットして差分レビューする)と
§11.1(誰の環境でも同じKGが再構築できる)の両方が成立しなくなる。

**リストのソートは許可リスト方式。** `sh:path` の連鎖パスや
`owl:propertyChainAxiom` のように、順序そのものが意味を持つRDFリストが
将来のスキーマ/オーバーレイで現れた場合、機械的にソートすると生成物の意味を
静かに反転させる。しかもその後は決定性が保たれるためテストもCIも検出できない
(公開するオントロジーが間違っているのに、どの装置も鳴らない状態になる)。
これを避けるため、順序に意味が無いと確認済みの述語だけを対象にし、未知の
述語がリストを持っていたらビルドを落とす。未解決の参照を沈黙させずに残す
(設計書§8.2)のと同じ思想である。
"""
import sys
from pathlib import Path

from rdflib import OWL, RDF, BNode, Graph, Literal
from rdflib.collection import Collection
from rdflib.compare import to_canonical_graph
from rdflib.namespace import SH, SKOS

LANG = "ja"
# 日本語の散文が入る述語だけを対象にする
TARGET_PREDICATES = (SKOS.definition, SH.description)

# 順序に意味が無いと確認済みの述語だけをここに登録する。
# sh:path の連鎖パスや owl:propertyChainAxiom は順序そのものが意味を持つので、
# 絶対に追加してはならない。
ORDER_INSENSITIVE_LIST_PREDICATES = {
    OWL.unionOf,
    OWL.intersectionOf,
    OWL.oneOf,
    OWL.withRestrictions,
    SH.ignoredProperties,
    SH["in"],
}


def tag_language(g: Graph, lang: str = LANG) -> int:
    """対象述語の、言語タグも型も持たないリテラルにタグを付ける。件数を返す。"""
    retagged = 0
    for predicate in TARGET_PREDICATES:
        for s, o in list(g.subject_objects(predicate)):
            if not isinstance(o, Literal):
                continue
            if o.language is not None or o.datatype is not None:
                continue
            g.remove((s, predicate, o))
            g.add((s, predicate, Literal(str(o), lang=lang)))
            retagged += 1
    return retagged


def _is_list_head(g: Graph, node: object) -> bool:
    return isinstance(node, BNode) and (node, RDF.first, None) in g


def sort_rdf_lists(g: Graph) -> int:
    """RDFリスト(rdf:first/rdf:restの連鎖)の要素順を辞書順に正規化する。

    `sh:ignoredProperties` のような「ignoredな述語の集合」を表すために
    LinkMLがRDFリストとして出力する箇所は、要素順に意味が無いにもかかわらず、
    リストという表現上、順序がグラフ構造そのものの一部になってしまう。
    `to_canonical_graph` はブランクノードのラベルを正準化するだけで、
    リストの要素順までは正規化しない(実測で確認済み: 要素順が異なる2つの
    リストは、ラベルを揃えても異なるグラフのまま)。ここで先に要素順を
    辞書順に固定してから正準化する。

    **対象は `ORDER_INSENSITIVE_LIST_PREDICATES` に登録された述語だけ。**
    未知の述語がRDFリストを値に持っていたら `ValueError` にする。順序に意味の
    あるリスト(`sh:path` の連鎖パス等)を無条件にソートしないための安全策。

    `rdf:rest` はリストの内部連結であり、それ自体は「リストを値に持つ述語」
    ではないので判定の対象から外す(外さないと、既に許可された先頭ノード
    から続くすべての内部ノードが「未知の述語」として誤検知され、どんな
    リストも処理できなくなる)。
    """
    changed = 0
    for s, p, o in list(g.triples((None, None, None))):
        if p == RDF.rest:
            continue
        if not _is_list_head(g, o):
            continue
        if p not in ORDER_INSENSITIVE_LIST_PREDICATES:
            raise ValueError(
                f"未知の述語 {p} がRDFリストを値に持っている。"
                "順序に意味が無いことを確認できたら"
                " ORDER_INSENSITIVE_LIST_PREDICATES に追加する。"
                " sh:path の連鎖パスや owl:propertyChainAxiom のように順序"
                "そのものが意味を持つ述語なら、絶対に追加してはならない"
                "(機械的にソートすると生成物の意味が静かに反転する)。"
            )
        items = list(Collection(g, o))
        ordered = sorted(items, key=str)
        if items == ordered:
            continue

        # 古いチェーンの rdf:first / rdf:rest を辿って削除する
        node = o
        while node is not None and node != RDF.nil:
            rest = g.value(node, RDF.rest)
            g.remove((node, RDF.first, None))
            g.remove((node, RDF.rest, None))
            node = rest

        g.remove((s, p, o))
        new_head = BNode()
        Collection(g, new_head, ordered)
        g.add((s, p, new_head))
        changed += 1
    return changed


def process(path: Path, lang: str = LANG) -> int:
    """言語タグ付け・リスト順の正規化・ブランクノードの正準化を行い書き戻す。

    タグ付けした件数を返す(呼び出し側のログ用途。既存の戻り値契約を維持する)。
    """
    g = Graph()
    g.parse(path, format="turtle")

    retagged = tag_language(g, lang)
    sort_rdf_lists(g)
    canonical = to_canonical_graph(g)

    canonical.serialize(destination=str(path), format="turtle", encoding="utf-8")
    return retagged


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m jgkg.schema_lang FILE [FILE ...]", file=sys.stderr)
        return 2
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            continue
        count = process(path)
        print(f"tagged {count} literal(s) with @{LANG} in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
