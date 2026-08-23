"""グラフ自体についてのPROV-O記述。

出典は名前付きグラフ単位で持つ(設計書§8.4)。RDF-starは使わない。
出典の単位が「ソース×取得日」であり、トリプル単位の注釈はPhase 1では過剰。
"""
import datetime

from rdflib import XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV

from jgkg.config import get_settings
from jgkg.sources import get_source

PARSER_VERSION = "0.1.0"


def _core_ns() -> Namespace:
    # base_uri はテストごとに monkeypatch + get_settings.cache_clear() で変わる
    # (emit._ns() と同じ理由でモジュール定数にしない。base_uri.py 参照)
    return Namespace(f"{get_settings().base_uri}/def/core#")


def provenance_graph(
    graph_uri: str,
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
    recorded_on: datetime.date | None = None,
    parser_version: str = PARSER_VERSION,
) -> Graph:
    """指定した名前付きグラフについての記述を返す。

    「どのソースの、いつ取得したファイルから、どのパーサバージョンで生成したか」
    を記録する。

    `sha256` はレイクの `Snapshot.sha256`(取得してくるソース)、あるいは
    `sources.py` の登録値(参照表)を呼び出し側が渡す。ここでは検証しない
    (実ファイルとの一致は呼び出し側の責務。テストは test_provenance.py で
    レイク/registry の実メタデータと照合する)。

    `recorded_on` は「取得日(`fetched_on` / `prov:generatedAtTime`)」とは別の
    概念で、取得の無いソース(手作りの参照表)だけが渡す(レビューMod①)。
    `fetched_on` の役割はこの追加の前後で変わらない。
    """
    src = get_source(source_id)
    core = _core_ns()
    g = Graph()
    subject = URIRef(graph_uri)

    g.add((subject, PROV.wasDerivedFrom, URIRef(src.url)))
    g.add((subject, PROV.generatedAtTime, Literal(fetched_on, datatype=XSD.date)))
    g.add((subject, DCTERMS.source, Literal(src.name)))
    g.add((subject, DCTERMS.license, URIRef(src.license_url)))
    g.add((subject, DCTERMS.rights, Literal(src.license)))
    g.add((subject, PROV.wasGeneratedBy, Literal(f"jgkg/{parser_version}")))
    if sha256:
        g.add((subject, core.sourceSha256, Literal(sha256)))
    if recorded_on:
        g.add((subject, core.recordedOn, Literal(recorded_on, datatype=XSD.date)))
    return g
