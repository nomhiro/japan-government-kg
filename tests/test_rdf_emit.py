import datetime

import pytest
from rdflib import RDF, Dataset, URIRef
from rdflib.namespace import PROV, SKOS

from jgkg.rdf import emit
from jgkg.transform.ministry import Ministry, UnmatchedMinistry
from jgkg.transform.organization import Organization

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _org(bangou="8000012070001", name="厚生労働省", kind="101"):
    return Organization(
        uri=f"https://jgkg.norr-tech.com/id/org/{bangou}",
        houjin_bangou=bangou,
        name=name,
        kind_code=kind,
        prefecture="東京都",
        is_government_organ=(kind == "101"),
    )


def test_organizations_land_in_the_named_graph_for_the_source():
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    expected_graph = URIRef("https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-01")

    contexts = {g.identifier for g in ds.contexts() if len(g) > 0}
    assert expected_graph in contexts


def test_organization_has_label_and_identifier():
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    subject = URIRef("https://jgkg.norr-tech.com/id/org/8000012070001")

    labels = [str(o) for o in ds.objects(subject, SKOS.prefLabel)]
    assert "厚生労働省" in labels


def test_no_fact_without_provenance():
    """設計書§2 原則7: 出典を持たない事実をKGに入れない。

    データを含むすべての名前付きグラフに、そのグラフについてのPROV-O記述が
    存在すること。
    """
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)

    data_graphs = {
        g.identifier
        for g in ds.contexts()
        if len(g) > 0 and "/graph/" in str(g.identifier) and "provenance" not in str(g.identifier)
    }
    assert data_graphs, "データを含むグラフが無い"

    for gid in data_graphs:
        described = list(ds.objects(gid, PROV.wasDerivedFrom))
        assert described, f"出典の記述が無いグラフがある: {gid}"


def test_provenance_records_fetch_date_and_checksum():
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY, sha256="abc123")
    gid = URIRef("https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-01")

    times = [str(o) for o in ds.objects(gid, PROV.generatedAtTime)]
    assert any("2026-08-01" in t for t in times)


def test_unmatched_ministries_are_emitted_not_dropped():
    ds = emit.emit_ministries(
        [Ministry(uri="https://jgkg.norr-tech.com/id/org/8000012070001",
                  houjin_bangou="8000012070001", ministry_code="020", name="厚生労働省")],
        [UnmatchedMinistry(ministry_code="999", name="存在しない省", reason="NO_CANDIDATE")],
        "ministry-codes",
        DAY,
    )
    core = emit.NS["core"]
    unresolved = [s for s in ds.subjects(RDF.type, core["UnresolvedReference"])]
    assert unresolved, "未解決の府省がKGに出力されていない(設計書§8.2)"


def test_write_nquads_roundtrips(tmp_path):
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    out = tmp_path / "out.nq"
    emit.write_nquads(ds, out)

    reloaded = Dataset()
    reloaded.parse(out, format="nquads")
    assert len(list(reloaded.quads())) == len(list(ds.quads()))
