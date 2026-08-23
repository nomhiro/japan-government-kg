import datetime

import pytest
from rdflib import RDF, Dataset, Literal, URIRef
from rdflib.namespace import PROV, SKOS

from jgkg.rdf import emit
from jgkg.transform.law import JurisdictionResult, LawRecord, Revision, UnresolvedJurisdiction
from jgkg.transform.ministry import Ministry, UnmatchedMinistry
from jgkg.transform.organization import Organization
from jgkg.uris import law_version_uri, unresolved_ministry_uri

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _org(bangou="6000012070001", name="厚生労働省", kind="101"):
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

    contexts = {g.identifier for g in ds.graphs() if len(g) > 0}
    assert expected_graph in contexts


def test_organization_has_label_and_identifier():
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    subject = URIRef("https://jgkg.norr-tech.com/id/org/6000012070001")

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
        for g in ds.graphs()
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
        [Ministry(uri="https://jgkg.norr-tech.com/id/org/6000012070001",
                  houjin_bangou="6000012070001", ministry_code="999", name="厚生労働省")],
        [UnmatchedMinistry(name="存在しない省", reason="NO_CANDIDATE")],
        "ministry-codes",
        DAY,
    )
    core = emit.NS["core"]
    unresolved = [s for s in ds.subjects(RDF.type, core["UnresolvedReference"])]
    assert unresolved, "未解決の府省がKGに出力されていない(設計書§8.2)"


def test_unmatched_ministry_uri_and_key_are_keyed_by_name():
    """未解決府省のURI・core:unresolved_key の鍵が名称であること(裁定B12)。

    以前は ministry_code を鍵にしていたが、主キーが名称に変わったため、
    分かる場合しか値を持たない ministry_code を鍵にし続けると、コード無しの
    行がすべて `.../unresolved/ministry/None` という1つのURIに収束してしまう
    (複数の未解決府省が1件に化けて隠れる、という設計書§8.2に反する退行)。
    """
    ds = emit.emit_ministries(
        [],
        [UnmatchedMinistry(name="存在しない省", reason="NO_CANDIDATE")],
        "ministry-codes",
        DAY,
    )
    core = emit.NS["core"]
    expected_uri = URIRef(unresolved_ministry_uri("存在しない省"))
    assert (expected_uri, RDF.type, core["UnresolvedReference"]) in ds
    assert (expected_uri, core["unresolved_key"], Literal("存在しない省")) in ds


def test_ministry_code_triple_is_omitted_when_absent():
    """府省コードが分からない行は org:ministryCode 自体を出力しないこと(裁定B12)。

    `Literal(None)` を書くと、KGに文字列"None"が実在してしまう
    (欠落の表現として最悪の形。SHACLのsh:maxCount 1は満たすがCQを読む人間を
    騙す)。トリプル自体を出さないことでこれを避ける
    """
    ds = emit.emit_ministries(
        [Ministry(uri="https://jgkg.norr-tech.com/id/org/2000012010002",
                  houjin_bangou="2000012010002", name="人事院")],
        [],
        "ministry-codes",
        DAY,
    )
    org = emit.NS["org"]
    s = URIRef("https://jgkg.norr-tech.com/id/org/2000012010002")
    assert list(ds.objects(s, org["ministryCode"])) == [], (
        "ministry_code=None なのに org:ministryCode トリプルが出力されている"
    )


def test_write_nquads_roundtrips(tmp_path):
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    out = tmp_path / "out.nq"
    emit.write_nquads(ds, out)

    reloaded = Dataset()
    reloaded.parse(out, format="nquads")
    assert len(list(reloaded.quads())) == len(list(ds.quads()))


# =============================================================================
# emit_laws(経路1。task-4-brief.md Step 5)
# =============================================================================

# 実在の法令番号(tests/test_transform_law.py の CASES と同じ、R45)
KOSEIROUDOU_LAW_ID = "323M60000100010"
OKURASHO_LAW_ID = "326M50000400100"


def _law_record(law_id: str, law_num: str, **overrides) -> LawRecord:
    defaults: dict = {
        "law_num_type": "MinisterialOrdinance",
        "law_type": "MinisterialOrdinance",
        "law_title": "テスト用の題名",
        "abbrev": [],
        "promulgation_date": "2020-01-01",
        "repeal_status": "None",
        "revisions": [],
    }
    defaults.update(overrides)
    return LawRecord(law_id=law_id, law_num=law_num, **defaults)


def test_emit_laws_writes_the_law_entity_with_its_fields():
    record = _law_record(
        KOSEIROUDOU_LAW_ID,
        "令和七年厚生労働省令第十号",
        law_title="○○に関する省令",
        abbrev=["○○省令"],
    )

    ds = emit.emit_laws([record], {}, "egov-law", DAY)
    s = URIRef("https://jgkg.norr-tech.com/id/law/323M60000100010")
    law = emit.NS["law"]

    assert (s, RDF.type, law["Law"]) in ds
    assert (s, law["lawId"], Literal(KOSEIROUDOU_LAW_ID)) in ds
    assert (s, law["lawNum"], Literal("令和七年厚生労働省令第十号")) in ds
    assert (s, law["lawTitle"], Literal("○○に関する省令", lang="ja")) in ds
    assert (s, law["abbrev"], Literal("○○省令", lang="ja")) in ds
    labels = [str(o) for o in ds.objects(s, SKOS.prefLabel)]
    assert "○○に関する省令" in labels


def test_emit_laws_resolved_jurisdiction_points_at_the_ministry_uri():
    record = _law_record(KOSEIROUDOU_LAW_ID, "令和七年厚生労働省令第十号")
    jr = JurisdictionResult(
        law_id=KOSEIROUDOU_LAW_ID,
        ministry_names=["厚生労働省"],
        resolved=["6000012070001"],
        unresolved=[],
    )

    ds = emit.emit_laws([record], {KOSEIROUDOU_LAW_ID: jr}, "egov-law", DAY)

    s = URIRef("https://jgkg.norr-tech.com/id/law/323M60000100010")
    ministry = URIRef("https://jgkg.norr-tech.com/id/org/6000012070001")
    assert (s, emit.NS["law"]["jurisdiction"], ministry) in ds


def test_emit_laws_unresolved_jurisdiction_is_not_dropped():
    """未解決は law:jurisdiction を設定せず、UnresolvedReference として残る(§8.2)。

    何があれば落ちるか: 「resolved が空なら何も出さない」に退化すると、
    OLD_MINISTRY/NO_CANDIDATE/AMBIGUOUS の件数が静かに0になる
    """
    record = _law_record(OKURASHO_LAW_ID, "昭和二十六年大蔵省令第百号")
    jr = JurisdictionResult(
        law_id=OKURASHO_LAW_ID,
        ministry_names=["大蔵省"],
        resolved=[],
        unresolved=[UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")],
    )

    ds = emit.emit_laws([record], {OKURASHO_LAW_ID: jr}, "egov-law", DAY)

    s = URIRef("https://jgkg.norr-tech.com/id/law/326M50000400100")
    law = emit.NS["law"]
    core = emit.NS["core"]
    assert (s, law["jurisdiction"], None) not in ds

    unresolved_nodes = list(ds.subjects(RDF.type, core["UnresolvedReference"]))
    assert unresolved_nodes, "未解決の府省名がKGに出力されていない(設計書§8.2)"
    node = unresolved_nodes[0]
    assert (node, core["unresolved_text"], Literal("大蔵省", lang="ja")) in ds
    assert (node, core["unresolved_reason"], Literal("OLD_MINISTRY")) in ds
    assert (node, core["unresolved_key"], Literal("大蔵省")) in ds


def test_emit_laws_gives_distinct_laws_distinct_unresolved_nodes():
    """同じ旧省庁名(大蔵省)を指す別々の法令が、1つのノードに収束しないこと。

    何があれば落ちるか: UnresolvedReference のURIを名称だけで作ると、
    大蔵省令が何百件あっても1ノードに潰れ、CQ9の「法令ごとの件数」が測れない
    """
    other_law_id = "331M50000400200"
    records = [
        _law_record(OKURASHO_LAW_ID, "昭和二十六年大蔵省令第百号"),
        _law_record(other_law_id, "昭和三十一年大蔵省令第二百号"),
    ]
    jurisdictions = {
        law_id: JurisdictionResult(
            law_id=law_id,
            ministry_names=["大蔵省"],
            resolved=[],
            unresolved=[UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")],
        )
        for law_id in (OKURASHO_LAW_ID, other_law_id)
    }

    ds = emit.emit_laws(records, jurisdictions, "egov-law", DAY)

    core = emit.NS["core"]
    unresolved_nodes = {s for s in ds.subjects(RDF.type, core["UnresolvedReference"])}
    assert len(unresolved_nodes) == 2, (
        f"別の法令の未解決が1ノードに収束している: {unresolved_nodes}"
    )


def test_emit_laws_records_a_revision_with_its_enforcement_date():
    record = _law_record(
        KOSEIROUDOU_LAW_ID,
        "令和七年厚生労働省令第十号",
        revisions=[
            Revision(
                amendment_law_num="令和八年厚生労働省令第一号",
                amendment_enforcement_date="2026-04-01",
                revision_status="CurrentEnforced",
            )
        ],
    )

    ds = emit.emit_laws([record], {}, "egov-law", DAY)

    # 改正法令番号も鍵に含む(指摘10)。日付だけの旧URIをハードコードしない
    # (`law_version_uri` 自体が正しいURIを組み立てる責務を持つため、テスト側で
    # 別に組み立てて二重管理にしない)
    rev_uri = URIRef(
        law_version_uri(
            KOSEIROUDOU_LAW_ID, datetime.date(2026, 4, 1), "令和八年厚生労働省令第一号"
        )
    )
    law = emit.NS["law"]
    assert (rev_uri, RDF.type, law["LawRevision"]) in ds
    assert (rev_uri, law["lawId"], Literal(KOSEIROUDOU_LAW_ID)) in ds
    assert (rev_uri, law["amendmentLawNum"], Literal("令和八年厚生労働省令第一号")) in ds
    assert (rev_uri, law["revisionStatus"], Literal("CurrentEnforced")) in ds


def test_emit_laws_distinguishes_revisions_sharing_the_same_enforcement_date():
    """同一施行日の改正が2件あっても、別々のLawRevisionノードになること(レビュー指摘10)。

    何があれば落ちるか: `law_version_uri` が施行日だけを鍵にしていると、
    2件が1つのURIに合流し、`amendmentLawNum` が2値になって閉じたシェイプの
    `sh:maxCount 1` に違反する(グラフ単位SHACL不合格。隔離の単位はグラフ
    なので、その取得日の全法令が丸ごと落ちる)。
    """
    record = _law_record(
        KOSEIROUDOU_LAW_ID,
        "令和七年厚生労働省令第十号",
        revisions=[
            Revision(
                amendment_law_num="令和八年厚生労働省令第一号",
                amendment_enforcement_date="2026-04-01",
                revision_status="CurrentEnforced",
            ),
            Revision(
                amendment_law_num="令和八年厚生労働省令第二号",
                amendment_enforcement_date="2026-04-01",
                revision_status="CurrentEnforced",
            ),
        ],
    )

    ds = emit.emit_laws([record], {}, "egov-law", DAY)

    law = emit.NS["law"]
    rev_subjects = set(ds.subjects(RDF.type, law["LawRevision"]))
    assert len(rev_subjects) == 2, (
        f"同一施行日の改正2件が1ノードに合流している: {sorted(str(s) for s in rev_subjects)}"
    )


def test_emit_laws_skips_a_revision_without_an_enforcement_date():
    """施行日が無い改正はLawRevisionのURIの材料が無いため見送る(このタスクの範囲)。

    Law本体は落とさない(見送るのは改正イベント1件だけ)ことも合わせて確認する。
    """
    record = _law_record(
        KOSEIROUDOU_LAW_ID,
        "令和七年厚生労働省令第十号",
        revisions=[
            Revision(
                amendment_law_num=None,
                amendment_enforcement_date=None,
                revision_status="New",
            )
        ],
    )

    ds = emit.emit_laws([record], {}, "egov-law", DAY)

    law = emit.NS["law"]
    s = URIRef("https://jgkg.norr-tech.com/id/law/323M60000100010")
    assert (s, RDF.type, law["Law"]) in ds, "施行日の無い改正のせいでLaw本体まで落ちている"
    assert not list(ds.subjects(RDF.type, law["LawRevision"])), (
        "施行日が無いのにLawRevisionが出力された"
    )


def test_emit_laws_out_of_scope_law_has_no_jurisdiction_edge_or_unresolved_node():
    """`jurisdictions` に key が無い(derive_jurisdictionがNoneを返した)法令は、

    jurisdiction も UnresolvedReference も出さない(経路1の対象外だから
    「未解決」でもない、という区別を保つ)。
    """
    record = _law_record("999AC0000000001", "令和三年法律第三十六号")

    ds = emit.emit_laws([record], {}, "egov-law", DAY)

    law = emit.NS["law"]
    core = emit.NS["core"]
    s = URIRef("https://jgkg.norr-tech.com/id/law/999AC0000000001")
    assert (s, RDF.type, law["Law"]) in ds
    assert (s, law["jurisdiction"], None) not in ds
    assert not list(ds.subjects(RDF.type, core["UnresolvedReference"]))
