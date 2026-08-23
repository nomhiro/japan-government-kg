"""グラフ自体についてのPROV-O記述。

出典は名前付きグラフ単位で持つ(設計書§8.4)。RDF-starは使わない。
出典の単位が「ソース×取得日」であり、トリプル単位の注釈はPhase 1では過剰。
"""
import datetime
from collections.abc import Iterable

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
    sha256: str | Iterable[str] | None = None,
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

    **複数件も受ける**(Task 7: RSは1つのグラフ(`graph/rs-system/{取得日}`)が
    5本の物理ファイルから作られるため、単一の値では出典を1つしか記録できず
    「4本のうちどれから来たか分からない」という嘘になる)。`core:sourceSha256`
    は budget/law/org 等どのクラスの slots にも加えていない(この関数冒頭の
    モジュールdocstring参照)ため、複数トリプルを1つの主語に付けても閉じた
    シェイプのsh:maxCountに違反しない。**`str` は `Iterable[str]` の一種
    (1文字ずつ反復してしまう)なので、最初に `isinstance` で分岐する** —
    分岐を忘れると `sha256="abc123"` のような単一文字列呼び出しが
    `core:sourceSha256` トリプルを1文字ごとに6件書く、という静かな破損になる。

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
    for h in _as_hash_list(sha256):
        g.add((subject, core.sourceSha256, Literal(h)))
    if recorded_on:
        g.add((subject, core.recordedOn, Literal(recorded_on, datatype=XSD.date)))
    return g


def _as_hash_list(sha256: str | Iterable[str] | None) -> list[str]:
    """`sha256` 引数を正規化する。単一文字列を1文字ずつのリストに壊さない。"""
    if sha256 is None:
        return []
    if isinstance(sha256, str):
        return [sha256] if sha256 else []
    return [h for h in sha256 if h]
