"""グラフ自体についてのPROV-O記述。

出典は名前付きグラフ単位で持つ(設計書§8.4)。RDF-starは使わない。
出典の単位が「ソース×取得日」であり、トリプル単位の注釈はPhase 1では過剰。
"""
import datetime

from rdflib import XSD, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV

from jgkg.sources import get_source

PARSER_VERSION = "0.1.0"


def provenance_graph(
    graph_uri: str,
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
    parser_version: str = PARSER_VERSION,
) -> Graph:
    """指定した名前付きグラフについての記述を返す。

    「どのソースの、いつ取得したファイルから、どのパーサバージョンで生成したか」
    を記録する。
    """
    src = get_source(source_id)
    g = Graph()
    subject = URIRef(graph_uri)

    g.add((subject, PROV.wasDerivedFrom, URIRef(src.url)))
    g.add((subject, PROV.generatedAtTime, Literal(fetched_on, datatype=XSD.date)))
    g.add((subject, DCTERMS.source, Literal(src.name)))
    g.add((subject, DCTERMS.license, URIRef(src.license_url)))
    g.add((subject, DCTERMS.rights, Literal(src.license)))
    g.add((subject, PROV.wasGeneratedBy, Literal(f"jgkg/{parser_version}")))
    if sha256:
        g.add((subject, PROV.value, Literal(f"sha256:{sha256}")))
    return g
