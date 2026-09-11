import datetime
import json
from pathlib import Path

import pytest
from rdflib import RDF, XSD, Dataset, Literal, URIRef
from rdflib.namespace import PROV, SKOS

from jgkg import uris
from jgkg.rdf import emit
from jgkg.transform import ministry_succession as ms
from jgkg.transform import rs
from jgkg.transform.law import JurisdictionResult, LawRecord, Revision, UnresolvedJurisdiction
from jgkg.transform.ministry import Ministry, UnmatchedMinistry, load_reference
from jgkg.transform.ministry_succession import AbolishedMinistryRecord
from jgkg.transform.old_ministries import load_old_ministries
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


# 実データ412CO0000000315(中央省庁再編に伴う関係法律の整備等に関する法律)を
# resolve_old_ministries→resolve_successor_namesまで通した実際の出力
# (2026-08-26、tests/test_transform_ministry_succession.pyの
# test_build_abolished_ministries_from_the_real_18_namesと同じ経路を実行して
# 確認した。数だけでなく18件の値そのものを固定する——団体レベルの解決層は
# 別ファイルで検査済みだが、emitted triplesへの反映はここでしか検査しない)
REAL_18_SUCCESSOR_NAMES = {
    "労働省": "厚生労働省",
    "北海道開発庁": "国土交通省",
    "厚生省": "厚生労働省",
    "国土庁": "国土交通省",
    "大蔵省": "財務省",
    "建設省": "国土交通省",
    "文部省": "文部科学省",
    "沖縄開発庁": "内閣府",
    "環境庁": "環境省",
    "科学技術庁": "文部科学省",
    "経済企画庁": "内閣府",
    "総務庁": "総務省",
    "総理府": "内閣府",
    "自治省": "総務省",
    "通商産業省": "経済産業省",
    "運輸省": "国土交通省",
    "郵政省": "総務省",
    "金融再生委員会": "金融庁",
}


def test_emit_abolished_ministries_covers_all_18_real_names_with_correct_triples():
    """裁定4(2026-08-26レビュー指摘。C-3裁定1の対): 18件のsucceededByを

    「1件以上」のような弱いアサートではなく、18件を個別に列挙して検査する
    ——現データはいずれも後継1件のみで、弱いアサートは事実上恒真になる。

    resolve_old_ministries/resolve_successor_namesの実データ出力
    (test_transform_ministry_succession.py参照。ここで再実行するのは
    build_abolished_ministries以降がemitted triplesへ正しく反映されることを
    確認するため——後継名→houjin_bangouの対応は合成の決定的な写像を使う
    (R45: houjin_bangouの値そのものは検査対象ではない。resolve_successor_names
    の実データ出力とemit_abolished_ministriesの結線が対象)。
    """
    fixtures = Path(__file__).parent / "fixtures"
    data = json.loads(
        (fixtures / "egov_law_data_412CO0000000315.json").read_text(encoding="utf-8")
    )
    extraction = ms.extract_succession_rows(data["law_full_text"], source_law_id="412CO0000000315")
    target_names = load_old_ministries()
    coverage = ms.resolve_old_ministries(extraction.rows, frozenset(target_names))
    reference_names = frozenset(
        r.name for r in load_reference(Path("data/reference/ministry-codes.csv"))
    )
    successors = ms.resolve_successor_names(coverage.resolved, reference_names)
    abolition_date = ms.derive_abolition_date(data["revision_info"])

    distinct_successor_names = sorted({r.successor_name for r in successors.resolved})
    houjin_bangou_by_name = {
        name: f"{i + 1:013d}" for i, name in enumerate(distinct_successor_names)
    }
    records = ms.build_abolished_ministries(successors, houjin_bangou_by_name, abolition_date)
    assert len(records) == 18, "本テストの前提(実データは18件)が崩れている"

    ds = emit.emit_abolished_ministries(records, "egov-law-data", DAY)
    org = emit.NS["org"]

    assert {r.name for r in records} == set(REAL_18_SUCCESSOR_NAMES), (
        "解決された18名称が、このテストが固定する実データの集合と一致しない"
    )
    for old_name, successor_name in REAL_18_SUCCESSOR_NAMES.items():
        s = URIRef(abolished_organ_uri(old_name))
        assert (s, RDF.type, org["AbolishedGovernmentOrgan"]) in ds, old_name
        assert (s, SKOS.prefLabel, Literal(old_name, lang="ja")) in ds, old_name
        assert (
            s, org["abolitionDate"], Literal(datetime.date(2001, 1, 6), datatype=XSD.date),
        ) in ds, old_name
        expected_successor_uri = URIRef(org_uri(houjin_bangou_by_name[successor_name]))
        assert (s, org["succeededBy"], expected_successor_uri) in ds, (
            f"{old_name} の succeededBy が {successor_name} の法人番号を指していない"
        )
        # 裁定5: 現データは後継1件のみ(前段のtest_build_abolished_ministries_
        # from_the_real_18_namesと同じ確認をemitted triples側でも取る)
        assert len(list(ds.objects(s, org["succeededBy"]))) == 1, old_name


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


def test_emit_laws_resolved_abolished_jurisdiction_points_at_the_abolished_organ_not_the_successor():
    """C-3裁定: `resolved_abolished`は当時の組織(AbolishedGovernmentOrgan)

    自身を指すこと。現存の後継(財務省)への読み替えではない
    (「昭和二十六年大蔵省令」の所管は大蔵省)。
    """
    record = _law_record(OKURASHO_LAW_ID, "昭和二十六年大蔵省令第百号")
    jr = JurisdictionResult(
        law_id=OKURASHO_LAW_ID,
        ministry_names=["大蔵省"],
        resolved=[],
        resolved_abolished=["大蔵省"],
        unresolved=[],
    )

    ds = emit.emit_laws([record], {OKURASHO_LAW_ID: jr}, "egov-law", DAY)

    s = URIRef("https://jgkg.norr-tech.com/id/law/326M50000400100")
    abolished = URIRef(abolished_organ_uri("大蔵省"))
    successor = URIRef(org_uri("2000012050002"))  # 財務省(合成)。ここを指してはならない
    assert (s, emit.NS["law"]["jurisdiction"], abolished) in ds
    assert (s, emit.NS["law"]["jurisdiction"], successor) not in ds


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
        # 既定は「解決済み」(recipient_houjin_bangouが実在するWOLFSTYLE_BANGOU)。
        # bundled/sentinel等の呼び出し側はrecipient_match_categoryも
        # 併せて上書きする(D-2裁定。既定値を持たせないrs.ExpenditureRecord
        # と同じ理由で、ここでも「呼び出し側が明示する」形を保つ)
        "recipient_match_category": "resolved",
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
                        amount=1379101, label="その他", is_bundled=True,
                        recipient_match_category="bundled")
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
    exp = _expenditure(recipient_houjin_bangou=None, payee_label="個人Ａ", label="個人Ａ",
                        recipient_match_category="sentinel_or_nonexistent_houjin_bangou")
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
    exp = _expenditure(recipient_houjin_bangou=None, is_bundled=False, label="実在しない架空商事株式会社",
                        recipient_match_category="unresolved")
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
            recipient_match_category="bundled",
        ),
        _expenditure(
            project_id="284", seq=0, recipient_houjin_bangou=None,
            label="個人Ａ", payee_label="個人Ａ",
            recipient_match_category="sentinel_or_nonexistent_houjin_bangou",
        ),
        # 4分類のうち残る「unresolved」もここで一緒にSHACLを通す
        # (部分適用——4分類のうち一部だけをこのテストが確かめる状態を避ける)
        _expenditure(
            project_id="17", seq=0, recipient_houjin_bangou=None,
            label="実在しない架空商事株式会社", recipient_match_category="unresolved",
        ),
    ]
    ds = emit.emit_budget(projects, expenditures, unresolved, "rs-system", DAY, sha256="deadbeef")

    shapes_dir = Path("schema/generated")
    results = validate.validate_dataset(ds, shapes_dir)
    failing = [r for r in results if not r.conforms]
    assert not failing, f"SHACL違反: {[r.report_text for r in failing]}"


def test_emit_budget_writes_the_recipient_match_category_for_all_four_values():
    """D-2裁定: `recipientMatchCategory`が4分類それぞれで正しい値を持つこと。

    何があれば落ちるか: emit_budgetがexp.recipient_match_categoryを無視して
    別の値(例: 常に"resolved")を書いたら、resolved以外の3件がここで落ちる。
    """
    budget = emit.NS["budget"]
    expenditures = [
        _expenditure(seq=0, recipient_match_category="resolved"),
        _expenditure(seq=1, recipient_houjin_bangou=None, is_bundled=True,
                      label="その他", recipient_match_category="bundled"),
        _expenditure(seq=2, recipient_houjin_bangou=None, payee_label="個人Ａ",
                      label="個人Ａ", recipient_match_category="sentinel_or_nonexistent_houjin_bangou"),
        _expenditure(seq=3, recipient_houjin_bangou=None, label="実在しない架空商事株式会社",
                      recipient_match_category="unresolved"),
    ]
    ds = emit.emit_budget([], expenditures, [], "rs-system", DAY)

    for seq, expected in enumerate(
        ["resolved", "bundled", "sentinel_or_nonexistent_houjin_bangou", "unresolved"]
    ):
        s = URIRef(uris.expenditure_uri("2025", "1", seq))
        values = list(ds.objects(s, budget["recipientMatchCategory"]))
        assert values == [Literal(expected)], (seq, expected, values)


def test_emit_budget_missing_recipient_match_category_fails_shacl():
    """壊し確認: `recipientMatchCategory`が必須(minCount 1)であることが

    実際にpyshaclで効くこと。emit_budget自身は無条件に書くので、パイプラインが
    この判定を忘れた場合を再現するため、emit後に該当トリプルを1本だけ手で除く。
    """
    from jgkg import validate

    exp = _expenditure()
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY)
    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    ds.remove((s, emit.NS["budget"]["recipientMatchCategory"], None))

    results = validate.validate_dataset(ds, Path("schema/generated"))
    assert results, "検証対象のグラフが無い"
    # emit_budgetはrs-systemグラフとprovenanceグラフの2本を作るため、
    # 全結果ではなく「1本以上が不合格」を見る(_abolished_organ_dataset系の
    # 単一グラフのテストと違い、`not any(conforms)`は無関係な
    # provenanceグラフの合格1件で常にFalseになってしまう)
    failing = [r for r in results if not r.conforms]
    assert failing, "recipientMatchCategoryを除いたのにSHACLが検出しなかった"


# =============================================================================
# emit_budget: 資金の流れ(支出先ブロック・国自らが支出する間接経費。裁定B97)
#
# 実データ由来の実例(R45): 6494 児童手当等交付金(同額が2ブロック)/
# 1406 独立行政法人国際協力機構有償資金協力部門への出資(出どころ3つ・
# 借入金ブロックは国の支出ではない)
# =============================================================================

JIDOU_TEATE_AMOUNT = 1401293745413


def _block(**overrides) -> rs.ExpenditureBlockRecord:
    defaults = {
        "project_id": "6494", "fiscal_year": "2025", "block_id": "A",
        "block_name": "市町村", "role": "児童手当の支給事務",
        "amount": JIDOU_TEATE_AMOUNT, "payee_count": 1741,
        "paid_by_government": True, "funded_by": (), "flow_notes": (),
    }
    defaults.update(overrides)
    return rs.ExpenditureBlockRecord(**defaults)


def _indirect_cost(**overrides) -> rs.IndirectCostRecord:
    defaults = {
        "project_id": "1", "fiscal_year": "2025", "item": "講師謝金", "amount": 1034000,
    }
    defaults.update(overrides)
    return rs.IndirectCostRecord(**defaults)


def test_emit_budget_writes_the_expenditure_block_with_all_its_fields():
    """ブロックの型・ラベル・blockId・事業・年度・役割・支出先の数・金額が出ること。

    何があれば落ちるか: どのトリプル1本を落としてもここで落ちる。ラベルは
    `core:label`(実際の述語はskos:prefLabel)であり、`budget:blockName`の
    ような独自述語を書くと閉じたシェイプに存在せずSHACLが落とす。
    """
    ds = emit.emit_budget([], [], [], "rs-system", DAY, blocks=[_block()])

    s = URIRef(uris.expenditure_block_uri("2025", "6494", "A"))
    budget = emit.NS["budget"]
    core = emit.NS["core"]
    assert (s, RDF.type, budget["ExpenditureBlock"]) in ds
    assert (s, SKOS.prefLabel, Literal("市町村", lang="ja")) in ds
    assert (s, budget["blockId"], Literal("A")) in ds
    assert (s, budget["project"], URIRef(uris.budget_uri("2025", "6494"))) in ds
    assert (s, budget["fiscalYear"], Literal(2025)) in ds
    assert (s, budget["role"], Literal("児童手当の支給事務")) in ds
    assert (s, budget["payeeCount"], Literal(1741)) in ds
    assert (s, core["amount_jpy"], Literal(JIDOU_TEATE_AMOUNT)) in ds


def test_emit_budget_writes_paid_by_government_even_when_it_is_false():
    """`paidByGovernment`は**偽のときも必ず出る**こと。

    「国が払っていない」は欠損ではなく情報である(借入金・回収金のブロックが
    まさにそれ)。何があれば落ちるか: `if block.paid_by_government:` のような
    真偽値チェックで省略する実装だと、偽のブロックがトリプルを持たず
    「調べていない」と区別できなくなる。
    """
    budget = emit.NS["budget"]
    ds = emit.emit_budget(
        [], [], [], "rs-system", DAY,
        blocks=[
            _block(block_id="A", paid_by_government=True),
            _block(
                project_id="1406", block_id="B", block_name="財政融資資金借入金",
                role="財政融資資金借入金", amount=1033400000000, payee_count=1,
                paid_by_government=False,
            ),
        ],
    )
    entry = URIRef(uris.expenditure_block_uri("2025", "6494", "A"))
    loan = URIRef(uris.expenditure_block_uri("2025", "1406", "B"))
    assert list(ds.objects(entry, budget["paidByGovernment"])) == [Literal(True)]
    assert list(ds.objects(loan, budget["paidByGovernment"])) == [Literal(False)]


def test_emit_budget_funded_by_points_at_other_blocks_of_the_same_project():
    """`fundedBy`が**同じ事業内の別ブロックのURI**を指し、複数値になること。

    JICA型(project_id=1406)のブロックDは A一般会計出資金 / B財政融資資金借入金 /
    C回収金等 の3つから流入する。

    何があれば落ちるか: 張り先を文字列リテラルにする実装(sh:nodeKind sh:IRI
    違反)、別の事業のURIを作る実装(project_idを取り違える)、単値にする実装
    のいずれでも落ちる。
    """
    block_d = _block(
        project_id="1406", block_id="D", block_name="独立行政法人国際協力機構",
        role="有償資金協力業務の実施", amount=1826971152858, payee_count=1,
        paid_by_government=False, funded_by=("A", "B", "C"),
    )
    ds = emit.emit_budget([], [], [], "rs-system", DAY, blocks=[block_d])

    s = URIRef(uris.expenditure_block_uri("2025", "1406", "D"))
    sources = set(ds.objects(s, emit.NS["budget"]["fundedBy"]))
    assert sources == {
        URIRef(uris.expenditure_block_uri("2025", "1406", b)) for b in ("A", "B", "C")
    }
    # 別の事業のブロックURIを指していないこと(鍵の取り違えの検出)
    assert URIRef(uris.expenditure_block_uri("2025", "6494", "A")) not in sources


def test_emit_budget_writes_every_flow_note():
    """`flowNote`が複数値でverbatim(langタグ無し)に出ること。

    何があれば落ちるか: `role`と同じ扱いにせずLangStringにする実装
    (Literal(..., lang='ja'))だと、SHACLのsh:datatype xsd:stringに違反する。
    1つだけ書く実装でも落ちる。
    """
    block = _block(
        project_id="1409", block_id="B", block_name="信用保証協会", role="",
        amount=None, payee_count=None, paid_by_government=False, funded_by=("A",),
        flow_notes=("保険金支払", "代位弁済"),
    )
    ds = emit.emit_budget([], [], [], "rs-system", DAY, blocks=[block])

    s = URIRef(uris.expenditure_block_uri("2025", "1409", "B"))
    notes = set(ds.objects(s, emit.NS["budget"]["flowNote"]))
    assert notes == {Literal("保険金支払"), Literal("代位弁済")}


def test_emit_budget_omits_the_block_amount_and_payee_count_when_missing():
    """5-2にしか現れないブロック(金額・支出先の数がNone)は、その2本を書かないこと。

    何があれば落ちるか: `Literal(None)` を書く実装だと、KGに"None"という
    文字列リテラルが実在してしまう(裁定B12のministry_codeと同じ「欠落の
    表現として最悪の形」)。ブロック自体は落とさないことも同時に見る。
    """
    block = _block(
        project_id="1409", block_id="C", block_name="金融機関", role="",
        amount=None, payee_count=None, paid_by_government=False, funded_by=("B",),
    )
    ds = emit.emit_budget([], [], [], "rs-system", DAY, blocks=[block])

    s = URIRef(uris.expenditure_block_uri("2025", "1409", "C"))
    budget = emit.NS["budget"]
    assert (s, RDF.type, budget["ExpenditureBlock"]) in ds
    assert list(ds.objects(s, emit.NS["core"]["amount_jpy"])) == []
    assert list(ds.objects(s, budget["payeeCount"])) == []
    assert list(ds.objects(s, budget["role"])) == []
    assert (s, SKOS.prefLabel, Literal("金融機関", lang="ja")) in ds


def test_emit_budget_writes_a_zero_block_amount_instead_of_treating_it_as_absent():
    """ブロックの合計支出額0は有効な値であり、Noneと同じ扱いで省略しないこと。

    何があれば落ちるか: `if block.amount:` のような真偽値チェックだと0が消える
    (budgetAmountに同じテストがある。同じ判定形をブロックにも揃える)。
    """
    ds = emit.emit_budget([], [], [], "rs-system", DAY, blocks=[_block(amount=0, payee_count=0)])
    s = URIRef(uris.expenditure_block_uri("2025", "6494", "A"))
    assert (s, emit.NS["core"]["amount_jpy"], Literal(0)) in ds
    assert (s, emit.NS["budget"]["payeeCount"], Literal(0)) in ds


def test_emit_budget_writes_the_indirect_cost_with_its_amount_and_label():
    """国自らが支出する間接経費が型・ラベル・金額・事業・年度を持って出ること。

    **この金額は5-1(支出先_支出情報)に現れない**ので、ExpenditureとBlockだけ
    では取りこぼす(実測2,432件・32,896,230,966円)。何があれば落ちるか:
    このループ自体が無い実装、または項目名をラベルに載せない実装。
    """
    ds = emit.emit_budget([], [], [], "rs-system", DAY, indirect_costs=[_indirect_cost()])

    s = URIRef(uris.indirect_cost_uri("2025", "1", "講師謝金"))
    budget = emit.NS["budget"]
    assert (s, RDF.type, budget["IndirectCost"]) in ds
    assert (s, SKOS.prefLabel, Literal("講師謝金", lang="ja")) in ds
    assert (s, emit.NS["core"]["amount_jpy"], Literal(1034000)) in ds
    assert (s, budget["project"], URIRef(uris.budget_uri("2025", "1"))) in ds
    assert (s, budget["fiscalYear"], Literal(2025)) in ds


def test_emit_budget_writes_in_block_on_the_expenditure():
    """支出が`budget:inBlock`で自分の段を指すこと。

    **これが無いと支出を段の区別なく合計してしまう**(裁定B96で29.9兆円の
    重複として実測した誤りそのもの)。何があれば落ちるか: このトリプルを
    書かない実装、または張り先のブロックURIの鍵を取り違える実装。
    """
    exp = _expenditure(project_id="6494", seq=0, block_id="A")
    ds = emit.emit_budget([], [exp], [], "rs-system", DAY, blocks=[_block()])

    s = URIRef(uris.expenditure_uri("2025", "6494", 0))
    block = URIRef(uris.expenditure_block_uri("2025", "6494", "A"))
    assert (s, emit.NS["budget"]["inBlock"], block) in ds
    assert (block, RDF.type, emit.NS["budget"]["ExpenditureBlock"]) in ds


def test_emit_budget_omits_in_block_when_the_expenditure_has_no_block():
    """`block_id`がNone(5-2を渡していないリリース等)なら`inBlock`を書かないこと。

    何があれば落ちるか: Noneをそのままquoteする実装だと
    `.../block/None` という実在しないURIが出て、参照整合ゲート(裁定B4。
    `budget:inBlock`はreference-classes.jsonに載る)がリリース全体を止める。
    """
    ds = emit.emit_budget([], [_expenditure()], [], "rs-system", DAY)
    s = URIRef(uris.expenditure_uri("2025", "1", 0))
    assert list(ds.objects(s, emit.NS["budget"]["inBlock"])) == []


def _graph_ids(ds: Dataset, pattern) -> set[URIRef]:
    """`pattern`に一致するクアッドが、どの名前付きグラフに入っているかを返す。

    rdflibのバージョンによって`Dataset.quads`の4要素目が`Graph`でも`URIRef`でも
    受けられるようにする(`ds.graphs()`は`Graph`を返すのに対し、`quads`は
    実装依存。既存のテストが`g.identifier`前提で書かれていたため明示する)。
    """
    return {
        getattr(g, "identifier", g) for _s, _p, _o, g in ds.quads(pattern)
    }


def test_emit_budget_puts_blocks_and_indirect_costs_in_the_same_named_graph():
    """ブロック・間接経費が支出と**同じ名前付きグラフ**に入ること。

    同じ一次資料の同じ取得日から作る事実であり、置換の単位も同じ。
    何があれば落ちるか: 別グラフに入れる実装だと、`fundedBy`/`inBlock`が
    グラフを跨ぎ、rs-systemグラフだけを差し替えたときに片方が取り残される。
    """
    expected = URIRef(uris.graph_uri("rs-system", DAY))
    ds = emit.emit_budget(
        [_project(project_id="6494")], [_expenditure(project_id="6494", block_id="A")], [],
        "rs-system", DAY, blocks=[_block()], indirect_costs=[_indirect_cost(project_id="6494")],
    )
    budget = emit.NS["budget"]
    subjects = {
        URIRef(uris.expenditure_block_uri("2025", "6494", "A")),
        URIRef(uris.indirect_cost_uri("2025", "6494", "講師謝金")),
        URIRef(uris.expenditure_uri("2025", "6494", 0)),
    }
    for s in subjects:
        graphs = _graph_ids(ds, (s, RDF.type, None, None))
        assert graphs == {expected}, (s, graphs)
    # inBlockの辺も同じグラフにあること
    assert _graph_ids(
        ds, (URIRef(uris.expenditure_uri("2025", "6494", 0)), budget["inBlock"], None, None)
    ) == {expected}


def test_emit_budget_with_the_money_flow_conforms_to_shacl():
    """ブロック・間接経費・inBlock・fundedBy を含むデータセットがSHACLを通ること。

    何があれば落ちるか: 閉じたシェイプに無い述語を書いた、langタグの有無を
    間違えた、必須(blockId/project/fiscalYear)を落とした、のいずれでも
    不合格になる。**上の個別テストが述語名だけを見ているのに対し、ここは
    スキーマ側の制約(datatype/maxCount/closed)を実際のpyshaclで通す。**
    """
    from jgkg import validate

    projects = [_project(project_id="1406", project_name="独立行政法人国際協力機構有償資金協力部門への出資")]
    blocks = [
        _block(
            project_id="1406", block_id="A", block_name="一般会計出資金",
            role="一般会計出資金", amount=81330000000, payee_count=1,
            paid_by_government=True,
        ),
        _block(
            project_id="1406", block_id="B", block_name="財政融資資金借入金",
            role="財政融資資金借入金", amount=1033400000000, payee_count=1,
            paid_by_government=False,
        ),
        _block(
            project_id="1406", block_id="D", block_name="独立行政法人国際協力機構",
            role="有償資金協力業務の実施", amount=1826971152858, payee_count=1,
            paid_by_government=False, funded_by=("A", "B"),
            flow_notes=("再委託",),
        ),
    ]
    expenditures = [
        _expenditure(
            project_id="1406", seq=0, recipient_houjin_bangou=None, is_bundled=True,
            label="一般会計出資金", amount=81330000000,
            recipient_match_category="bundled", block_id="A",
        )
    ]
    indirect_costs = [_indirect_cost(project_id="1406", item="事務費", amount=12345)]
    ds = emit.emit_budget(
        projects, expenditures, [], "rs-system", DAY, sha256="deadbeef",
        blocks=blocks, indirect_costs=indirect_costs,
    )

    results = validate.validate_dataset(ds, Path("schema/generated"))
    failing = [r for r in results if not r.conforms]
    assert not failing, f"SHACL違反: {[r.report_text for r in failing]}"


def test_emit_budget_a_dangling_in_block_is_caught_by_the_reference_integrity_gate():
    """壊し確認: 存在しないブロックを指す`inBlock`が参照整合ゲートに拾われること。

    `build_projects`が`block_id`を「同じ事業のblocksに実在するものだけ」に
    絞っている理由そのもの(裁定B4)。この絞り込みを外した実装を再現するため、
    ブロックを渡さずに`block_id`付きの支出をemitする。

    何があれば落ちるか: `budget:inBlock`がreference-classes.jsonから外れた
    (=グラフを跨ぐ参照の検査対象から抜けた)場合、違反が0件になってここが落ちる。
    """
    from jgkg import validate

    exp = _expenditure(project_id="6494", seq=0, block_id="A")
    ds = emit.emit_budget([_project(project_id="6494")], [exp], [], "rs-system", DAY)

    violations = validate.check_reference_integrity(ds, Path("schema/generated"))
    paths = {str(v.path) for v in violations}
    assert "https://jgkg.norr-tech.com/def/budget#inBlock" in paths, violations


# =============================================================================
# emit_budget: 年度ごとの予算と執行(裁定B99)
#
# 実データ由来の実例(R45。2026-08-23取得の2-1から引用): project_id=828
# 「危険物事故防止対策の推進」のFY2024(予備費等が-400,000円という負値)と
# FY2025(レビューシート年度。執行額0)
# =============================================================================


def _annual_budget(**overrides) -> rs.AnnualBudgetRecord:
    defaults = {
        "project_id": "828", "fiscal_year": "2025", "budget_fiscal_year": "2024",
        "initial_budget": 97_130_000, "supplementary_budget": 14_194_000,
        "carried_over_from_previous_year": 12_980_000, "reserve_fund": -400_000,
        "total_budget_available": 123_904_000, "executed_amount": 97_738_000,
        "carried_over_to_next_year": 7_594_000, "next_year_request": 109_861_000,
    }
    defaults.update(overrides)
    return rs.AnnualBudgetRecord(**defaults)


def test_emit_budget_writes_the_annual_budget_with_all_eight_amounts():
    """型・事業・2つの年度・8つの金額が出ること(負値も含む)。

    何があれば落ちるか: どのトリプル1本を落としてもここで落ちる。
    `budgetFiscalYear`を`fiscalYear`と同じ値で書く実装(2つの年度の混同)なら
    2024が2025になって落ちる。金額を非負と仮定する実装なら予備費等で落ちる。
    """
    ds = emit.emit_budget([], [], [], "rs-system", DAY, annual_budgets=[_annual_budget()])

    s = URIRef(uris.annual_budget_uri("2025", "828", "2024"))
    budget = emit.NS["budget"]
    assert (s, RDF.type, budget["AnnualBudget"]) in ds
    assert (s, budget["project"], URIRef(uris.budget_uri("2025", "828"))) in ds
    assert (s, budget["fiscalYear"], Literal(2025)) in ds
    assert (s, budget["budgetFiscalYear"], Literal(2024)) in ds
    assert (s, budget["initialBudget"], Literal(97_130_000)) in ds
    assert (s, budget["supplementaryBudget"], Literal(14_194_000)) in ds
    assert (s, budget["carriedOverFromPreviousYear"], Literal(12_980_000)) in ds
    assert (s, budget["reserveFund"], Literal(-400_000)) in ds
    assert (s, budget["totalBudgetAvailable"], Literal(123_904_000)) in ds
    assert (s, budget["executedAmount"], Literal(97_738_000)) in ds
    assert (s, budget["carriedOverToNextYear"], Literal(7_594_000)) in ds
    # 一次データは`'109861000.0'`という小数表記だが、intとして出ること
    # (`Literal(float)`はSHACLの`sh:datatype xsd:integer`に違反する)
    assert (s, budget["nextYearRequest"], Literal(109_861_000)) in ds
    assert list(ds.objects(s, budget["nextYearRequest"])) == [Literal(109_861_000)]


def test_emit_budget_keeps_budget_amount_and_initial_budget_as_different_predicates():
    """BudgetProjectの`budgetAmount`とAnnualBudgetの`initialBudget`が

    **別の述語・別の主語**として出ること(裁定B99)。

    何があれば落ちるか: 同じ列から来るからと1つの述語に統合する実装だと、
    `SUM(?budgetAmount)`が粒度をまたいで二重に数える —— 実データでは
    BudgetProjectが5,794件・AnnualBudgetが23,036件あり、合計が4倍に膨らむ。
    ここでは同じ値(95,667,000円)が2つの主語に別の述語で載り、
    **`budgetAmount`がAnnualBudget側に、`initialBudget`がBudgetProject側に
    出ていないこと**を両方向で縛る。
    """
    project = _project(project_id="828", fiscal_year="2025", budget_amount=95_667_000)
    annual = _annual_budget(
        budget_fiscal_year="2025", initial_budget=95_667_000,
        supplementary_budget=40_150_000, carried_over_from_previous_year=7_594_000,
        reserve_fund=0, total_budget_available=143_411_000, executed_amount=0,
        carried_over_to_next_year=0, next_year_request=136_095_000,
    )
    ds = emit.emit_budget([project], [], [], "rs-system", DAY, annual_budgets=[annual])

    budget = emit.NS["budget"]
    project_uri = URIRef(uris.budget_uri("2025", "828"))
    annual_uri = URIRef(uris.annual_budget_uri("2025", "828", "2025"))
    assert project_uri != annual_uri
    assert list(ds.objects(project_uri, budget["budgetAmount"])) == [Literal(95_667_000)]
    assert list(ds.objects(annual_uri, budget["initialBudget"])) == [Literal(95_667_000)]
    # 述語が入れ替わっていないこと(統合された実装の検出)
    assert list(ds.objects(annual_uri, budget["budgetAmount"])) == []
    assert list(ds.objects(project_uri, budget["initialBudget"])) == []


def test_emit_budget_omits_the_annual_budget_amounts_that_are_missing():
    """欠損している項目の述語を**書かない**こと(記録自体は落とさない)。

    何があれば落ちるか: `Literal(None)`を書く実装だと、KGに"None"という文字列
    リテラルが実在してしまう(裁定B12のministry_codeと同じ最悪の形)。
    欠損を0として書く実装でも落ちる —— 「調べたら0だった」年度
    (レビューシート年度の執行額0。実測5,794事業全件)と区別できなくなる。
    """
    annual = _annual_budget(
        supplementary_budget=None, carried_over_from_previous_year=None,
        reserve_fund=None, total_budget_available=None, carried_over_to_next_year=None,
        next_year_request=None,
    )
    ds = emit.emit_budget([], [], [], "rs-system", DAY, annual_budgets=[annual])

    s = URIRef(uris.annual_budget_uri("2025", "828", "2024"))
    budget = emit.NS["budget"]
    assert (s, RDF.type, budget["AnnualBudget"]) in ds
    assert (s, budget["initialBudget"], Literal(97_130_000)) in ds
    for predicate in (
        "supplementaryBudget", "carriedOverFromPreviousYear", "reserveFund",
        "totalBudgetAvailable", "carriedOverToNextYear", "nextYearRequest",
    ):
        assert list(ds.objects(s, budget[predicate])) == [], predicate


def test_emit_budget_writes_a_zero_executed_amount_instead_of_treating_it_as_absent():
    """執行額0が述語として出ること(欠損と区別する)。

    **実測でレビューシート年度(2025)の執行額は5,794事業すべて0**である。
    何があれば落ちるか: `if annual.executed_amount:`のような真偽値チェックだと
    最新年度の執行額が1本も出ず、「まだ執行されていない」が「調べていない」に
    化ける(budgetAmount・ブロック金額に同じテストがある。判定形を揃える)。
    """
    annual = _annual_budget(
        budget_fiscal_year="2025", initial_budget=0, supplementary_budget=0,
        carried_over_from_previous_year=0, reserve_fund=0, total_budget_available=0,
        executed_amount=0, carried_over_to_next_year=0, next_year_request=0,
    )
    ds = emit.emit_budget([], [], [], "rs-system", DAY, annual_budgets=[annual])

    s = URIRef(uris.annual_budget_uri("2025", "828", "2025"))
    budget = emit.NS["budget"]
    assert (s, budget["executedAmount"], Literal(0)) in ds
    assert (s, budget["initialBudget"], Literal(0)) in ds
    assert (s, budget["totalBudgetAvailable"], Literal(0)) in ds
    # 翌年度要求額0は実測3,838件(集計行23,036件のうち)。端のケースではない
    assert (s, budget["nextYearRequest"], Literal(0)) in ds


def test_emit_budget_gives_the_annual_budget_neither_a_label_nor_a_generic_amount():
    """AnnualBudgetに`skos:prefLabel`と`core:amount_jpy`を付けないこと。

    ラベル: この記録に固有の名前は一次データに無い(`ExpenditureBlock`は
    ブロック名を持つが、こちらは持たない)。「2024年度 危険物事故防止対策の
    推進」のような文字列を合成すると、出典の無い事実をKGに入れる(原則7)。

    `core:amount_jpy`: 名前の付いた金額が8つあるので、そのうち1つを汎用
    スロットに載せると`SUM(?amount_jpy)`の意味がまた変わる
    (`ExpenditureBlock`のdocstringが書いた「3粒度に載る」危険をこれ以上
    広げない。schema/budget.yaml の AnnualBudget 参照)。

    何があれば落ちるか: 親切心でラベルを合成した、あるいは
    `MonetaryItem`を継承しているからと`amount_jpy`にどれか1つを載せた実装。
    """
    ds = emit.emit_budget([], [], [], "rs-system", DAY, annual_budgets=[_annual_budget()])

    s = URIRef(uris.annual_budget_uri("2025", "828", "2024"))
    assert list(ds.objects(s, SKOS.prefLabel)) == []
    assert list(ds.objects(s, emit.NS["core"]["amount_jpy"])) == []


def test_emit_budget_writes_one_annual_budget_per_year_of_the_same_project():
    """同じ事業の5年度分が5つの別ノードになり、それぞれ自分の年度を持つこと。

    何があれば落ちるか: URIが予算年度を鍵にしていない実装だと5件が1ノードに
    潰れ、`initialBudget`が5つ載って閉じたシェイプ(sh:maxCount 1)に違反する。
    """
    history = {
        "2021": (95_000_000, 118_000_000, 99_000_000),
        "2022": (85_000_000, 129_000_000, 77_000_000),
        "2023": (85_394_000, 128_251_000, 96_455_000),
        "2024": (97_130_000, 123_904_000, 97_738_000),
        "2025": (95_667_000, 143_411_000, 0),
    }
    annual_budgets = [
        _annual_budget(
            budget_fiscal_year=year, initial_budget=initial,
            total_budget_available=total, executed_amount=executed,
        )
        for year, (initial, total, executed) in history.items()
    ]
    ds = emit.emit_budget([], [], [], "rs-system", DAY, annual_budgets=annual_budgets)

    budget = emit.NS["budget"]
    subjects = set(ds.subjects(RDF.type, budget["AnnualBudget"]))
    assert len(subjects) == 5
    for year, (initial, _total, _executed) in history.items():
        s = URIRef(uris.annual_budget_uri("2025", "828", year))
        assert list(ds.objects(s, budget["budgetFiscalYear"])) == [Literal(int(year))]
        assert list(ds.objects(s, budget["initialBudget"])) == [Literal(initial)]


def test_emit_budget_puts_annual_budgets_in_the_same_named_graph():
    """AnnualBudgetが事業と**同じ名前付きグラフ**に入ること。

    2-1という同じ一次資料の同じ取得日から作る事実であり、置換の単位も同じ。
    何があれば落ちるか: 別グラフに入れる実装だと`budget:project`がグラフを
    跨ぎ、rs-systemグラフだけを差し替えたときに片方が取り残される。
    """
    expected = URIRef(uris.graph_uri("rs-system", DAY))
    ds = emit.emit_budget(
        [_project(project_id="828")], [], [], "rs-system", DAY,
        annual_budgets=[_annual_budget()],
    )
    s = URIRef(uris.annual_budget_uri("2025", "828", "2024"))
    assert _graph_ids(ds, (s, RDF.type, None, None)) == {expected}
    assert _graph_ids(ds, (s, emit.NS["budget"]["project"], None, None)) == {expected}


def test_emit_budget_with_annual_budgets_conforms_to_shacl():
    """5年度分を含むデータセットがSHACLを通ること。

    何があれば落ちるか: 閉じたシェイプに無い述語を書いた、integerのはずの
    金額にlangタグを付けた、必須(project/fiscalYear/budgetFiscalYear)を
    落としたのいずれでも不合格になる。**上の個別テストが述語名だけを見て
    いるのに対し、ここはスキーマ側の制約(datatype/maxCount/closed)を
    実際のpyshaclで通す。**
    """
    from jgkg import validate

    project = _project(
        project_id="828", project_name="危険物事故防止対策の推進", budget_amount=95_667_000
    )
    annual_budgets = [
        _annual_budget(),
        _annual_budget(
            budget_fiscal_year="2025", initial_budget=95_667_000,
            supplementary_budget=40_150_000, carried_over_from_previous_year=7_594_000,
            reserve_fund=0, total_budget_available=143_411_000, executed_amount=0,
            carried_over_to_next_year=0, next_year_request=136_095_000,
        ),
        # 金額8項目のうち6つが欠損している記録も同じシェイプを通ること
        _annual_budget(
            budget_fiscal_year="2023", supplementary_budget=None,
            carried_over_from_previous_year=None, reserve_fund=None,
            total_budget_available=None, carried_over_to_next_year=None,
            next_year_request=None,
        ),
    ]
    ds = emit.emit_budget(
        [project], [], [], "rs-system", DAY, sha256="deadbeef",
        annual_budgets=annual_budgets,
    )

    results = validate.validate_dataset(ds, Path("schema/generated"))
    failing = [r for r in results if not r.conforms]
    assert not failing, f"SHACL違反: {[r.report_text for r in failing]}"


def test_emit_budget_a_dangling_annual_budget_project_is_caught_by_the_reference_gate():
    """壊し確認: 存在しない事業を指す`budget:project`が参照整合ゲートに拾われること。

    AnnualBudgetは`budget:project`以外にグラフを跨ぐ参照を持たないので、
    **この1本が参照整合ゲート(裁定B4)の検査対象に入っていること**が、
    予算履歴が宙に浮いたまま出荷されないことの唯一の保証である。

    何があれば落ちるか: `budget:project`がreference-classes.jsonから外れた
    場合、違反が0件になってここが落ちる。
    """
    from jgkg import validate

    ds = emit.emit_budget([], [], [], "rs-system", DAY, annual_budgets=[_annual_budget()])

    violations = validate.check_reference_integrity(ds, Path("schema/generated"))
    paths = {str(v.path) for v in violations}
    assert "https://jgkg.norr-tech.com/def/budget#project" in paths, violations
