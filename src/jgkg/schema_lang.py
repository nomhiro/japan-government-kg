"""生成されたOWL/SHACLの後処理: 日本語タグ付け・出力の正準化・参照制約の抽出。

linkml==1.11.1 の gen-owl / gen-shacl には言語タグを付けるCLIオプションが無い
(公式ドキュメントには記載があるが、どのリリース版にも未実装)。設計書§5.7が
求める「日本語の用語定義」を満たすため、生成後にタグを付け直す。

タグを付けるのは定義文(skos:definition / sh:description)と表示名
(dcterms:title)にする。表示名は仕様§9.2「専門用語を避けた表示名」に
応えるため`schema/*.yaml`のクラス/スロットに`title:`として足すもので
(裁定B78)、定義文と同じく日本語の文字列である。
rdfs:label はスキーマの要素名(houjinBangou 等のASCII識別子)なので、
日本語として印を付けるのは誤りになる。

**`title:` を足すと、実は `dcterms:title` だけでは済まない(実測)。**
`gen-shacl` は同じ表示名を、クラスなら生成される`sh:NodeShape`の
`rdfs:label`に、スロットなら`sh:PropertyShape`の`sh:name`にも書く
(SHACLには`dcterms:title`は一切出ない——出るのは`*.owl.ttl`だけ)。
この2つは**このモジュールでは意図的にタグ付けの対象外のままにする**:
`sh:name`は`title:`が無いスロットには出ないので値そのものは安全に
タグ付けできるが、`rdfs:label`をTARGET_PREDICATESに加えると
`*.owl.ttl`側のASCII識別子(`"BudgetProject"`等)まで日本語として誤タグ
してしまう——このモジュールはファイルの種類(OWLかSHACLか)を見ずに
同じTARGET_PREDICATESを両方に適用するため、`rdfs:label`だけを狙って
タグ付けする手段が無い。したがって`sh:name`/`rdfs:label`(SHACL側)は
日本語の文字列を持つが言語タグは付かない、という非対称が残る
(裁定B78の実装範囲としてはこれで足りる——公開する表示名の正の場所は
`*.owl.ttl`の`dcterms:title`であり、`site/index.html`もそちらを指す)。

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

**裁定B4: 自名前空間のクラスを指す `sh:class` をSHACLから除去し、
`reference-classes.json` に移す。** `sh:class` の制約はグラフを跨ぐ参照の
型を要求するが、`validate.validate_dataset` は名前付きグラフ単位で検証する
(グラフが置換の単位。設計書§6.4)。参照先が別グラフにあるという実運用の
形では `sh:class` は原理的に満たせない(`org:houjinBangou` の必須制約を
グラフ単位のSHACLでは検証できず、CQのSPARQLテストで担保しているのと同じ
理由。R2)。そこで `sh:class` はスキーマ生成時に外し、`(path, expected_class)`
の対を `reference-classes.json` に書き出す。実際の型検査は
`validate.check_reference_integrity` が和集合Datasetに対して行う
(Task 4 裁定B3→B4の経緯)。`sh:nodeKind sh:IRI` は残す — 値がIRIである
ことまではグラフ単位のSHACLで検証できる。
"""
import json
import sys
from pathlib import Path

from rdflib import OWL, RDF, BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.compare import to_canonical_graph
from rdflib.namespace import DCTERMS, SH, SKOS

from jgkg.config import get_settings

LANG = "ja"
# 日本語の文字列が入る述語だけを対象にする(定義文・説明文・表示名)。
# dcterms:title は裁定B78: `schema/*.yaml` の `title:` がここに生成される
# 表示名で、仕様§9.2「専門用語を避けた表示名」に応える。モジュール単位の
# `title:`(例: 「日本政府ナレッジグラフ コアスキーマ」)も同じ述語で出るため
# 同様にタグが付く——これも日本語の文字列であり、対象から除く理由が無い
TARGET_PREDICATES = (SKOS.definition, SH.description, DCTERMS.title)

# 順序に意味が無いと確認済みの述語だけをここに登録する。
# sh:path の連鎖パスや owl:propertyChainAxiom は順序そのものが意味を持つので、
# 絶対に追加してはならない。
#
# owl:members は OWL 2 の n項対称構文(owl:AllDisjointClasses /
# owl:AllDifferent / owl:AllDisjointProperties)専用の述語で、いずれも
# 「このリストの要素は互いに◯◯である」という対称関係を表すだけであり、
# 要素の並び順に意味は無い(仕様上、集合として解釈される)。Task 12(R16)で
# `children_are_mutually_disjoint` を使うと gen-owl がこの形でリストを出す
# (実測: 7クラスがソート済みで並ぶ)。個々の構文ごとに許可するのではなく
# 述語そのものを許可する — 3構文とも同じ理由で順序無意味だから
ORDER_INSENSITIVE_LIST_PREDICATES = {
    OWL.unionOf,
    OWL.intersectionOf,
    OWL.oneOf,
    OWL.withRestrictions,
    OWL.members,
    SH.ignoredProperties,
    SH["in"],
}

# 参照制約(裁定B4)の書き出し先。全モジュールを束ねたSHACLだけが完全な集合を
# 持つ(`all.yaml` が他の全モジュールを import する。この網羅性自体は
# tests/test_schema_consistency.py::test_all_shacl_covers_every_module が
# 別途保証している)ため、このファイル名のときだけ書く。`jgkg.validate` の
# `SHAPES_FILENAME` からではなくここで直接定数にする — validate側から
# import すると schema_lang → validate → schema_lang の循環import になる
# (validate側がこの定数を import する、逆向きだけにする)
AGGREGATE_SHACL_FILENAME = "all.shacl.ttl"
REFERENCE_CLASSES_FILENAME = "reference-classes.json"


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


def extract_reference_classes(g: Graph, base_uri: str) -> list[dict[str, str]]:
    """自名前空間のクラスを指す `sh:class` を `g` から除去し、(path, expected_class) の対で返す。

    裁定B4(モジュールdocstring参照)。**外部語彙のクラスへの `sh:class` は対象外。**
    現時点でこのスキーマに外部クラスへの `sh:class` は無いが、将来 `prov:Agent` 等を
    参照するようになったとき、無条件に全部剥がすと外部語彙相手の検証まで失う。
    自分の名前空間(`{base_uri}/def/`)かどうかで判定する。

    `sh:nodeKind sh:IRI` を含む他のトリプルはそのまま残す(値がIRIであることは
    グラフ単位のSHACLで検証を続ける。剥がすのは`sh:class`だけ)。

    件数ではなく対のリストを返す理由: 呼び出し側(`process`)がファイルをまたいで
    重複を消すため、`{path: expected_class}` の情報自体が要る。
    """
    prefix = f"{base_uri}/def/"
    pairs: set[tuple[str, str]] = set()
    for shape, cls in list(g.subject_objects(SH["class"])):
        if not isinstance(cls, URIRef) or not str(cls).startswith(prefix):
            continue
        path = g.value(shape, SH.path)
        if path is None:
            # sh:path が無い sh:class は想定していない(LinkMLのgen-shaclが
            # 出す形はsh:propertyの中だけ)。黙って無視すると抽出漏れが
            # 静かに残るので、想定外の形に気づけるようにする
            raise ValueError(f"sh:path が無い sh:class が見つかった: {shape}")
        pairs.add((str(path), str(cls)))
        g.remove((shape, SH["class"], cls))
    return [{"path": p, "expected_class": c} for p, c in sorted(pairs)]


def process(path: Path, lang: str = LANG) -> int:
    """言語タグ付け・リスト順の正規化・参照制約の抽出・ブランクノードの正準化を行い書き戻す。

    **`sh:class`の抽出はどの`*.shacl.ttl`にも(素通りする`*.owl.ttl`にも)適用する。**
    OWLには`sh:class`が無いので実質no-op。SHACLの側は、モジュール別ファイル
    (`core.shacl.ttl`等)にも束ねファイル(`all.shacl.ttl`)にも同じ対が現れる
    (`all.yaml`が他モジュールをimportするため)。**`reference-classes.json`を
    書くのは`all.shacl.ttl`のときだけ。** 束ねファイルが全モジュールの対の
    superset であることは`tests/test_schema_consistency.py::
    test_all_shacl_covers_every_module`が別途保証しているので、モジュール別
    ファイルの分だけ何度も書いて集計する必要がない(プロセスをまたいで状態を
    持たない設計を保てる — `scripts/generate-schema.sh`はモジュールごとに
    このスクリプトを別プロセスで呼ぶ)。

    **この関数は`sh:class`の除去について冪等ではない(レビュー指摘5で実測)。**
    既に`sh:class`を除去済みの`all.shacl.ttl`にもう一度`process()`を適用すると、
    2回目は除去対象の`sh:class`が既に無いため`reference-classes.json`が`[]`
    になる。`scripts/generate-schema.sh`は毎回`gen-shacl`の生の出力から
    `process()`を呼ぶため通常はこの非冪等性を踏まないが、生成物1ファイルだけを
    手で流し直すと踏む。この`[]`は「対象が無い」正常状態ではなく二重適用の
    証拠として扱う(`validate._load_reference_classes`が実行時に例外にする。
    裁定B9)。

    タグ付けした件数を返す(呼び出し側のログ用途。既存の戻り値契約を維持する)。
    """
    g = Graph()
    g.parse(path, format="turtle")

    retagged = tag_language(g, lang)
    sort_rdf_lists(g)
    extracted = extract_reference_classes(g, get_settings().base_uri)

    if path.name == AGGREGATE_SHACL_FILENAME:
        ref_path = path.parent / REFERENCE_CLASSES_FILENAME
        ref_path.write_text(
            json.dumps(extracted, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"extracted {len(extracted)} reference class constraint(s) to {ref_path}")

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
