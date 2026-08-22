"""生成OWLと手書きオーバーレイのマージ。公開オントロジーはこの結果である。"""
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
