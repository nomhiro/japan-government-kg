"""生成OWLと手書きオーバーレイのマージ。

**公開オントロジーはこの結果ではない(決定44。修正ラウンド1)。** 公開経路
(`src/jgkg/site.py`)は生成OWLのモジュール別ファイルをそのまま配布し、この
関数を呼ばない。呼び出し元は現在テストのみで、オーバーレイがLinkMLで
表現できない公理を将来持つ場合に備えた機構として残っている。使うときは
`merge_ontology` を `site.py` に結線することが公開の条件になる(未結線)。
"""
from pathlib import Path

from rdflib import Graph, URIRef


def merge_ontology(generated: list[Path], overlay: list[Path]) -> Graph:
    """生成OWLにオーバーレイを加算して1つのグラフにする。

    オーバーレイは加算専用なので、単純な和集合で足りる。
    """
    g = Graph()
    for path in generated:
        g.parse(path, format="turtle")
    for path in overlay:
        g.parse(path, format="turtle")
    return g


def overlay_terms(overlay: Path) -> set[str]:
    """オーバーレイが言及するIRIをすべて集める(主語・述語・目的語)。"""
    g = Graph()
    g.parse(overlay, format="turtle")
    terms: set[str] = set()
    for s, p, o in g:
        for node in (s, p, o):
            if isinstance(node, URIRef):
                terms.add(str(node))
    return terms
