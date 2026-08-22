"""生成されたOWL/SHACLの定義文に日本語の言語タグを付ける後処理。

linkml==1.11.1 の gen-owl / gen-shacl には言語タグを付けるCLIオプションが無い
(公式ドキュメントには記載があるが、どのリリース版にも未実装)。設計書§5.7が
求める「日本語の用語定義」を満たすため、生成後にタグを付け直す。

タグを付けるのは定義文(skos:definition / sh:description)だけにする。
rdfs:label はスキーマの要素名(houjinBangou 等のASCII識別子)なので、
日本語として印を付けるのは誤りになる。
"""
import sys
from pathlib import Path

from rdflib import Graph, Literal
from rdflib.namespace import SH, SKOS

LANG = "ja"
# 日本語の散文が入る述語だけを対象にする
TARGET_PREDICATES = (SKOS.definition, SH.description)


def tag_language(path: Path, lang: str = LANG) -> int:
    """対象述語の、言語タグも型も持たないリテラルにタグを付ける。件数を返す。"""
    g = Graph()
    g.parse(path, format="turtle")

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

    g.serialize(destination=str(path), format="turtle", encoding="utf-8")
    return retagged


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m jgkg.schema_lang FILE [FILE ...]", file=sys.stderr)
        return 2
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            continue
        count = tag_language(path)
        print(f"tagged {count} literal(s) with @{LANG} in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
