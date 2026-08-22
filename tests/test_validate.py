import datetime
from pathlib import Path

import pytest
from rdflib import RDF, Dataset, Literal, URIRef

from jgkg import validate
from jgkg.rdf import emit
from jgkg.transform.organization import Organization

DAY = datetime.date(2026, 8, 1)
SHAPES = Path("schema/generated")


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _valid_org():
    return Organization(
        uri="http://localhost:8080/kg/id/org/8000012070001",
        houjin_bangou="8000012070001",
        name="厚生労働省",
        kind_code="101",
        is_government_organ=True,
    )


def test_valid_dataset_conforms():
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    results = validate.validate_dataset(ds, SHAPES)

    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [r.report_text for r in data_results if not r.conforms]


def test_malformed_houjin_bangou_fails_validation():
    """法人番号のパターン制約に違反するデータは不合格になること。"""
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    gid = URIRef("http://localhost:8080/kg/graph/houjin-bangou/2026-08-01")
    g = ds.graph(gid)
    bad = URIRef("http://localhost:8080/kg/id/org/9999999999999")
    ns = emit.NS["org"]
    g.add((bad, RDF.type, ns["Organization"]))
    g.add((bad, ns["houjinBangou"], Literal("BROKEN")))

    results = validate.validate_dataset(ds, SHAPES)
    failing = [r for r in results if not r.conforms]
    assert failing, "不正な法人番号が検証を通ってしまった"


def test_quarantine_writes_failing_graphs(tmp_path):
    ds = Dataset()
    gid = URIRef("http://localhost:8080/kg/graph/broken/2026-08-01")
    g = ds.graph(gid)
    ns = emit.NS["org"]
    subj = URIRef("http://localhost:8080/kg/id/org/1")
    g.add((subj, RDF.type, ns["Organization"]))
    g.add((subj, ns["houjinBangou"], Literal("NOPE")))

    results = validate.validate_dataset(ds, SHAPES)
    written = validate.quarantine(ds, results, tmp_path)

    assert written, "隔離ファイルが書かれていない"
    assert any(p.suffix == ".txt" for p in written), "違反内容の報告が書かれていない"


def test_passing_dataset_excludes_failing_graphs():
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    broken_gid = URIRef("http://localhost:8080/kg/graph/broken/2026-08-01")
    bg = ds.graph(broken_gid)
    ns = emit.NS["org"]
    subj = URIRef("http://localhost:8080/kg/id/org/2")
    bg.add((subj, RDF.type, ns["Organization"]))
    bg.add((subj, ns["houjinBangou"], Literal("NOPE")))

    results = validate.validate_dataset(ds, SHAPES)
    clean = validate.passing_dataset(ds, results)

    contexts = {str(c.identifier) for c in clean.contexts() if len(c) > 0}
    assert str(broken_gid) not in contexts, "不合格グラフがロード対象に残っている"
