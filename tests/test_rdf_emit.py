import datetime

import pytest
from rdflib import RDF, XSD, Dataset, Literal, URIRef
from rdflib.namespace import PROV, SKOS

from jgkg.rdf import emit
from jgkg.transform.law import JurisdictionResult, LawRecord, Revision, UnresolvedJurisdiction
from jgkg.transform.ministry import Ministry, UnmatchedMinistry
from jgkg.transform.ministry_succession import AbolishedMinistryRecord
from jgkg.transform.organization import Organization
from jgkg.uris import abolished_organ_uri, law_version_uri, org_uri, unresolved_ministry_uri

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


# =============================================================================
# emit_abolished_ministries(C-3)
# =============================================================================

FINANCIAL_RECONSTRUCTION_COMMISSION = "金融再生委員会"
FSA_HOUJIN_BANGOU = "5000012060001"


def _abolished_record(name=FINANCIAL_RECONSTRUCTION_COMMISSION, successor_houjin_bangou=None, date="2001-01-06"):
    return AbolishedMinistryRecord(
        name=name,
        successor_houjin_bangou=successor_houjin_bangou or [FSA_HOUJIN_BANGOU],
        abolition_date=date,
    )


def test_abolished_ministry_has_type_label_and_abolition_date():
    ds = emit.emit_abolished_ministries([_abolished_record()], "egov-law-data", DAY)
    org = emit.NS["org"]
    s = URIRef(abolished_organ_uri(FINANCIAL_RECONSTRUCTION_COMMISSION))

    assert (s, RDF.type, org["AbolishedGovernmentOrgan"]) in ds
    assert (s, SKOS.prefLabel, Literal(FINANCIAL_RECONSTRUCTION_COMMISSION, lang="ja")) in ds
    assert (
        s,
        org["abolitionDate"],
        Literal(datetime.date(2001, 1, 6), datatype=XSD.date),
    ) in ds


def test_abolished_ministry_succeeded_by_points_at_the_ministry_uri():
    ds = emit.emit_abolished_ministries([_abolished_record()], "egov-law-data", DAY)
    org = emit.NS["org"]
    s = URIRef(abolished_organ_uri(FINANCIAL_RECONSTRUCTION_COMMISSION))

    assert (s, org["succeededBy"], URIRef(org_uri(FSA_HOUJIN_BANGOU))) in ds


def test_abolished_ministry_succeeded_by_is_multivalued_in_synthetic_data():
    """裁定5: 現データでは18件とも後継が常に1件だけなので、多値の実際の

    行使は合成データでのみ確認できる(意味論としては多値・必須を維持する
    ——機関レベルでは分割の実例が実在するため。C-2報告参照)。
    """
    ds = emit.emit_abolished_ministries(
        [_abolished_record(successor_houjin_bangou=[FSA_HOUJIN_BANGOU, "6000012070001"])],
        "egov-law-data",
        DAY,
    )
    org = emit.NS["org"]
    s = URIRef(abolished_organ_uri(FINANCIAL_RECONSTRUCTION_COMMISSION))

    successors = set(ds.objects(s, org["succeededBy"]))
    assert successors == {URIRef(org_uri(FSA_HOUJIN_BANGOU)), URIRef(org_uri("6000012070001"))}


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


def test_provenance_graph_of_emit_laws_accepts_multiple_sha256():
    """emit_laws経由でも複数sha256を渡せること(provenance_graphの拡張の伝播確認)。"""
    ds = emit.emit_laws([], {}, "egov-law", DAY, sha256=["h1", "h2"])
    core = emit.NS["core"]
    gid = URIRef("https://jgkg.norr-tech.com/graph/egov-law/2026-08-01")
    shas = {str(o) for o in ds.objects(gid, core["sourceSha256"])}
    assert shas == {"h1", "h2"}


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


# =============================================================================
# emit_budget(Task 7 brief Step 5)
# =============================================================================

from pathlib import Path

from jgkg import uris
from jgkg.transform import rs

# 実在のRS project_id/法令ID/法人番号(R45)。project_id=1(内閣人事局経費・
# 内閣官房)/828(消防庁・総務省)。デジタル庁設置法=503AC0000000036、
# 株式会社ウルフスタイル=3010001137944(rs_columns.py照合記録と同じ引用)
NAIKAKUKANBOU_BANGOU = "5000012010023"
DIGITAL_AGENCY_LAW_ID = "503AC0000000036"
WOLFSTYLE_BANGOU = "3010001137944"


def _project(**overrides) -> rs.BudgetProjectRecord:
    defaults = {
        "project_id": "1", "fiscal_year": "2025", "project_name": "内閣人事局経費（研修事業）",
        "ministry_houjin_bangou": NAIKAKUKANBOU_BANGOU, "budget_amount": 34482000,
        "basis_law_ids": (),
    }
    defaults.update(overrides)
    return rs.BudgetProjectRecord(**defaults)


def _expenditure(**overrides) -> rs.ExpenditureRecord:
    defaults = {
        "project_id": "1", "fiscal_year": "2025", "seq": 0,
        "recipient_houjin_bangou": WOLFSTYLE_BANGOU, "amount": 3025000,
        "label": "株式会社ウルフスタイル", "is_bundled": False,
    }
    defaults.update(overrides)
    return rs.ExpenditureRecord(**defaults)


def test_emit_budget_writes_the_project_entity_with_its_fields():
    project = _project()
    ds = emit.emit_budget([project], [], [], "rs-system", DAY)

    s = URIRef(uris.budget_uri("2025", "1"))
    budget = emit.NS["budget"]
    assert (s, RDF.type, budget["BudgetProject"]) in ds
    assert (s, budget["projectId"], Literal("1")) in ds
    assert (s, budget["projectName"], Literal("内閣人事局経費（研修事業）", lang="ja")) in ds
    assert (s, budget["fiscalYear"], Literal(2025)) in ds
    assert (s, budget["budgetAmount"], Literal(34482000)) in ds
    labels = [str(o) for o in ds.objects(s, SKOS.prefLabel)]
    assert "内閣人事局経費（研修事業）" in labels


def test_emit_budget_resolved_ministry_points_at_the_organization_uri():
    project = _project()
    ds = emit.emit_budget([project], [], [], "rs-system", DAY)

    s = URIRef(uris.budget_uri("2025", "1"))
    org = URIRef(f"https://jgkg.norr-tech.com/id/org/{NAIKAKUKANBOU_BANGOU}")
    assert (s, emit.NS["budget"]["ministry"], org) in ds


def test_emit_budget_zero_amount_is_emitted_not_treated_as_absent():
    """'0'(ゼロ予算)は有効な値であり、Noneと同じ扱いで省略してはならない。

    `if amount:` のような真偽値チェックでゼロを弾く実装だと、このテストだけが
    落ちる(rs_columns.pyの「ゼロ予算は有効値」を参照)。
    """
    project = _project(project_id="5551", budget_amount=0)
    ds = emit.emit_budget([project], [], [], "rs-system", DAY)

    s = URIRef(uris.budget_uri("2025", "5551"))
    assert (s, emit.NS["budget"]["budgetAmount"], Literal(0)) in ds


def test_emit_budget_omits_budget_amount_when_missing():
    """budget_amount=None(欠損)は `Literal(None)` を書かず、トリプル自体を出さない

    (裁定B12のministry_codeと同じ「欠落の表現として最悪の形」を避ける作法)。
    """
    project = _project(budget_amount=None)
    ds = emit.emit_budget([project], [], [], "rs-system", DAY)

    s = URIRef(uris.budget_uri("2025", "1"))
    assert list(ds.objects(s, emit.NS["budget"]["budgetAmount"])) == []


def test_emit_budget_unresolved_ministry_is_not_dropped():
    project = _project(ministry_houjin_bangou=None)
    unresolved = [
        rs.UnresolvedBudgetReference(
            kind="ministry", fiscal_year="2025", project_id="1", seq=None,
            key="存在しない省", reason="NO_CANDIDATE",
        )
    ]
    ds = emit.emit_budget([project], [], unresolved, "rs-system", DAY)

    s = URIRef(uris.budget_uri("2025", "1"))
    core = emit.NS["core"]
    assert (s, emit.NS["budget"]["ministry"], None) not in ds
    node = URIRef(uris.unresolved_budget_ministry_uri("2025", "1", "存在しない省"))
    assert (node, RDF.type, core["UnresolvedReference"]) in ds
    assert (node, core["unresolved_text"], Literal("存在しない省", lang="ja")) in ds
    assert (node, core["unresolved_reason"], Literal("NO_CANDIDATE")) in ds
    assert (node, core["unresolved_key"], Literal("存在しない省")) in ds
    assert (node, core["unresolvedFor"], s) in ds


def test_emit_budget_basis_law_points_at_the_law_uri_and_is_multivalued():
    project = _project(basis_law_ids=(DIGITAL_AGENCY_LAW_ID, "322AC0000000120"))
    ds = emit.emit_budget([project], [], [], "rs-system", DAY)

    s = URIRef(uris.budget_uri("2025", "1"))
    budget = emit.NS["budget"]
    edges = set(ds.objects(s, budget["basisLaw"]))
    assert edges == {
        URIRef("https://jgkg.norr-tech.com/id/law/503AC0000000036"),
        URIRef("https://jgkg.norr-tech.com/id/law/322AC0000000120"),
    }


def test_emit_budget_unresolved_basis_law_is_not_dropped():
    project = _project(basis_law_ids=())
    unresolved = [
        rs.UnresolvedBudgetReference(
            kind="basis_law", fiscal_year="2025", project_id="1", seq=None,
            key="存在しない法令", reason="NO_CANDIDATE",
        )
    ]
    ds = emit.emit_budget([project], [], unresolved, "rs-system", DAY)

    core = emit.NS["core"]
    node = URIRef(uris.unresolved_basis_law_uri("2025", "1", "存在しない法令"))
    assert (node, RDF.type, core["UnresolvedReference"]) in ds
    assert (node, core["unresolvedFor"], URIRef(uris.budget_uri("2025", "1"))) in ds


def test_emit_budget_writes_the_expenditure_entity_with_amount_and_label():
    exp = _expenditure()
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)

    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    core = emit.NS["core"]
    budget = emit.NS["budget"]
    assert (s, RDF.type, budget["Expenditure"]) in ds
    assert (s, core["amount_jpy"], Literal(3025000)) in ds
    assert (s, SKOS.prefLabel, Literal("株式会社ウルフスタイル", lang="ja")) in ds
    assert (s, budget["project"], URIRef(uris.budget_uri("2025", "1"))) in ds
    assert (s, budget["fiscalYear"], Literal(2025)) in ds


def test_emit_budget_resolved_recipient_points_at_the_organization_uri():
    exp = _expenditure()
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)

    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    org = URIRef(f"https://jgkg.norr-tech.com/id/org/{WOLFSTYLE_BANGOU}")
    assert (s, emit.NS["budget"]["recipient"], org) in ds


def test_emit_budget_bundled_expenditure_has_no_recipient_edge_and_no_unresolved_node():
    """束ね行(B14)はrecipientを設定せず、かつUnresolvedReferenceも立てない

    (解決を試みていないので「未解決」ではない。§8.2の意図的な非対象)。
    """
    exp = _expenditure(project_id="11", seq=0, recipient_houjin_bangou=None,
                        amount=1379101, label="その他", is_bundled=True)
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)

    s = URIRef(uris.expenditure_uri("2025", "11", 0))
    core = emit.NS["core"]
    budget = emit.NS["budget"]
    assert (s, budget["recipient"], None) not in ds
    assert (s, SKOS.prefLabel, Literal("その他", lang="ja")) in ds
    assert not list(ds.subjects(RDF.type, core["UnresolvedReference"])), (
        "束ね行なのにUnresolvedReferenceが出力されている(解決を試みていないはず)"
    )


def test_emit_budget_sentinel_recipient_has_payee_label_and_no_recipient_edge():
    """センチネル法人番号(B18・task-7-review.md指摘1)の行は`recipient`エッジも

    `UnresolvedReference`も持たず、`payeeLabel`に表示名だけを残す。
    """
    exp = _expenditure(recipient_houjin_bangou=None, payee_label="個人Ａ", label="個人Ａ")
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)

    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    core = emit.NS["core"]
    budget = emit.NS["budget"]
    assert (s, budget["recipient"], None) not in ds
    assert (s, budget["payeeLabel"], Literal("個人Ａ", lang="ja")) in ds
    assert (s, SKOS.prefLabel, Literal("個人Ａ", lang="ja")) in ds
    assert not list(ds.subjects(RDF.type, core["UnresolvedReference"])), (
        "センチネルは照合すべき実体が無いのでUnresolvedReferenceの対象外"
    )


def test_emit_budget_omits_payee_label_when_not_a_sentinel_row():
    """通常解決できた行(payee_label=None)にはpayeeLabelを書かない(重複防止)。"""
    exp = _expenditure()
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)
    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    assert list(ds.objects(s, emit.NS["budget"]["payeeLabel"])) == []


def test_emit_budget_writes_the_role_verbatim_without_a_language_tag():
    """role(B20)はplain(LangStringではない)なので、langタグを付けずに書く。"""
    exp = _expenditure(role="間接補助事業者")
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)

    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    assert (s, emit.NS["budget"]["role"], Literal("間接補助事業者")) in ds


def test_emit_budget_omits_role_when_empty():
    """role=''(ブロックの役割が記録されていない実データが多数ある)は

    トリプル自体を出さない(§8.2「欠損を空文字列で表現しない」)。
    """
    exp = _expenditure()  # role未指定 -> 既定の""
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)
    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    assert list(ds.objects(s, emit.NS["budget"]["role"])) == []


def test_emit_budget_unresolved_recipient_is_not_dropped():
    exp = _expenditure(recipient_houjin_bangou=None, is_bundled=False, label="実在しない架空商事株式会社")
    unresolved = [
        rs.UnresolvedBudgetReference(
            kind="recipient", fiscal_year="2025", project_id="1", seq=0,
            key="実在しない架空商事株式会社", reason="NO_CANDIDATE",
        )
    ]
    ds = emit.emit_budget([], [exp], unresolved, "rs-system", DAY)

    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    core = emit.NS["core"]
    node = URIRef(uris.unresolved_recipient_uri("2025", "1", 0, "実在しない架空商事株式会社"))
    assert (node, RDF.type, core["UnresolvedReference"]) in ds
    assert (node, core["unresolved_reason"], Literal("NO_CANDIDATE")) in ds
    assert (node, core["unresolvedFor"], s) in ds


def test_emit_budget_lands_in_the_rs_system_graph_for_the_fetch_date():
    ds = emit.emit_budget([_project()], [_expenditure()], [], "rs-system", DAY)
    expected_graph = URIRef("https://jgkg.norr-tech.com/graph/rs-system/2026-08-01")
    contexts = {g.identifier for g in ds.graphs() if len(g) > 0}
    assert expected_graph in contexts


def test_emit_budget_records_every_source_files_sha256():
    """RSは1グラフが複数の物理ファイルから作られるため、複数sha256を記録できること

    (Task 1の出典規約。provenance_graphの複数件対応の実際の消費者)。
    """
    ds = emit.emit_budget(
        [_project()], [], [], "rs-system", DAY,
        sha256=["hash-project-summary", "hash-budget-summary", "hash-law", "hash-payee"],
    )
    core = emit.NS["core"]
    shas = {str(o) for o in ds.objects(None, core["sourceSha256"])}
    assert shas == {"hash-project-summary", "hash-budget-summary", "hash-law", "hash-payee"}


def test_emit_budget_conforms_to_shacl():
    """Step 5: 閉じたシェイプで全域が通ることをSHACLで確認する。"""
    from jgkg import validate

    project = _project(basis_law_ids=(DIGITAL_AGENCY_LAW_ID,))
    unresolved = [
        rs.UnresolvedBudgetReference(
            kind="ministry", fiscal_year="2025", project_id="828", seq=None,
            key="存在しない省", reason="NO_CANDIDATE",
        ),
        rs.UnresolvedBudgetReference(
            kind="recipient", fiscal_year="2025", project_id="11", seq=0,
            key="その他", reason="NO_CANDIDATE",
        ),
    ]
    projects = [project, _project(project_id="828", fiscal_year="2025",
                                    ministry_houjin_bangou=None, budget_amount=0)]
    expenditures = [
        _expenditure(role="間接補助事業者"),
        _expenditure(
            project_id="11", seq=0, recipient_houjin_bangou=None, label="その他", is_bundled=True,
        ),
        _expenditure(
            project_id="284", seq=0, recipient_houjin_bangou=None,
            label="個人Ａ", payee_label="個人Ａ",
        ),
    ]
    ds = emit.emit_budget(projects, expenditures, unresolved, "rs-system", DAY, sha256="deadbeef")

    shapes_dir = Path("schema/generated")
    results = validate.validate_dataset(ds, shapes_dir)
    failing = [r for r in results if not r.conforms]
    assert not failing, f"SHACL違反: {[r.report_text for r in failing]}"
