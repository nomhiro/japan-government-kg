"""Pydanticモデル → 名前付きグラフ。

データは「ソース×取得日」の名前付きグラフに入れる。そのグラフについての
PROV-O記述は、置換の単位を揃えるため専用のメタデータグラフに入れる。
"""
import datetime
from collections.abc import Iterable
from pathlib import Path

from rdflib import RDF, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SKOS

from jgkg.config import get_settings
from jgkg.rdf.provenance import provenance_graph
from jgkg.transform.ministry import Ministry, UnmatchedMinistry
from jgkg.transform.organization import Organization
from jgkg.uris import graph_uri


def _ns() -> dict[str, Namespace]:
    base = get_settings().base_uri
    return {
        "core": Namespace(f"{base}/def/core#"),
        "org": Namespace(f"{base}/def/org#"),
    }


class _NSProxy:
    """テストから emit.NS["core"] で参照できるようにする薄いラッパ。"""

    def __getitem__(self, key: str) -> Namespace:
        return _ns()[key]


NS = _NSProxy()


def _metadata_graph_uri() -> str:
    return f"{get_settings().base_uri}/graph/provenance"


def _new_dataset(source_id: str, fetched_on: datetime.date, sha256: str | None) -> tuple[Dataset, Graph]:
    # default_union=True にしないと、rdflib の Dataset は既定でクエリを
    # デフォルトグラフだけに限定する(名前付きグラフを跨いだ ds.objects() 等が
    # 常に空になる)。データもメタデータも名前付きグラフに入れる設計(デフォルト
    # グラフは使わない)なので、これが無いと出典の記述に到達できない
    ds = Dataset(default_union=True)
    gid = graph_uri(source_id, fetched_on)
    data = ds.graph(URIRef(gid))

    meta = ds.graph(URIRef(_metadata_graph_uri()))
    for triple in provenance_graph(gid, source_id, fetched_on, sha256=sha256):
        meta.add(triple)
    return ds, data


def emit_organizations(
    orgs: Iterable[Organization],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
) -> Dataset:
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256)

    for org in orgs:
        s = URIRef(org.uri)
        # 型は「最も具体的なもの1つ」だけを出す。上位型(core:Agent 等)を材質化
        # しないのは、LinkMLの生成SHACLが閉じたシェイプであり、上位クラスが
        # 宣言していないプロパティが違反になるため。上位型はOWLの階層から導ける
        most_specific = "GovernmentOrgan" if org.is_government_organ else "Organization"
        data.add((s, RDF.type, ns["org"][most_specific]))
        data.add((s, SKOS.prefLabel, Literal(org.name, lang="ja")))
        data.add((s, ns["org"]["houjinBangou"], Literal(org.houjin_bangou)))
        data.add((s, ns["org"]["organizationKindCode"], Literal(org.kind_code)))
        if org.prefecture:
            data.add((s, ns["org"]["prefectureName"], Literal(org.prefecture, lang="ja")))
        if org.city:
            data.add((s, ns["org"]["cityName"], Literal(org.city, lang="ja")))
    return ds


def emit_ministries(
    ministries: Iterable[Ministry],
    unmatched: Iterable[UnmatchedMinistry],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
) -> Dataset:
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256)
    base = get_settings().base_uri

    for m in ministries:
        s = URIRef(m.uri)
        data.add((s, RDF.type, ns["org"]["Ministry"]))
        data.add((s, ns["org"]["ministryCode"], Literal(m.ministry_code)))

    for u in unmatched:
        s = URIRef(f"{base}/id/unresolved/ministry/{u.ministry_code}")
        data.add((s, RDF.type, ns["core"]["UnresolvedReference"]))
        data.add((s, ns["core"]["unresolved_text"], Literal(u.name, lang="ja")))
        data.add((s, ns["core"]["unresolved_reason"], Literal(u.reason)))
        # ドメイン固有の org:ministryCode ではなく core の汎用キーに入れる。
        # UnresolvedReference は org: のプロパティを宣言しておらず、閉じたシェイプに
        # 違反するため。CQ P0-5 が core:UnresolvedReference を直接問えるよう
        # サブクラス化はしない(推論なしのFusekiでは上位型が引けない)
        data.add((s, ns["core"]["unresolved_key"], Literal(u.ministry_code)))
    return ds


def write_nquads(ds: Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.serialize(destination=str(path), format="nquads", encoding="utf-8")
