"""Phase 1(計画B) CQ1〜CQ10 用の合成データセット構築ヘルパー。

`tests/zenken_rows.py` と同じ位置づけ(pytestに依存しない、素の構築関数の集合)。
`test_competency_questions_phase1.py` がpytestフィクスチャの中からここを呼ぶ。

**実在の値(R45。org/law/budget各yamlのdocstring・task-9-brief.md Interfaces節
「実在の府省令のlaw_id/law_num、実在の府省の法人番号」を満たす)**:

- 厚生労働省(現行府省。houjin_bangou=6000012070001)。
  `tests/fixtures/houjin_bangou_sample.csv`・`tests/zenken_rows.py`・
  P0のCQテスト(`test_cq_p0_01_organization_lookup`)と同じ値。
- KOUSEIROUDOU_LAW_ID/KOUSEIROUDOU_LAW_NUM: 2026-08-24、レイクの実データ
  `data/lake/rs-system/2026-08-23/1-3_RS_2025_基本情報_政策・施策、法令等.zip`
  ([20]法令番号・[21]法令ID)を実際に全走査し、`law.extract_ministry_names`が
  返す名称が現行のdata/reference/ministry-codes.csv(40件)に一致する行を
  検索して見つけた。RS project_id=1953(政策所管府省庁=厚生労働省)が引用する
  組。**実在のRS引用に現れる法令ID・法令番号そのもの**であり、以前のタスク
  (test_transform_law.py等)が使っていた`323M60000100010`は法令番号
  (令和七年厚生労働省令第十号。ブリーフ引用)こそ実在確認済みだが、その
  law_id(e-GovのID)自体は実データでの裏付けが無かった(egov-lawはレイクに
  実データが無く、Task 4がネットワーク無しで構成した値である疑いが残る)。
  今回はlaw_id・law_num・所管府省の組そのものが実データ引用に現れる、
  より強い根拠を持つ値に置き換える。
- OLD_KOUSEISHO_LAW_ID/OLD_KOUSEISHO_LAW_NUM: 同じ走査で見つけた、旧省庁
  (厚生省。2001年の中央省庁再編で廃止、data/reference/old-ministries.csv記載)
  を指す組。RS project_id=1735(政策所管府省庁=厚生労働省。廃止された前身の
  厚生省令を今も根拠法令として引用している)。
- WOLFSTYLE_BANGOU/WOLFSTYLE_NAME: rs_columns.py照合記録・task-7の
  test_rdf_emit.py/test_transform_rs.pyが引用する実在のRS支出先
  (project_id=1、内閣人事局経費)と同じ値。所在地もrs_columns.py引用の実測値
  (東京都中央区築地１丁目９番１１号)をそのまま使う。

**架空の値(R45: 明らかに合成と分かる形式にする)**: budget事業のproject_id
(`999901`〜`999903`。RSの実在project_idは最大5,794件程度で4桁までしか
観測されていないため、6桁・`9999`始まりは実データと衝突しない)。
事業名・法人番号(`1000000000001`/`1000000000002`。tests/test_transform_rs.py
の既存の合成パターンと同型)・改正版(架空。法令(Law)自体は実在するが、
版(LawRevision)の施行日・番号はテスト用に作った)。
"""
import datetime
from pathlib import Path

from rdflib import RDF, XSD, Dataset, Literal, URIRef
from zenken_rows import zipped

from jgkg import lake
from jgkg.connectors import houjin_bangou
from jgkg.rdf import emit
from jgkg.transform import rs
from jgkg.transform.law import JurisdictionResult, LawRecord, Revision, UnresolvedJurisdiction
from jgkg.transform.ministry import Ministry
from jgkg.transform.ministry_succession import AbolishedMinistryRecord
from jgkg.transform.organization import Organization

DAY = datetime.date(2026, 8, 1)

# --- 実在の値(モジュールdocstring参照) -------------------------------------
KOUSEIROUDOU_BANGOU = "6000012070001"
KOUSEIROUDOU_LAW_ID = "417M60000100021"
KOUSEIROUDOU_LAW_NUM = "平成十七年厚生労働省令第二十一号"
# 実データの照合記録に無い(RSは法令の題名・公布日を持たない)。年(平成十七年
# =2005年)だけが法令番号から確定しており、月日は未確認のプレースホルダ
KOUSEIROUDOU_PROMULGATION_DATE = "2005-01-01"

OLD_KOUSEISHO_LAW_ID = "327M50000100010"
OLD_KOUSEISHO_LAW_NUM = "昭和二十七年厚生省令第十号"
OLD_KOUSEISHO_NAME = "厚生省"
# 昭和二十七年=1952年。KOUSEIROUDOU_PROMULGATION_DATEと同じ理由でプレースホルダ
OLD_KOUSEISHO_PROMULGATION_DATE = "1952-01-01"

# C-3(CQ1/CQ11実演用): OLD_KOUSEISHO_NAME(厚生省)が発令した別の省令を、
# 既にAbolishedGovernmentOrganとして解決済みの状態で用意する。
# OLD_KOUSEISHO_LAW_ID自身のJurisdictionResultは変更しない——CQ5/CQ9の
# 既存の正のコントロール(「jurisdictionが未解決(OLD_MINISTRY)でも
# CQ5は答えられる」「CQ9のOLD_MINISTRY分類」)がこれに依存しているため
# (下記jurisdictions辞書参照)。本番のderive_jurisdictionは同一名称に
# 単一の分類しか出さないが、ここは法令ごとに独立したJurisdictionResultを
# 手組みするfixtureであり、「同じ機関名の別の法令では既に解決されている」
# という状態を独立に示せる(NO_CANDIDATE_LAW_IDと同種の、明らかに架空の
# 追加法令。R45)。
SUCCESSION_DEMO_LAW_ID = "998RS0000000001"
SUCCESSION_DEMO_LAW_NUM = "架空厚生省令第一号(CQ11実演用)"
# 412CO0000000315(中央省庁再編に伴う関係法律の整備等に関する法律)自身の
# revision_info.amendment_enforcement_dateから導出される実在の値であり、
# 18機関すべてこの1日付を共有する(tests/test_transform_ministry_succession.py
# 参照。手書きではなくderive_abolition_dateの実測結果をそのまま転記した)
ABOLISHED_KOUSEISHO_ABOLITION_DATE = "2001-01-06"

WOLFSTYLE_BANGOU = "3010001137944"
WOLFSTYLE_NAME = "株式会社ウルフスタイル"

# task-9-review.md指摘5: CQ9の分類境界(unresolved_other)側に正のコントロールが
# 無かった(OLD_MINISTRY側しか無く、クエリのIFを丸ごと定数に置き換えても
# テストがPASSしてしまう)。NO_CANDIDATE(警報。抽出段の誤りを疑うべき)の
# 正のコントロールとして、tests/test_transform_law.pyの既存precedent
# (test_derive_jurisdiction_classifies_non_organ_shaped_name_as_no_candidate)
# と同じ法令番号「ダミー機関規則第一号」を使う。ここでは架空(明らかに合成と
# 分かる形式。R45)なので law_id も"999RS"始まり(同ファイルの既存precedentと
# 同じ接頭辞)にする。実際に`law.derive_jurisdiction`(現行40件+旧18件の
# 実参照表)に通し、NO_CANDIDATEになることを確認済み(検証スクリプトは
# 使い捨てのため未コミット。task-9-report.md参照)
NO_CANDIDATE_LAW_ID = "999RS0000000099"
NO_CANDIDATE_LAW_NUM = "ダミー機関規則第一号"
NO_CANDIDATE_NAME = "ダミー機関"

# --- 架空だが明らかに合成と分かる値 ------------------------------------------
PROJECT_CORE = "999901"  # 厚生労働省・FY2025・basisLaw有・支出3件(解決1/未解決1/束ね1)+sentinel1件
PROJECT_MULTI_YEAR = "999902"  # 厚生労働省・FY2024・WOLFSTYLEへの2件目の支出(CQ3の年度別確認用)
PROJECT_ROLE_DEMO = "999903"  # B20実演用。役割による二重計上を最小構成で示す

ROGUE_REVISION_URI = URIRef(
    "https://jgkg.norr-tech.com/id/law/TEST-ROGUE-REVISION-NO-LAWID"
)
"""law:lawIdを持たない`law:LawRevision`(Task 2レビュー申し送りの正のコントロール)。

`emit_laws`は常に親Lawのlaw_idをコピーするため、この状態は本番コードパスでは
作れない(schemaがminCardinality 0で許容している状態を、意図的に手で作る)。
CQ8がlawIdでの絞り込みを外すと、この版が誤って「最新版」に選ばれる日付
(2026-02-01。KOUSEIROUDOU_LAW_IDの2版の間)にしている。

**Task 11修正ラウンド: 2022-06-01から2026-02-01へ平行移動した。** CQ8の
カットオフを実データ(法令417M60000100021の実際の改正が2026-04-01の1件
しかない)に合わせて2023-01-01→2026-04-01に変えたため、この正のコントロール
一式(KOUSEIROUDOU_LAW_IDの2版・この野良版)も同じカットオフを挟む配置へ
平行移動した(相対的な前後関係は不変)。

**A-3(O9): カットオフを手書きの2026-04-01からKG自身のprovenanceへ変更した。**
このfixtureのegov-lawグラフの`prov:generatedAtTime`は`DAY`
(2026-08-01。下記`_law_records_and_jurisdictions`が`emit_laws`へ渡す
`fetched_on`と、この野良版を注入するグラフURIの両方に使われる)になるため、
「カットオフより後(除外されるべき)」の版の日付を2026-05-01から`DAY`より
後の2026-09-01へ平行移動した(この野良版の日付・相対的な前後関係は不変。
queries/cq/cq08-law-revision-as-of-date.rq参照)。
"""
ROGUE_REVISION_DATE = datetime.date(2026, 2, 1)


def _merge_into(target: Dataset, source: Dataset) -> None:
    """複数の`emit_*`が返す`Dataset`を1つに合流する(test_validate.pyと同じ形)。"""
    for ctx in source.graphs():
        if len(ctx) == 0:
            continue
        g = target.graph(ctx.identifier)
        for triple in ctx:
            g.add(triple)


def _wolfstyle_organization() -> Organization:
    return Organization(
        uri=f"https://jgkg.norr-tech.com/id/org/{WOLFSTYLE_BANGOU}",
        houjin_bangou=WOLFSTYLE_BANGOU,
        name=WOLFSTYLE_NAME,
        kind_code="301",
        prefecture="東京都",
        city="中央区",
        street="築地１丁目９番１１号",
        is_government_organ=False,
    )


def _law_records_and_jurisdictions() -> tuple[list[LawRecord], dict[str, JurisdictionResult]]:
    current = LawRecord(
        law_id=KOUSEIROUDOU_LAW_ID,
        law_num=KOUSEIROUDOU_LAW_NUM,
        law_num_type="MinisterialOrdinance",
        law_type="MinisterialOrdinance",
        law_title="架空の題名(厚生労働省令。RS実データはlaw_id/law_numのみで題名を持たない)",
        abbrev=[],
        promulgation_date=KOUSEIROUDOU_PROMULGATION_DATE,
        repeal_status="None",
        revisions=[
            # 改正2版(ブリーフStep1)。日付以外は架空(RS/e-Govいずれも改正履歴の
            # 実データをこのタスクは持たない)。
            # Task 11修正ラウンド: 2020-04-01/2024-04-01から2026-01-01/
            # 2026-05-01へ平行移動(CQ8のカットオフを実データに合わせて
            # 2026-04-01にしたため)。
            # A-3(O9)修正ラウンド: 2026-05-01から2026-09-01へ再び平行移動
            # (カットオフを手書きの2026-04-01からこのグラフ自身の
            # prov:generatedAtTime=DAY=2026-08-01へ変えたため。この版は
            # 「カットオフ〔=DAY〕より後なので除外される」ことを示す役割
            # なので、DAYより後である必要がある。
            # queries/cq/cq08-law-revision-as-of-date.rq参照)
            Revision(
                amendment_law_num="令和二年厚生労働省令第一号",
                amendment_enforcement_date="2026-01-01",
                revision_status="Enforced",
            ),
            Revision(
                amendment_law_num="令和六年厚生労働省令第一号",
                amendment_enforcement_date="2026-09-01",
                revision_status="Enforced",
            ),
        ],
    )
    old = LawRecord(
        law_id=OLD_KOUSEISHO_LAW_ID,
        law_num=OLD_KOUSEISHO_LAW_NUM,
        law_num_type="MinisterialOrdinance",
        law_type="MinisterialOrdinance",
        law_title="架空の題名(厚生省令)",
        abbrev=[],
        promulgation_date=OLD_KOUSEISHO_PROMULGATION_DATE,
        repeal_status="None",
        revisions=[],
    )
    # task-9-review.md指摘5: unresolved_other(NO_CANDIDATE)側の正のコントロール。
    # 現行(resolved)・旧省庁(OLD_MINISTRY)しか無いと、CQ9のクエリのIFを丸ごと
    # 定数"unresolved_old_or_obsolete_ministry"に置き換えてもテストがPASSして
    # しまう(NO_CANDIDATEという警報が「昔の省庁名だから仕方ない」に化けて
    # 消えることを検出できない)。架空の法令(明らかに合成と分かる形式。R45)
    no_candidate = LawRecord(
        law_id=NO_CANDIDATE_LAW_ID,
        law_num=NO_CANDIDATE_LAW_NUM,
        law_num_type="Rule",
        law_type="Rule",
        law_title="架空の題名(NO_CANDIDATEの正のコントロール)",
        abbrev=[],
        promulgation_date="2020-01-01",
        repeal_status="None",
        revisions=[],
    )
    # C-3(CQ1/CQ11実演用。モジュールdocstring参照): 厚生省発令の別の省令を、
    # 既にAbolishedGovernmentOrganへ解決済みの状態で追加する
    succession_demo = LawRecord(
        law_id=SUCCESSION_DEMO_LAW_ID,
        law_num=SUCCESSION_DEMO_LAW_NUM,
        law_num_type="MinisterialOrdinance",
        law_type="MinisterialOrdinance",
        law_title="架空の題名(CQ11: 廃止機関への解決の正のコントロール)",
        abbrev=[],
        promulgation_date=OLD_KOUSEISHO_PROMULGATION_DATE,
        repeal_status="None",
        revisions=[],
    )
    jurisdictions = {
        KOUSEIROUDOU_LAW_ID: JurisdictionResult(
            law_id=KOUSEIROUDOU_LAW_ID,
            ministry_names=["厚生労働省"],
            resolved=[KOUSEIROUDOU_BANGOU],
            unresolved=[],
        ),
        OLD_KOUSEISHO_LAW_ID: JurisdictionResult(
            law_id=OLD_KOUSEISHO_LAW_ID,
            ministry_names=[OLD_KOUSEISHO_NAME],
            resolved=[],
            unresolved=[
                UnresolvedJurisdiction(name=OLD_KOUSEISHO_NAME, reason="OLD_MINISTRY"),
            ],
        ),
        NO_CANDIDATE_LAW_ID: JurisdictionResult(
            law_id=NO_CANDIDATE_LAW_ID,
            ministry_names=[NO_CANDIDATE_NAME],
            resolved=[],
            unresolved=[
                UnresolvedJurisdiction(name=NO_CANDIDATE_NAME, reason="NO_CANDIDATE"),
            ],
        ),
        # C-3: resolved_abolishedはhoujin_bangouでなく名称のリスト(law.py
        # JurisdictionResultのdocstring参照)。AbolishedGovernmentOrgan自体は
        # build_dataset()がemit_abolished_ministries経由で別途emitする
        SUCCESSION_DEMO_LAW_ID: JurisdictionResult(
            law_id=SUCCESSION_DEMO_LAW_ID,
            ministry_names=[OLD_KOUSEISHO_NAME],
            resolved=[],
            resolved_abolished=[OLD_KOUSEISHO_NAME],
            unresolved=[],
        ),
    }
    return [current, old, no_candidate, succession_demo], jurisdictions


def build_budget_result() -> rs.BuildResult:
    """budget側(3事業・7支出)を本番の`rs.build_projects`経由で組み立てる。

    手組みの`ExpenditureRecord`を直接作らない(advisorレビュー指摘)。センチネル・
    束ね・未解決の分類が実際に本番コードパス(`resolve_recipient`)を通ることを
    CQ6の前提にする — Task 7の`BuildStats`計数とCQ6の4分類が食い違えば、
    どちらかが壊れている証拠になる。
    """
    ministry_ref = {
        "厚生労働省": [
            Ministry(
                uri=f"https://jgkg.norr-tech.com/id/org/{KOUSEIROUDOU_BANGOU}",
                houjin_bangou=KOUSEIROUDOU_BANGOU,
                name="厚生労働省",
            )
        ]
    }
    laws_by_id = {
        OLD_KOUSEISHO_LAW_ID: LawRecord(
            law_id=OLD_KOUSEISHO_LAW_ID,
            law_num=OLD_KOUSEISHO_LAW_NUM,
            law_num_type="MinisterialOrdinance",
            law_type="MinisterialOrdinance",
            law_title="架空の題名(厚生省令)",
            abbrev=[],
            promulgation_date=OLD_KOUSEISHO_PROMULGATION_DATE,
            repeal_status="None",
            revisions=[],
        ),
        # C-3(2026-08-26レビュー指摘1実演): CQ5のOPTIONAL(issuingOrgan→
        # succeededBy)自身のクエリテキストに、正のコントロールを持たせるため。
        # OLD_KOUSEISHO_LAW_ID(上記)はjurisdiction未解決のまま(CQ5/CQ9の
        # 既存の正のコントロールを保つ。モジュールdocstring参照)なので、
        # このOPTIONALは常に不発火のまま——「発火しないこと」しか検査できず、
        # OPTIONAL内部の述語名(succeededBy等)の誤字はどのテストも検出できない
        # (弱いアサートが事実上恒真になる、というC-3裁定4と同型の欠陥)。
        # PROJECT_MULTI_YEARにSUCCESSION_DEMO_LAW_IDを引用させ、CQ5のOPTIONAL
        # が実際に発火してissuingOrgan/successorを束縛することの正のコントロール
        # に使う(下記rows参照)
        SUCCESSION_DEMO_LAW_ID: LawRecord(
            law_id=SUCCESSION_DEMO_LAW_ID,
            law_num=SUCCESSION_DEMO_LAW_NUM,
            law_num_type="MinisterialOrdinance",
            law_type="MinisterialOrdinance",
            law_title="架空の題名(CQ11: 廃止機関への解決の正のコントロール)",
            abbrev=[],
            promulgation_date=OLD_KOUSEISHO_PROMULGATION_DATE,
            repeal_status="None",
            revisions=[],
        ),
    }

    rows = [
        # PROJECT_CORE: 解決1(WOLFSTYLE・実在)/未解決1(NO_CANDIDATE)/束ね1/
        # センチネル1。basisLaw=OLD_KOUSEISHO_LAW_ID(CQ4が「府省→jurisdiction」
        # 経路と「事業→basisLaw」経路を取り違えていないかを分けるための、
        # 意図的に異なる法令。advisorレビュー指摘3)
        rs.RsRow(
            project_id=PROJECT_CORE,
            fiscal_year="2025",
            project_name="(架空)地域医療体制強化推進事業",
            ministry_name="厚生労働省",
            budget_amount=100_000_000,
            basis_law_citations=(
                rs.BasisLawCitation(law_id=OLD_KOUSEISHO_LAW_ID, law_title=None),
            ),
            expenditures=(
                # 実在の金額そのもの(rs_columns.py引用: project_id=1・
                # ブロックA・株式会社ウルフスタイル=3,025,000円)
                rs.ExpenditureLine(
                    recipient_name=WOLFSTYLE_NAME, recipient_houjin_bangou=WOLFSTYLE_BANGOU,
                    is_bundled=False, amount=3_025_000, role="",
                ),
                rs.ExpenditureLine(
                    recipient_name="存在しない株式会社", recipient_houjin_bangou=None,
                    is_bundled=False, amount=500_000, role="",
                ),
                rs.ExpenditureLine(
                    recipient_name="その他", recipient_houjin_bangou=None,
                    is_bundled=True, amount=200_000, role="",
                ),
                rs.ExpenditureLine(
                    recipient_name="個人Ａ", recipient_houjin_bangou="9999999999999",
                    is_bundled=False, amount=100_000, role="",
                ),
            ),
        ),
        # PROJECT_MULTI_YEAR: WOLFSTYLEへの2件目の支出(別事業・別年度)。
        # CQ3「年度別に並べられるか」の正のコントロール(2行以上で初めて
        # 並べる意味が出る)。
        # C-3: SUCCESSION_DEMO_LAW_IDを根拠法令として引用させる(上記
        # laws_by_idのコメント参照。CQ5のOPTIONAL自身の正のコントロール)。
        # CQ2(budgetAmount集計)・CQ3(年度別支出)・CQ6(支出先の解決状況)の
        # いずれもbasisLawを見ないため、この追加による副作用は無い
        rs.RsRow(
            project_id=PROJECT_MULTI_YEAR,
            fiscal_year="2024",
            project_name="(架空)医療従事者確保対策事業",
            ministry_name="厚生労働省",
            budget_amount=50_000_000,
            basis_law_citations=(
                rs.BasisLawCitation(law_id=SUCCESSION_DEMO_LAW_ID, law_title=None),
            ),
            expenditures=(
                rs.ExpenditureLine(
                    recipient_name=WOLFSTYLE_NAME, recipient_houjin_bangou=WOLFSTYLE_BANGOU,
                    is_bundled=False, amount=2_000_000, role="",
                ),
            ),
        ),
        # PROJECT_ROLE_DEMO: B20実演。素朴なΣ(amount_jpy)=2,000,000だが、
        # 「間接補助事業者」ブロックは一次受給者ブロックが受けた同じ資金の
        # 通過金である(task-7-review.md指摘8と同じ構造の最小再現)。
        # 実データでこの2値だけの除外が245事業を解消しないことは別途検証済み
        # (task-9-report.md参照)なので、ここは「roleがqueryableであること」
        # と「素朴なΣが二重計上すること」の実演に用途を絞る
        rs.RsRow(
            project_id=PROJECT_ROLE_DEMO,
            fiscal_year="2025",
            project_name="(架空)役割二重計上デモ事業",
            ministry_name="厚生労働省",
            budget_amount=10_000_000,
            basis_law_citations=(),
            expenditures=(
                rs.ExpenditureLine(
                    recipient_name="デモ一次受給者株式会社", recipient_houjin_bangou="1000000000001",
                    is_bundled=False, amount=1_000_000, role="",
                ),
                rs.ExpenditureLine(
                    recipient_name="デモ間接補助事業者株式会社", recipient_houjin_bangou="1000000000002",
                    is_bundled=False, amount=1_000_000, role="間接補助事業者",
                ),
            ),
        ),
    ]

    return rs.build_projects(rows, ministry_ref, laws_by_id, laws_by_title={})


def build_dataset(out_dir: Path) -> Dataset:
    """org(pipeline.run経由)+ law/budget(emit_*直呼び。Task 11がまだpipeline.py
    に結線していないため)を1つのDatasetに合流する。

    呼び出し側が先に`JGKG_BASE_URI`/`JGKG_LAKE_DIR`/`JGKG_QUARANTINE_DIR`を
    monkeypatchしていること(test_competency_questions.pyのtmp_envと同じ)。
    """
    from jgkg import pipeline

    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_text(encoding="utf-8")
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, zipped(content))
    report = pipeline.run({"houjin-bangou": DAY}, out_dir)
    assert report.graphs_quarantined == 0, "org側のfixtureがSHACL検証で隔離された"

    ds = Dataset(default_union=True)
    ds.parse(out_dir / "kg.nq", format="nquads")

    _merge_into(ds, emit.emit_organizations([_wolfstyle_organization()], "houjin-bangou", DAY))

    records, jurisdictions = _law_records_and_jurisdictions()
    _merge_into(ds, emit.emit_laws(records, jurisdictions, "egov-law", DAY))

    # C-3: SUCCESSION_DEMO_LAW_IDのjurisdictionが指すAbolishedGovernmentOrgan
    # (厚生省)本体。succeededByはKOUSEIROUDOU_BANGOU(厚生労働省。現存)1件のみ
    # ——実データの18件も常に1件だけであり、多値の実演はtest_rdf_emit.py側の
    # 合成データが引き受ける(裁定5)
    _merge_into(
        ds,
        emit.emit_abolished_ministries(
            [
                AbolishedMinistryRecord(
                    name=OLD_KOUSEISHO_NAME,
                    successor_houjin_bangou=[KOUSEIROUDOU_BANGOU],
                    abolition_date=ABOLISHED_KOUSEISHO_ABOLITION_DATE,
                )
            ],
            "egov-law-data",
            DAY,
        ),
    )

    # 正のコントロール: lawIdを持たないLawRevision(Task 2レビュー申し送り)。
    # emit_lawsは常にlawIdを書くため本番コードパスでは作れず、ここで直接注入する
    law_ns = emit.NS["law"]
    egov_graph = ds.graph(URIRef(f"https://jgkg.norr-tech.com/graph/egov-law/{DAY.isoformat()}"))
    egov_graph.add((ROGUE_REVISION_URI, RDF.type, law_ns["LawRevision"]))
    egov_graph.add((
        ROGUE_REVISION_URI, law_ns["amendmentEnforcementDate"],
        Literal(ROGUE_REVISION_DATE, datatype=XSD.date),
    ))
    egov_graph.add((ROGUE_REVISION_URI, law_ns["revisionStatus"], Literal("Enforced")))

    budget_result = build_budget_result()
    _merge_into(
        ds,
        emit.emit_budget(
            budget_result.projects, budget_result.expenditures, budget_result.unresolved,
            "rs-system", DAY,
        ),
    )

    return ds
