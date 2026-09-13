"""Phase 1(計画B)CQ1〜CQ10のテスト。設計書§1.2完了条件(A)そのもの
(CQに答えられないオントロジーは不合格)。

fixtureの構築は`tests/phase1_fixture.py`に集約する(値の出典・実在確認の
根拠はそちら側のdocstringを正とする)。ここでは各CQへの応答を確認する。

各テストは正のコントロール(期待件数>0・特定の値)を持つ。否定形のみの
アサートは作らない(レビューI5の教訓)。CQ6・CQ9は「わざと壊す」確認を
task-9-report.mdに別途記録している(変異はコミットしない使い捨てスクリプト
で確認したもの。ここに残す変異はコミットに含めない)。
"""
from pathlib import Path

import phase1_fixture as fx
import pytest
from rdflib import RDF, Dataset, URIRef

from jgkg.rdf import emit

CQ_DIR = Path("queries/cq")
BASE = "https://jgkg.norr-tech.com"


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", BASE)
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def kg(tmp_path) -> Dataset:
    return fx.build_dataset(tmp_path / "out")


@pytest.fixture
def budget_result():
    """SPARQL側の答えをTask 7の`BuildStats`(本番の集計)と照合するための素の結果。"""
    return fx.build_budget_result()


def _query(ds: Dataset, name: str):
    return list(ds.query((CQ_DIR / name).read_text(encoding="utf-8")))


def _uri(kind: str, value: str) -> URIRef:
    return URIRef(f"{BASE}/id/{kind}/{value}")


@pytest.fixture
def kg_with_ministry_marked_as_abolished(kg):
    """cq01のOPTIONAL(succeededByを辿る側)自身の正のコントロール専用。

    通常のkgでは417M60000100021のjurisdiction先(厚生労働省)は常に現存府省
    であり、この分岐は他のどのテストでも一度も発火しない——OPTIONAL内部の
    述語名(org:AbolishedGovernmentOrgan・org:succeededBy)を誤字っても
    test_cq1_jurisdiction_of_ordinanceの負のコントロール(succeededByが
    未束縛)は崩れない(2026-08-26レビュー指摘1と同型。C-3裁定4参照)。

    **厚生労働省が実際に廃止されたという主張ではない**(R45に抵触しない
    合成の注入。P0-6の`kg_without_houjin_bangou`と同じ手法——kgのコピー上に
    テスト専用の型・トリプルを直接注入し、クエリのOPTIONAL構文そのものが
    正しく発火することだけを確認する)。後継の代わりに使う値は
    WOLFSTYLE(既にkgに実在するOrganization)を流用し、新規の組織を
    増やさない。
    """
    org = emit.NS["org"]
    ministry_uri = _uri("org", fx.KOUSEIROUDOU_BANGOU)
    successor_uri = _uri("org", fx.WOLFSTYLE_BANGOU)
    graph = kg.graph(
        URIRef(f"{BASE}/graph/egov-law/{fx.DAY.isoformat()}")
    )
    graph.add((ministry_uri, RDF.type, org["AbolishedGovernmentOrgan"]))
    graph.add((ministry_uri, org["succeededBy"], successor_uri))
    return kg


# =============================================================================
# CQ1: この府省令の所管府省はどこか
# =============================================================================


def test_cq1_jurisdiction_of_ordinance(kg):
    """C-3でsuccessor/successorNameを追加。焼き込んだこの法令は現存府省
    (厚生労働省)を指すため、この2列は常に未束縛のはず(負のコントロール)。
    このOPTIONAL自身が実際に発火することの正のコントロールは
    test_cq1_optional_successor_branch_fires_when_jurisdiction_target_is_abolished
    (直後)が注入データで、CQ11が実データ形の法令で、それぞれ引き受ける。
    """
    rows = _query(kg, "cq01-jurisdiction-of-ordinance.rq")
    assert rows, "CQ1に答えられない"
    assert len(rows) == 1, f"厚生労働省令の所管は1件のはず: {rows}"
    ministry, name, successor, successor_name = rows[0]
    assert ministry == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(name) == "厚生労働省"
    assert successor is None, f"現存府省のはずがsuccessorが束縛された: {successor}"
    assert successor_name is None, (
        f"現存府省のはずがsuccessorNameが束縛された: {successor_name}"
    )


def test_cq1_optional_successor_branch_fires_when_jurisdiction_target_is_abolished(
    kg_with_ministry_marked_as_abolished,
):
    """cq01-jurisdiction-of-ordinance.rq自身のOPTIONAL構文の正のコントロール。

    上のtest_cq1_jurisdiction_of_ordinanceは負のコントロール(発火しない
    こと)しか持たず、OPTIONAL内部の述語名の誤字を検出できない
    (2026-08-26レビュー指摘1。C-3裁定4と同型)。kg_with_ministry_marked_
    as_abolished(このファイル参照)が厚生労働省のURIにテスト専用で注入した
    状態に対し、cq01を実際に流してsuccessor/successorNameが正しく束縛
    されることを確認する。
    """
    rows = _query(kg_with_ministry_marked_as_abolished, "cq01-jurisdiction-of-ordinance.rq")
    assert len(rows) == 1, rows
    _ministry, _name, successor, successor_name = rows[0]
    assert successor == _uri("org", fx.WOLFSTYLE_BANGOU), successor
    assert str(successor_name) == fx.WOLFSTYLE_NAME


# =============================================================================
# CQ2: この府省が所管する予算事業は何か。年度ごとの総額はいくらか
# =============================================================================


def test_cq2_ministry_budget_by_year(kg):
    """厚生労働省の4事業(FY2025×3・FY2024×1)が年度別に正しく集計されること。

    何があれば落ちるか: ministryのURIがずれたら0件になる。年度でGROUP BYせず
    全事業を1本に合計したら年度が2行に分かれず1行になる。budgetAmountの
    代わりにExpenditureを合計する実装に変えたら、B20の役割二重計上
    (PROJECT_ROLE_DEMO)とB97の段の二重計上(PROJECT_FLOW_DEMO)の影響で
    2025年度の総額が狂う —— **このCQがbudgetAmountを読んでいる限り、
    支出側にいくつ重複があっても影響を受けない**ことがここで固定される。
    """
    rows = _query(kg, "cq02-ministry-budget-by-year.rq")
    assert rows, "CQ2に答えられない"
    by_year = {int(y): (int(total), int(count)) for y, total, count in rows}
    assert by_year == {
        # PROJECT_CORE + PROJECT_ROLE_DEMO + PROJECT_FLOW_DEMO(裁定B97で追加)
        2025: (100_000_000 + 10_000_000 + 3_000_000, 3),
        2024: (50_000_000, 1),  # PROJECT_MULTI_YEAR
    }, by_year


# =============================================================================
# CQ3: この法人はどの事業からいくら支出を受けたか。年度別に並べられるか
# =============================================================================


def test_cq3_recipient_expenditures_by_year(kg):
    """株式会社ウルフスタイルへの支出が2事業・2年度にわたって並ぶこと。

    何があれば落ちるか: core:amount_jpyの代わりに存在しないbudget:amountを
    使ったら0件になる。ORDER BY ?yが無いと順序を保証できない。
    """
    rows = _query(kg, "cq03-recipient-expenditures-by-year.rq")
    assert rows, "CQ3に答えられない"
    assert len(rows) == 2, f"2件(FY2024・FY2025)のはず: {rows}"
    years = [int(y) for _, _, y, _ in rows]
    assert years == [2024, 2025], "ORDER BY ?y が年度昇順になっていない"
    amounts = {int(y): int(a) for _, _, y, a in rows}
    assert amounts == {2024: 2_000_000, 2025: 3_025_000}


# =============================================================================
# B20実演(CQではない。10CQの一部ではないため専用の.rqファイルは作らない):
# 素朴なΣ(core:amount_jpy)が事業内で二重計上すること、budget:roleが実際に
# queryableであることを固定する。「消費者のいない記録」(欠陥型4)にしない
# ためのテスト — competency-questions.mdのB20節が主張する2点を検証する
# (advisorレビュー指摘)。
# =============================================================================


def test_b20_naive_sum_double_counts_but_role_is_queryable(kg):
    """PROJECT_ROLE_DEMO(999903)は一次受給者1,000,000円+間接補助事業者
    1,000,000円(同じ資金の通過)を持つ。素朴なΣは2,000,000円に膨らむが、
    budget:roleで「間接補助事業者」を除外すると1,000,000円に戻る。

    何があれば落ちるか: emit_budgetがbudget:roleを書かなくなったら
    (§8.2「欠損を空文字列で表現しない」の実装が変わったら)role_filtered
    がnaiveと同じ2,000,000円になり、このテストが検出する。
    """
    project_uri = URIRef(f"{BASE}/id/budget/2025/{fx.PROJECT_ROLE_DEMO}")

    naive = kg.query(
        """
        PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
        PREFIX core:   <https://jgkg.norr-tech.com/def/core#>
        SELECT (SUM(?a) AS ?total) WHERE {
          ?e budget:project ?p ; core:amount_jpy ?a .
        }
        """,
        initBindings={"p": project_uri},
    )
    assert int(next(iter(naive))[0]) == 2_000_000, "素朴な合計が想定どおり二重計上していない"

    role_filtered = kg.query(
        """
        PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
        PREFIX core:   <https://jgkg.norr-tech.com/def/core#>
        SELECT (SUM(?a) AS ?total) WHERE {
          ?e budget:project ?p ; core:amount_jpy ?a .
          OPTIONAL { ?e budget:role ?r }
          FILTER (!BOUND(?r) || ?r != "間接補助事業者")
        }
        """,
        initBindings={"p": project_uri},
    )
    assert int(next(iter(role_filtered))[0]) == 1_000_000, (
        "budget:roleでの除外がこの最小例では機能していない"
    )


# =============================================================================
# CQ4: ある法人に流れた資金をさかのぼると、どの府省・どの法令に行き着くか
# =============================================================================


def test_cq4_traces_money_via_ministry_jurisdiction_not_basis_law(kg):
    """WOLFSTYLEの資金は厚生労働省→(jurisdiction)厚生労働省令に行き着く。

    fixtureは事業のbasisLaw(旧厚生省令)と府省のjurisdiction(厚生労働省令)を
    意図的に別の法令にしている。CQ4が骨子どおり「府省→jurisdiction」経路を
    辿っていれば厚生労働省令(現行)が返り、誤って「事業→basisLaw」経路
    (旧厚生省令)を辿ったら別の法令IDが返るか、旧省庁令のjurisdictionが
    未解決なため0件になる。どちらでもこのアサートが検出する。
    """
    rows = _query(kg, "cq04-money-trace-to-ministry-and-law.rq")
    assert rows, "CQ4に答えられない"
    assert len(rows) == 1, f"府省1件・法令1件の1組のはず: {rows}"
    ministry, ministry_name, law, _law_title = rows[0]
    assert ministry == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(ministry_name) == "厚生労働省"
    assert law == _uri("law", fx.KOUSEIROUDOU_LAW_ID), (
        f"basisLaw(旧厚生省令)を誤って辿った疑いがある: {law}"
    )


# =============================================================================
# CQ5: ある法令を根拠とする事業を所管する府省はどこか
# =============================================================================


def test_cq5_ministry_of_basis_law(kg):
    """旧厚生省令(basisLaw)を根拠とする事業の所管は厚生労働省(現行)。

    根拠法令自身のjurisdictionが未解決(OLD_MINISTRY)であっても、事業の
    budget:ministryから直接答えられることを確認する(CQ4とは別の軸)。

    C-3でissuingOrgan/issuingOrganName/successor/successorNameを追加。
    OLD_KOUSEISHO_LAW_ID自身のJurisdictionResultは変更していない
    (tests/phase1_fixture.pyのモジュールdocstring参照)ため、この4列は
    引き続きすべて未束縛のはず——「jurisdictionが未解決でもCQ5は答えられる」
    という上のdocstringの主張そのものが、新しい列を追加した後も崩れて
    いないことの負のコントロール。
    """
    rows = _query(kg, "cq05-ministry-of-basis-law.rq")
    assert rows, "CQ5に答えられない"
    matches = [r for r in rows if r[0] == _uri("law", fx.OLD_KOUSEISHO_LAW_ID)]
    assert len(matches) == 1, f"旧厚生省令を根拠とする事業は1件のはず: {matches}"
    _law, project, ministry, ministry_name, issuing_organ, issuing_organ_name, successor, successor_name = matches[0]
    assert project == URIRef(f"{BASE}/id/budget/2025/{fx.PROJECT_CORE}")
    assert ministry == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(ministry_name) == "厚生労働省"
    assert issuing_organ is None, (
        f"OLD_KOUSEISHO_LAW_IDのjurisdictionは未解決のはずがissuingOrganが束縛された: {issuing_organ}"
    )
    assert issuing_organ_name is None
    assert successor is None
    assert successor_name is None


def test_cq5_optional_issuing_organ_and_successor_columns_are_populated(kg):
    """cq05のOPTIONAL(issuingOrgan→succeededBy)自身の正のコントロール。

    上のtest_cq5_ministry_of_basis_lawはOLD_KOUSEISHO_LAW_ID(jurisdiction
    未解決のまま)しか見ないため、この2段のOPTIONAL自体は一度も発火せず、
    OPTIONAL内部の述語名(law:jurisdiction・org:AbolishedGovernmentOrgan・
    org:succeededBy)の誤字をどのテストも検出できない(C-3裁定4と同型の
    「弱いアサートが事実上恒真になる」欠陥。2026-08-26レビュー指摘1)。

    PROJECT_MULTI_YEARがSUCCESSION_DEMO_LAW_ID(厚生省発令・既に
    AbolishedGovernmentOrganへ解決済み)を根拠法令として引用する
    (tests/phase1_fixture.py参照)ため、この行では4列すべてが束縛される。
    """
    rows = _query(kg, "cq05-ministry-of-basis-law.rq")
    matches = [r for r in rows if r[0] == _uri("law", fx.SUCCESSION_DEMO_LAW_ID)]
    assert len(matches) == 1, f"SUCCESSION_DEMO_LAW_IDを根拠とする事業は1件のはず: {matches}"
    _law, project, ministry, ministry_name, issuing_organ, issuing_organ_name, successor, successor_name = matches[0]

    from jgkg.uris import abolished_organ_uri

    assert project == URIRef(f"{BASE}/id/budget/2024/{fx.PROJECT_MULTI_YEAR}")
    assert ministry == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(ministry_name) == "厚生労働省"
    assert issuing_organ == URIRef(abolished_organ_uri(fx.OLD_KOUSEISHO_NAME)), issuing_organ
    assert str(issuing_organ_name) == fx.OLD_KOUSEISHO_NAME
    assert successor == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(successor_name) == "厚生労働省"


# =============================================================================
# CQ6: ある事業の支出先のうち、法人番号が解決できていないものはどれだけあるか
# =============================================================================


def test_cq6_unresolved_recipients_per_project_distinguishes_categories(kg):
    """PROJECT_COREの4支出が resolved/unresolved/bundled/
    sentinel_or_nonexistent_houjin_bangou に正しく1件ずつ分かれること
    (骨子との乖離はcq06のクエリ本体コメントに明記済み)。

    何があれば落ちるか: bundled/sentinel_or_nonexistent_houjin_bangouを
    「未解決」に混ぜたらunresolvedが3になる(過大報告)。
    core:unresolvedForの向きを間違えたらunresolvedが0になる。
    """
    rows = _query(kg, "cq06-unresolved-recipients-per-project.rq")
    assert rows, "CQ6に答えられない"

    project_uri = URIRef(f"{BASE}/id/budget/2025/{fx.PROJECT_CORE}")
    by_category = {
        str(category): int(count) for project, category, count in rows if project == project_uri
    }
    assert by_category == {
        "resolved": 1, "unresolved": 1, "bundled": 1,
        "sentinel_or_nonexistent_houjin_bangou": 1,
    }, by_category


def test_cq6_totals_match_task7_build_stats(kg, budget_result):
    """全事業合計がTask 7のBuildStats(本番の集計)と一致すること。

    CQ6が独自に数えた分類と、rs.build_projectsが返す統計が食い違えば、
    SPARQL側かPython側のどちらかの分類ロジックが壊れている証拠になる
    (advisorレビュー指摘: 「整合の証拠そのもの」)。

    **最終レビュー要修正4(裁定B42)**: `sentinel_or_nonexistent_houjin_bangou`
    はグラフ上区別できない2つのBuildStats欄(recipients_sentinel・
    recipients_nonexistent_houjin_bangou)の**合計**と一致するはず
    ——このテストが「合算である」という設計そのものを固定する
    (この2つを合計せず`recipients_sentinel`だけと比較する実装に戻すと、
    `recipients_nonexistent_houjin_bangou`が1件以上ある入力で合計が
    ずれて落ちる)。
    """
    rows = _query(kg, "cq06-unresolved-recipients-per-project.rq")
    totals: dict[str, int] = {}
    for _project, category, count in rows:
        totals[str(category)] = totals.get(str(category), 0) + int(count)

    stats = budget_result.stats
    resolved_total = stats.recipients_resolved_by_houjin_bangou + stats.recipients_resolved_by_name
    assert totals == {
        "resolved": resolved_total,
        "unresolved": stats.recipients_unresolved,
        "bundled": stats.expenditures_bundled,
        "sentinel_or_nonexistent_houjin_bangou": (
            stats.recipients_sentinel + stats.recipients_nonexistent_houjin_bangou
        ),
    }, (totals, stats)


# =============================================================================
# CQ7: ある関係(エッジ)は、どの一次資料の何日取得分に基づくか(P0-3の一般化)
# =============================================================================


def test_cq7_provenance_of_a_law_jurisdiction_edge(kg):
    """law:jurisdictionというP0-3とは別種のエッジでも出典が辿れること。

    B-S3: 焼き込んだ法令ID(417M60000100021)はfixtureにも実データにも
    存在する値(schema/competency-questions.md参照)。
    """
    rows = _query(kg, "cq07-provenance-of-edge.rq")
    assert rows, "CQ7に答えられない(法令の所管エッジの出典が辿れない)"
    for graph, _source, fetched_on, license_ in rows:
        assert "graph/egov-law/" in str(graph), graph
        assert str(fetched_on).startswith("2026-08-01"), (graph, fetched_on)
        assert str(license_)


# =============================================================================
# CQ8: ある法令の、そのLawRevisionが載っている名前付きグラフのprovenance時点
# (取得時点)における版はどれか
# =============================================================================


def test_cq8_revision_as_of_date_skips_the_rogue_revision_without_law_id(kg):
    """カットオフ(このグラフのprov:generatedAtTime=DAY=2026-08-01)時点の版は
    2026-01-01施行のものであり、lawIdを持たない2026-02-01の野良LawRevision
    (Task 2レビュー申し送りの正のコントロール)も、カットオフより後
    (2026-09-01施行)の版も、誤って選ばれないこと。

    **A-3(O9)修正ラウンド: カットオフを手書きの2026-04-01からこのグラフ自身の
    prov:generatedAtTimeへ変更した**(queries/cq/cq08-law-revision-as-of-date.rq
    参照)。これに伴い「カットオフより後」の版の日付を2026-05-01から
    2026-09-01へ平行移動した(相対的な前後関係は不変。tests/phase1_fixture.py
    参照)。

    **何があれば落ちるか(空虚な検査にしない)**:
    - `rows`が空になる: 完了条件A(0件を作らない)への回帰
    - law:lawIdでの絞り込みが外れる: 日付だけで見て2026-02-01(野良)が
      「カットオフ以下の最新」として誤って選ばれ、`?d`が"2026-02-01"になる
    - 日付フィルタ(`?d <= ?asOf`)が外れる/`ORDER BY DESC LIMIT 1`が
      効かない: カットオフより後のはずの2026-09-01が選ばれる
    どちらの誤答も`?d`の値で判別できるため、非空だけでなく値そのものを見る。
    """
    rows = _query(kg, "cq08-law-revision-as-of-date.rq")
    assert rows, "CQ8に答えられない"
    assert len(rows) == 1, f"1件のはず: {rows}"
    revision, d = rows[0]
    assert str(d) == "2026-01-01", (
        f"カットオフ以下最新の版は2026-01-01のはずが{d}が選ばれた"
        "(野良版が誤って選ばれた、あるいは未来の版がフィルタで除外されていない)"
    )
    assert "417M60000100021" in str(revision), rows


def test_cq8_positive_control_the_rogue_revision_exists_but_is_unrelated(kg):
    """正のコントロールの前提そのもの: 野良LawRevisionは実際にKGに存在し、
    かつ law:lawId を持たないこと(前提が崩れていたら上のテストは空振り)。
    """
    from jgkg.rdf import emit

    law_ns = emit.NS["law"]
    assert (fx.ROGUE_REVISION_URI, law_ns["amendmentEnforcementDate"], None) in kg or any(
        True for _ in kg.objects(fx.ROGUE_REVISION_URI, law_ns["amendmentEnforcementDate"])
    ), "野良LawRevisionがKGに存在しない(fixtureの前提が崩れている)"
    assert list(kg.objects(fx.ROGUE_REVISION_URI, law_ns["lawId"])) == [], (
        "野良LawRevisionがlaw:lawIdを持ってしまっている(正のコントロールとして機能しない)"
    )


# =============================================================================
# CQ9: この府省令は旧省庁名のため未解決か、現存府省に解決済みか
# =============================================================================


def test_cq9_distinguishes_resolved_from_old_ministry_unresolved(kg):
    """解決済み(厚生労働省令)・旧省庁名のため未解決(旧厚生省令)・
    NO_CANDIDATE警報のため未解決(ダミー機関規則。task-9-review.md指摘5)の
    三方に正のコントロールを持つ。

    何があれば落ちるか: OLD_MINISTRY/OBSOLETE_ORGANIZATIONをNO_CANDIDATEと
    区別しなければstatusが常に同じ値になる — 分類のIFを丸ごと定数
    "unresolved_old_or_obsolete_ministry"に置き換えても、旧厚生省令側の
    アサートだけでは検出できない(NO_CANDIDATE_LAW_ID側のアサートが無いと
    このテストはPASSしたままになる。実際に置き換えて確認した結果は
    task-9-report.mdに記録)。core:unresolvedForの向きを間違えたら
    旧厚生省令・ダミー機関規則の行が両方0件になる。
    """
    rows = _query(kg, "cq09-jurisdiction-resolution-status.rq")
    assert rows, "CQ9に答えられない"
    by_law = {str(law): (str(status), str(detail)) for law, status, detail in rows}

    current_law = f"{BASE}/id/law/{fx.KOUSEIROUDOU_LAW_ID}"
    old_law = f"{BASE}/id/law/{fx.OLD_KOUSEISHO_LAW_ID}"
    no_candidate_law = f"{BASE}/id/law/{fx.NO_CANDIDATE_LAW_ID}"
    assert by_law[current_law] == ("resolved", f"{BASE}/id/org/{fx.KOUSEIROUDOU_BANGOU}")
    assert by_law[old_law] == ("unresolved_old_or_obsolete_ministry", "OLD_MINISTRY")
    assert by_law[no_candidate_law] == ("unresolved_other", "NO_CANDIDATE")


# =============================================================================
# CQ10: KGのこのリリースは、各ソースについていつ時点のデータを含むか
# =============================================================================


def test_cq10_release_freshness_covers_all_five_sources(kg):
    """P0-4は2ソースだったが、law/budgetを加えたこのfixtureでは5ソース
    (houjin-bangou・ministry-codes・egov-law・rs-system・egov-law-data)
    すべてが返ること。

    **C-3で4ソースから5ソースに増えた。** egov-law-data(ministry_succession。
    AbolishedGovernmentOrganの元)を追加したため(tests/phase1_fixture.py
    のbuild_dataset参照)。

    何があれば落ちるか: ソースが1つでも欠けたら落ちる。egov-law/rs-system/
    egov-law-dataはrecorded_onを持たないため3つとも「取得日」になるはず
    — 「記録日」に化けたら(ministry-codesの値を誤って流用したら)落ちる。
    """
    from jgkg.sources import get_source

    rows = _query(kg, "cq10-release-freshness.rq")
    assert rows, "CQ10に答えられない"
    by_source = {str(name): str(kind) for name, _asof, kind in rows}

    assert by_source == {
        get_source("houjin-bangou").name: "取得日",
        get_source("ministry-codes").name: "記録日",
        get_source("egov-law").name: "取得日",
        get_source("rs-system").name: "取得日",
        get_source("egov-law-data").name: "取得日",
    }, by_source


# =============================================================================
# CQ11: 発令機関が既に廃止された法令は、現在のどの府省が引き継いだか
# (C-3: 継承そのものを問うCQ。CQ1の姉妹CQ)
# =============================================================================


def test_cq11_succession_of_abolished_ministry(kg):
    """CQ1(この法令の所管はどこか)では持てなかった、廃止済み側の正の
    コントロール。fixtureのSUCCESSION_DEMO_LAW_ID(厚生省発令・既に
    AbolishedGovernmentOrganへ解決済み)が、名称"厚生省"・後継
    "厚生労働省"(KOUSEIROUDOU_BANGOU)として1件だけ返ること。

    何があれば落ちるか: law:jurisdictionの型チェック(a org:AbolishedGovernmentOrgan)
    が外れたら、現存府省を指す2法令(KOUSEIROUDOU_LAW_ID・NO_CANDIDATE_LAW_IDは
    未解決なので混ざらないが、KOUSEIROUDOU_LAW_IDは現存府省を指すため型が
    無いと混ざる)も返ってしまい件数がずれる。OPTIONALのsucceededByホップが
    外れたらsuccessor列が常に未束縛になる。
    """
    rows = _query(kg, "cq11-succession-of-abolished-ministry.rq")
    assert rows, "CQ11に答えられない"
    assert len(rows) == 1, f"廃止機関を指す法令は1件(fixture)のはず: {rows}"
    from jgkg.uris import abolished_organ_uri

    law, organ, organ_name, successor, successor_name = rows[0]
    assert law == _uri("law", fx.SUCCESSION_DEMO_LAW_ID)
    assert organ == URIRef(abolished_organ_uri(fx.OLD_KOUSEISHO_NAME)), organ
    assert str(organ_name) == fx.OLD_KOUSEISHO_NAME
    assert successor == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(successor_name) == "厚生労働省"


def test_cq11_does_not_include_the_still_unresolved_old_ministry_law(kg):
    """OLD_KOUSEISHO_LAW_ID(厚生省発令・jurisdiction未解決のまま)は、
    org:AbolishedGovernmentOrganを指していないためCQ11には現れないこと。

    2つの厚生省発令法令(OLD_KOUSEISHO_LAW_IDとSUCCESSION_DEMO_LAW_ID)を
    意図的に別の解決状態にしているfixtureの前提(tests/phase1_fixture.py
    モジュールdocstring参照)が、CQ11の型フィルタで正しく分かれることの確認。
    """
    rows = _query(kg, "cq11-succession-of-abolished-ministry.rq")
    laws = {str(law) for law, *_ in rows}
    assert str(_uri("law", fx.OLD_KOUSEISHO_LAW_ID)) not in laws, laws


# =============================================================================
# CQ12: 国が自ら支払った額は、年度ごとにいくらか(裁定B97)
# =============================================================================


def test_cq12_government_paid_total_excludes_the_pass_through_stage(kg):
    """入口の段(A)と国自身の間接経費だけが数えられ、**次の段(B)と
    国の支出ではない資金(C)が入らない**こと。

    fixtureのPROJECT_FLOW_DEMOは意図的に3つのブロックを持つ:
      A 1,000,000 国が支払った(入口)
      B 1,000,000 Aが出どころ・入口ではない(= Aと同じお金の2段目)
      C   500,000 出どころも無く入口でもない(借入金型。国の支出ではない)
    加えて間接経費 7,000。**素朴なΣ(amount_jpy)は 2,507,000 になる。**

    何があれば落ちるか:
    - `budget:paidByGovernment true` のフィルタが外れたら B と C が入って
      2,507,000 になる
    - UNIONのIndirectCost側が落ちたら 1,000,000 になり、
      **5-1に現れない支出を取りこぼす**(裁定B97が実データで32,896,230,966円と
      実測した分がまるごと消える類の欠陥)
    - 「流入辺が無いものを入口とする」という素朴な規則に実装を変えたら、
      C(出どころが無い)が入って 1,507,000 になる
    - 年度でGROUP BYしなくなったら、FY2024の事業と混ざって1行になる
    """
    rows = _query(kg, "cq12-government-paid-total.rq")
    assert rows, "CQ12に答えられない"
    by_year = {int(y): (int(total), int(count)) for y, total, count in rows}
    # FY2025: ブロックA(1,000,000) + 間接経費(7,000) = 2件
    assert by_year[2025] == (1_007_000, 2), by_year
    # FY2024(PROJECT_MULTI_YEAR)はブロックを持たないので現れない
    assert 2024 not in by_year, by_year


def test_cq12_is_not_the_naive_sum_of_all_amounts(kg):
    """**正のコントロール**: 同じfixtureに対する「型で絞らない素朴な合計」が
    CQ12の答えより大きいことを、実際に両方数えて示す。

    何があれば落ちるか: このテストが通らなくなるのは、fixtureから段の重複が
    消えたとき —— つまり**CQ12が「重複を除いている」という主張の根拠が
    fixtureから失われたとき**である。CQ12の期待値だけを直書きしていると、
    fixtureが平坦になっても気づけない(欠陥型: 空虚なテスト)。
    """
    naive = list(kg.query(
        "PREFIX core: <https://jgkg.norr-tech.com/def/core#> "
        "SELECT (SUM(?a) AS ?t) WHERE { ?x core:amount_jpy ?a }"
    ))
    naive_total = int(naive[0][0])
    cq12 = {int(y): int(total) for y, total, _ in _query(kg, "cq12-government-paid-total.rq")}
    assert naive_total > cq12[2025], (
        f"素朴な合計({naive_total})がCQ12の答え({cq12[2025]})を上回っていない"
        " —— fixtureに段の重複が無くなっており、CQ12の主張を裏づけられない"
    )


# =============================================================================
# CQ13: 同じお金が複数の段に記録されている事業はどれか(裁定B97)
# =============================================================================


def test_cq13_finds_the_pass_through_stage_and_not_the_entry(kg):
    """出どころを持つブロック(B)だけが返り、入口(A)と孤立ブロック(C)が
    返らないこと。返る行が「足してはいけない額」を指していること。

    何があれば落ちるか: `budget:fundedBy` を必須にしている部分がOPTIONALに
    変わると、AとCも返って「重複の在りか」を示す問いでなくなる。
    fundedByの向きを逆に実装すると(出どころ側に張ると)、Aが返ってBが返らない。
    """
    rows = _query(kg, "cq13-money-passing-through-stages.rq")
    assert rows, "CQ13に答えられない"
    # **列は名前で読む(位置で分解しない)。** 2026-09-13にCQ13へ `?project`
    # を足したら、位置で分解していたこのテストが「7個のはずが8個」で落ちた
    # ——列の**追加**で落ちる検査は、追加が安全かを何も言っていない
    # (裁定B103追記7の「変更は加算のみ」を検査側が支えられていなかった)。
    seen = {
        str(row["blockId"]): (str(row["sourceId"]), int(row["amount"])) for row in rows
    }
    assert set(seen) == {"B"}, f"出どころを持つブロックはBだけのはず: {seen}"
    assert seen["B"] == ("A", 1_000_000), seen
    # 事業のIRIも返ること(裁定B110。トップから事業ページへ遷移するために要る)。
    assert all(row["project"] is not None for row in rows), "CQ13が事業のIRIを返していない"


def test_cq13_reports_whether_the_stage_was_paid_by_government(kg):
    """返る行が `paidByGovernment` を持ち、Bについて偽であること。

    **実データにはこれが真になるブロックが9件ある**(国からの支払いと他の段
    からの流入が混在する。裁定B97・schema/budget.yamlの`paidByGovernment`
    のdocstring)。その場合「入口の合計」に全額が入って過大になりうるため、
    このCQは真偽をそのまま返して読み手に判断させる —— 列を落とすと、
    混在ブロックを見分ける手段が画面から消える。

    何があれば落ちるか: クエリから`?paidByGovernment`を消すとタプルの
    形が変わって落ちる。emit側が偽のときに述語を出さない実装に戻すと、
    未束縛になって None になる。
    """
    rows = _query(kg, "cq13-money-passing-through-stages.rq")
    # 列は名前で読む(上のテストと同じ理由)。
    flags = {str(row["blockId"]): row["paidByGovernment"] for row in rows}
    assert "B" in flags, flags
    assert flags["B"] is not None, "paidByGovernmentが未束縛(偽のとき出していない疑い)"
    assert bool(flags["B"].toPython()) is False, flags["B"]


# =============================================================================
# CQ14: 国の予算はいくら付いて、いくら使われたか。年度ごとに(裁定B99)
# =============================================================================


def test_cq14_returns_one_row_per_budget_year_with_the_breakdown(kg):
    """1事業が複数年度の記録を持ち、**予算年度ごとに1行**返ること。
    4つの内訳が恒等式(当初+補正+繰越+予備費=現額)を満たすこと。

    fixtureのPROJECT_COREは3年度を持つ(2026年度はCQ20実演——不一致の
    年度ペアを作るためteam-lead裁定で追加。task-2b-report.md参照):
      2024: 90 + 5 + 3 + 2 = 100(現額) / 執行80
      2025: 100 + 0 + 0 + 0 = 100(現額) / 執行0(未執行)
      2026: 95 + 0 + 0 + 0 = 95(現額) / 執行0(未執行)

    何があれば落ちるか:
    - `budgetFiscalYear`でGROUP BYしなくなると3年度が1行に潰れる
    - `fiscalYear`(シート年度)と`budgetFiscalYear`(対象年度)を同じスロットに
      統合すると、2024年度の行が消える(シート年度は2025しか無いため)
    - 内訳のどれかを必須にし忘れて0件になる
    """
    rows = _query(kg, "cq14-budget-and-execution-by-year.rq")
    assert rows, "CQ14に答えられない"
    by_year = {}
    for sheet, budget_year, init, supp, carried_in, reserve, avail, executed, count in rows:
        assert int(sheet) == 2025, f"fixtureのシート年度は2025のみ: {sheet}"
        by_year[int(budget_year)] = (
            int(init), int(supp), int(carried_in), int(reserve), int(avail), int(executed), int(count)
        )
    assert sorted(by_year) == [2024, 2025, 2026], by_year
    assert by_year[2024] == (90_000_000, 5_000_000, 3_000_000, 2_000_000, 100_000_000, 80_000_000, 1)
    assert by_year[2025] == (100_000_000, 0, 0, 0, 100_000_000, 0, 1)
    assert by_year[2026] == (95_000_000, 0, 0, 0, 95_000_000, 0, 1)
    # 恒等式が全年度で成立する(CQが返す値そのもので確かめる)
    for y, v in by_year.items():
        assert v[0] + v[1] + v[2] + v[3] == v[4], f"{y}年度の恒等式が崩れている: {v}"


def test_cq14_keeps_the_sheet_year_row_whose_executed_amount_is_zero(kg):
    """**執行額0の年度を落とさない**こと。

    実データではレビューシート年度(最新)の執行額が5,794事業すべて0である
    (まだ執行されていない。裁定B99)。`budget:executedAmount`を
    「値があるときだけ書く」実装で**0を欠損として扱うと、最新年度の行が
    まるごと消える** —— つまり「今年の予算はいくらか」に答えられなくなる。

    何があれば落ちるか: emit側が`if value:`(0を偽と見る)で判定するように
    戻ると、2025年度の行がCQ14から消えてこのテストが落ちる。
    """
    rows = _query(kg, "cq14-budget-and-execution-by-year.rq")
    years = {int(budget_year): int(executed) for _s, budget_year, *rest in rows
             for executed in [rest[5]]}
    assert 2025 in years, f"執行額0の年度が落ちている: {sorted(years)}"
    assert years[2025] == 0, years


def test_cq14_initial_budget_of_the_sheet_year_matches_the_project_budget_amount(kg):
    """`budgetAmount`(BudgetProject)と`initialBudget`(AnnualBudget)が
    **別の述語として存在し、シート年度については同じ値**であること。

    同じ述語に統合すると`SUM(?budgetAmount)`が粒度をまたいで二重に数える
    (実データでは5,794件 対 23,036件。schema/budget.yamlの`initialBudget`の
    docstring参照)。**別述語であることと、値が一致することの両方**を
    ここで固定する。

    何があれば落ちるか: `initialBudget`を`budgetAmount`に統合すると、
    このクエリのどちらかの束縛が消えて0行になる。値をずらすと不一致で落ちる。
    """
    rows = list(kg.query("""
        PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
        SELECT ?project ?budgetAmount ?initialBudget WHERE {
          ?project budget:budgetAmount ?budgetAmount ;
                   budget:fiscalYear ?sheetYear .
          ?annual budget:project ?project ;
                  budget:budgetFiscalYear ?sheetYear ;
                  budget:initialBudget ?initialBudget .
        }
    """))
    assert rows, "budgetAmountとinitialBudgetを突き合わせられない"
    for project, budget_amount, initial_budget in rows:
        assert int(budget_amount) == int(initial_budget), (
            f"{project} のbudgetAmount({int(budget_amount)})とシート年度の"
            f"initialBudget({int(initial_budget)})が食い違っている"
        )


def test_cq14_next_year_request_is_readable_and_is_not_the_initial_budget(kg):
    """`nextYearRequest`(翌年度要求額)が読めること。**当初予算とは別の値**
    であること。

    **controllerはこの列を「集計行すべてで空」と誤って記録していた**
    (裁定B99の訂正) —— 測定スクリプトが`.isdigit()`で判定していたため、
    `'45013000.0'`という小数表記を「空」と誤認した。実際は23,036件すべてが
    非空である。実データでは年度Yの要求額が年度Y+1の当初予算とおおむね
    対応する(96.9〜99.4%)。

    何があれば落ちるか: 取り込みが小数表記を欠損として落とすと0行になる
    (`transform.rs.normalize_amount`が末尾の`.0`を落とす実装に依存している)。
    """
    rows = list(kg.query("""
        PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
        SELECT ?budgetYear ?request ?initial WHERE {
          ?annual budget:budgetFiscalYear ?budgetYear ;
                  budget:nextYearRequest ?request ;
                  budget:initialBudget ?initial .
        }
        ORDER BY ?budgetYear
    """))
    assert rows, "nextYearRequestが読めない(取り込みが小数表記を落としている疑い)"
    by_year = {int(y): (int(req), int(init)) for y, req, init in rows}
    assert sorted(by_year) == [2024, 2025], by_year
    # fixtureは「2024年度に100を要求し、2025年度に当初100が付いた」形にしてある
    assert by_year[2024][0] == 100_000_000, by_year
    assert by_year[2025][1] == 100_000_000, by_year
    # 要求額と当初予算が別の値であること(同じスロットに潰れていない)
    assert by_year[2025][0] != by_year[2025][1], (
        f"2025年度の要求額と当初予算が同じ値になっている: {by_year[2025]}"
    )


# =============================================================================
# CQ15〜CQ18: トップページ第1層が出す数字の出所(裁定B103)
# =============================================================================


def test_cq15_ranks_every_ministry_not_just_one(kg):
    """**全府省**が返り、予算額の降順であること。CQ2は1府省に固定されている。

    何があれば落ちるか:
    - `budget:ministry <...6000012070001>` のように府省を固定に戻すと1行になる
    - `OPTIONAL { ?ministry skos:prefLabel ?name }` を必須にすると、
      表示名の無い府省の行が消えて合計が減る

    **修正ラウンド(task-1-report.md参照)**: fixtureの全RsRowが
    `ministry_name="厚生労働省"`しか使っていなかったため、この正のコントロール
    (2府省以上)自体がfixture側で検証できていなかった。
    `tests/phase1_fixture.py`のPROJECT_MINISTRY_RANKING_DEMO(内閣府)を
    追加して初めて、このテストが「1府省固定」と「複数府省」を実際に
    区別できるようになった。
    """
    rows = _query(kg, "cq15-ministry-budget-ranking.rq")
    assert rows, "CQ15に答えられない"
    budgets = [int(r[3]) for r in rows]
    assert budgets == sorted(budgets, reverse=True), f"降順でない: {budgets}"
    ministries = {str(r[0]) for r in rows}
    assert len(ministries) >= 2, f"府省が1つしか返っていない(CQ2と同じになっている): {ministries}"


def test_cq16_returns_request_and_initial_side_by_side(kg):
    """要求額と当初予算が**同じ行に別の列として**返ること。

    何があれば落ちるか: クエリ側で年度をずらす(Y の要求と Y+1 の当初を
    同じ行に置く)実装にすると、この行の2つの数字が何なのか読めなくなる
    ——対応付けは表示側の仕事である(クエリのヘッダ参照)。
    """
    rows = _query(kg, "cq16-request-vs-initial-budget.rq")
    assert rows, "CQ16に答えられない"
    by_year = {int(r[0]): (int(r[1]), int(r[2]), int(r[3])) for r in rows}
    assert sorted(by_year) == [2024, 2025], by_year
    # fixtureは「2024年度に100を要求し、2025年度に当初100が付いた」形
    assert by_year[2024][0] == 100_000_000, by_year
    assert by_year[2025][1] == 100_000_000, by_year
    assert by_year[2025][0] != by_year[2025][1], (
        f"要求額と当初予算が同じ値になっている(同じ列を2回読んでいる疑い): {by_year[2025]}"
    )


def test_cq17_sums_amounts_from_the_core_namespace(kg, budget_result):
    """照合区分ごとの金額が返ること。**`core:amount_jpy`を読んでいる**こと。

    何があれば落ちるか: `budget:amount_jpy`(存在しない)に書き換えると
    **エラーにならず0件**になる。そのとき「支払先の特定は0件」という
    嘘が画面に出る——だから金額の合計が非0であることを固定する。

    **修正ラウンド1(task-1-review.md指摘1・3)**: 以前は件数の期待値を
    手書きの定数にしていた(ブリーフ原案の`count == 4`→実測に合わせた
    `count == 10`)。これは「導出できる値を手書きする」という同じ罠を
    別の数字で再演していただけで、fixtureに支出を1件足せばクエリが
    正しくても落ちる。`test_cq6_totals_match_task7_build_stats`(このファイル
    L334の前例)に倣い、`budget_result.stats`(本番の`BuildStats`)から
    期待値を導く。あわせて区分の**名前**そのもの(件数だけでなく)を
    突き合わせる——4区分返れば中身が何でも緑になる、という弱いアサートを閉じる。

    このテストはCQ6(事業ごと)の「KG全体」版でもある。CQ6が一致していても
    CQ17が一致しない状態(例: `core:amount_jpy`を持たない支出が1件でもある)
    は、「支払先はどこまで特定できているか」というデータ品質パネル自身が
    自分の欠損を隠していることを意味する。
    """
    rows = _query(kg, "cq17-recipient-identification.rq")
    assert rows, "CQ17に答えられない(述語の名前空間を間違えている疑い)"
    total = sum(int(r[1]) for r in rows)
    assert total > 0, f"金額の合計が0(core:amount_jpyを読めていない): {rows}"

    counts = {str(r[0]).rsplit("/", 1)[-1].rsplit("#", 1)[-1]: int(r[2]) for r in rows}
    stats = budget_result.stats
    resolved_total = stats.recipients_resolved_by_houjin_bangou + stats.recipients_resolved_by_name
    assert counts == {
        "resolved": resolved_total,
        "unresolved": stats.recipients_unresolved,
        "bundled": stats.expenditures_bundled,
        "sentinel_or_nonexistent_houjin_bangou": (
            stats.recipients_sentinel + stats.recipients_nonexistent_houjin_bangou
        ),
    }, (counts, stats)


def test_cq18_counts_instances_across_named_graphs(kg):
    """型ごとの件数が、実測値どおりに返ること。

    **検出できる(実測で確認済み)**: 型のどれかの件数がずれること。
    たとえば1つの名前付きグラフだけに絞る変異
    (`GRAPH <.../graph/houjin-bangou/2026-08-01> { ?s a ?type }`)を試すと、
    組織ドメイン以外の型がすべて消えて実際に落ちる(task-1-report.md
    「修正ラウンド1」参照)。CQ18は「このKGには何が何件入っているか」
    という**件数そのものが答え**のCQなので、Step 5の実測値
    (`schema/competency-questions.md`「答えの例」と同じ値)をそのまま固定する
    ——`Expenditure`の10件はCQ17テストが`budget_result.stats`から導く
    支出の内訳合計とも一致する。

    **検出できない(実測で確認済み。修正ラウンド2)**: `GRAPH ?g { ?s a ?type }`
    (名前付きグラフを個別に辿る形)を試しても、この完全一致に変えた後も
    **PASSEDのまま**だった——このfixtureには同じ`(s, rdf:type, type)`が
    複数の名前付きグラフに重複して乗っているケースが無いため、二重計上が
    そもそも起こらない。実演するにはfixtureにcarry-over型の重複トリプルを
    人工的に注入する必要があり、**見送った**(controller裁定: 他の29件の
    CQテストの標本を人工の重複で汚すコストの方が高い)。
    """
    rows = _query(kg, "cq18-kg-scale.rq")
    assert rows, "CQ18に答えられない"
    counts = {str(r[0]).rsplit("#", 1)[-1]: int(r[1]) for r in rows}
    assert counts == {
        "GovernmentOrgan": 40,
        "Ministry": 40,
        "Expenditure": 10,
        "BudgetProject": 5,
        "Law": 4,
        "UnresolvedReference": 3,
        "LawRevision": 3,
        "ExpenditureBlock": 3,
        # CQ20実演のため2026年度分を1件追加した(team-lead裁定。
        # task-2b-report.md参照)ので2→3件になった。
        "AnnualBudget": 3,
        "Organization": 1,
        "AbolishedGovernmentOrgan": 1,
        "IndirectCost": 1,
    }, counts


# =============================================================================
# CQ19: 素朴な合計と入口だけの合計(裁定B103の追記。第4節の中心の主張)
# =============================================================================


def test_cq19_naive_sum_includes_all_blocks_and_entry_only_is_just_the_entry_stage(kg):
    """fixtureのPROJECT_FLOW_DEMO(A入口1,000,000・B通過1,000,000・C借入金
    500,000)に対し、`naiveSum`が3ブロック全額(2,500,000)、`entryOnly`が
    入口(A)だけ(1,000,000)、`blockCount`が3であること。

    何があれば落ちるか:
    - `budget:paidByGovernment ?entry`を落とす・`IF(?entry, ?all, 0)`を
      `?all`に変えると`entryOnly`が`naiveSum`と同じ2,500,000になる
      (壊し確認。task-2b-report.md参照)
    - `blockCount`が入口だけを数える実装に変わると3ではなく1になる
      ——`blockCount`は入口/非入口を問わず全ブロックを数える設計であることの
      正のコントロール
    """
    rows = _query(kg, "cq19-naive-sum-vs-entry-only.rq")
    assert rows, "CQ19に答えられない"
    by_year = {int(y): (int(naive), int(entry), int(count)) for y, naive, entry, count in rows}
    assert sorted(by_year) == [2025], by_year
    assert by_year[2025] == (2_500_000, 1_000_000, 3), by_year


def test_cq19_entry_only_matches_the_independent_sum_from_budget_result_blocks(kg, budget_result):
    """**正のコントロール(ブリーフStep 3の要求)**: `entryOnly`が
    `SUM(IF(?entry, ?all, 0))`の効果によるものであることを、`entryOnly <
    naiveSum`という弱い比較ではなく、一次データを組み立てる別の経路
    (`budget_result.blocks`。`rs.build_projects`の戻り値。手書きSPARQLでは
    ない)から独立に導いた「入口フラグが真のブロックの金額合計」と
    突き合わせて確認する。

    何があれば落ちるか: このテストは`naiveSum`・`entryOnly`・`blockCount`の
    3つを`budget_result.blocks`から独立に再計算するため、
    `IF(?entry, ?all, 0)`を`?all`に変える変異(全ブロックを入口として
    数える)は、独立に導いた`entry`(1,000,000)とCQ19の`entryOnly`
    (変異後は2,500,000)が不一致になって落ちる——`entryOnly < naiveSum`
    だけを見る形では、fixtureのブロックがたまたまその関係を満たしているだけ
    かもしれず、この変異を検出できない(ブリーフStep 3の指摘そのもの)。
    """
    rows = _query(kg, "cq19-naive-sum-vs-entry-only.rq")
    cq19 = {int(y): (int(naive), int(entry), int(count)) for y, naive, entry, count in rows}

    by_year: dict[int, dict[str, int]] = {}
    for block in budget_result.blocks:
        year_totals = by_year.setdefault(int(block.fiscal_year), {"naive": 0, "entry": 0, "count": 0})
        year_totals["naive"] += block.amount
        year_totals["count"] += 1
        if block.paid_by_government:
            year_totals["entry"] += block.amount

    assert set(cq19) == set(by_year), (cq19, by_year)
    for y, (naive, entry, count) in cq19.items():
        expected = by_year[y]
        assert naive == expected["naive"], (y, naive, expected)
        assert entry == expected["entry"], (y, entry, expected)
        assert count == expected["count"], (y, count, expected)
        assert entry < naive, (
            f"{y}年度: entryOnly({entry})がnaiveSum({naive})未満になっていない"
            " —— fixtureに通過/借入の段が無く、二重計上の主張を裏づけられない"
        )


def test_cq19_entry_only_differs_from_cq12_government_paid_total(kg):
    """**CQ19の`entryOnly`とCQ12の`governmentPaid`は別の値である**こと
    (`models.py`の`NaiveSumVsEntryOnly`docstring・CQ19ヘッダ参照)。

    CQ12=`entryOnly` + 間接経費なので、fixtureのFY2025では
    CQ12=1,007,000円(=1,000,000+7,000) ≠ CQ19の`entryOnly`=1,000,000円。
    表示側がこの2つを同じ「国が自ら支払った額」として混同すると、
    差の7,000円分だけ食い違ったまま気づけない——両方を実際にfixtureに対して
    計算し、意図的に不一致であることをここで固定する。
    """
    cq19 = {int(y): int(entry) for y, _naive, entry, _count in _query(kg, "cq19-naive-sum-vs-entry-only.rq")}
    cq12 = {int(y): int(total) for y, total, _count in _query(kg, "cq12-government-paid-total.rq")}
    assert cq19[2025] == 1_000_000, cq19
    assert cq12[2025] == 1_007_000, cq12
    assert cq19[2025] != cq12[2025], (
        "CQ19のentryOnlyとCQ12のgovernmentPaidが一致してしまっている"
        " —— 間接経費の扱いが混ざった疑い"
    )


# =============================================================================
# CQ20: 要求額がそのまま付いた事業の件数(裁定B103の追記。第3節の誤読防止)
# =============================================================================


def test_cq20_counts_the_project_present_in_both_years_and_its_exact_match(kg):
    """fixtureのPROJECT_CORE(CQ14/CQ16と同じ事業)に対し、
    **一致する年度ペアと一致しない年度ペアの両方**が正しく数えられること。

    - 2024年度: `nextYearRequest`(100,000,000円)と2025年度の
      `initialBudget`(100,000,000円)が**一致**する
    - 2025年度: `nextYearRequest`(110,000,000円)と2026年度の
      `initialBudget`(95,000,000円)が**一致しない**
      (2026年度分は不一致の年度ペアを作るために追加した。team-lead裁定。
      `tests/phase1_fixture.py`のPROJECT_CORE・task-2b-report.md参照)

    2026年度は`nextYearRequest`を持たないため、2026年度自身が
    `requestYear`になる行は現れない(次の年度=2027の記録も無い)。

    **追記(裁定「導出の母集団が正しくなければならない」): `requestedBoth`/
    `initialBoth`も固定する。** 両方の年度に存在する事業だけの要求額・
    当初予算の合計であり、フロントエンドはこれを割合の分母・分子に使う
    (`RequestAndInitial`の全事業合計を使うと、新規事業の混入で見かけの
    比率になる——実データで2022→2023年度が104.1%になった実例)。
    fixtureにはPROJECT_CORE1件しかCQ20に現れないので、`requestedBoth`/
    `initialBoth`は該当年度の`nextYearRequest`/`initialBudget`そのものと
    一致する。

    何があれば落ちるか(いずれも実際に壊して確認した。task-2b-report.md参照):
    - `SUM(IF(?req = ?nextInitial, 1, 0))`を`SUM(1)`(全件を一致として
      数える)に変えると、2025年度のexactMatchesが0から1に変わって
      `by_year[2025]`が崩れる(**2026年度追加前は、一致する
      事業しかfixtureに無くこの変異を検出できなかった**——この壊し
      確認が通るようになったこと自体が、今回のfixture修正の目的である)
    - `BIND(?requestYear + 1 AS ?nextYear)`を外し同一年度で比べる実装に
      戻すと、年度の集合(`{2024, 2025}`)自体は変わらないが、2024年度の
      `exactMatches`が1から0に変わる(同一年度のnextYearRequest
      100,000,000円とinitialBudget 90,000,000円は一致しないため)——
      `by_year[2024]`が崩れる
    """
    rows = _query(kg, "cq20-request-exactly-granted.rq")
    assert rows, "CQ20に答えられない"
    by_year = {
        int(y): (int(req_both), int(init_both), int(both), int(exact))
        for y, req_both, init_both, both, exact in rows
    }
    assert sorted(by_year) == [2024, 2025], by_year
    assert by_year[2024] == (100_000_000, 100_000_000, 1, 1), by_year
    assert by_year[2025] == (110_000_000, 95_000_000, 1, 0), by_year


def test_cq20_matches_the_independent_count_from_budget_result_annual_budgets(kg, budget_result):
    """`requestedBoth`/`initialBoth`/`projectsInBothYears`/`exactMatches`を、
    `budget_result.annual_budgets`(`rs.build_projects`の戻り値。手書きSPARQL
    ではない別経路)から(project_id, budget_fiscal_year)で自前に結合し直した
    値と突き合わせる——CQ19の`test_cq19_entry_only_matches_the_independent_
    sum_from_budget_result_blocks`と同型の正のコントロール。

    **訂正(team-lead裁定を受けた修正)。** この関数の前の版は「fixtureに
    不一致の事業が無いため、`SUM(IF(?req = ?nextInitial, 1, 0))`を
    `SUM(1)`に変える変異を検出できない」という既知の限界を書いていた。
    team-leadの指摘(CQ18/CQ15と違い、これは人工的な汚染ではなく
    **現実の側の普通の姿**——要求が満額通らない事業——をfixtureに
    入れることだという指摘)を受けて`tests/phase1_fixture.py`の
    PROJECT_COREに2026年度(不一致)を追加した結果、**この独立経路の
    突き合わせが実際にその変異を検出できるようになった**
    (2025年度: 独立経路が導くexact=0に対し、変異後のCQ20は1を返すため
    不一致になる。壊し確認は`test_cq20_counts_the_project_present_in_
    both_years_and_its_exact_match`のdocstring・task-2b-report.md参照)。

    **追記(裁定「導出の母集団が正しくなければならない」): `requestedBoth`/
    `initialBoth`(両方の年度に存在する事業だけの要求額・当初予算の合計)も
    同じ独立経路(`nextYearRequest`/`initialBudget`をそのまま足す)で
    突き合わせる。** `SUM(?req)`を`SUM(?req) + 1`のような変異に変えると
    ここで検出できる。
    """
    rows = _query(kg, "cq20-request-exactly-granted.rq")
    cq20 = {
        int(y): (int(req_both), int(init_both), int(both), int(exact))
        for y, req_both, init_both, both, exact in rows
    }

    by_key = {
        (rec.project_id, int(rec.budget_fiscal_year)): rec
        for rec in budget_result.annual_budgets
    }
    requested_both: dict[int, int] = {}
    initial_both: dict[int, int] = {}
    both_years: dict[int, int] = {}
    exact: dict[int, int] = {}
    for (project_id, y), rec in by_key.items():
        if rec.next_year_request is None:
            continue
        nxt = by_key.get((project_id, y + 1))
        if nxt is None or nxt.initial_budget is None:
            continue
        requested_both[y] = requested_both.get(y, 0) + rec.next_year_request
        initial_both[y] = initial_both.get(y, 0) + nxt.initial_budget
        both_years[y] = both_years.get(y, 0) + 1
        if rec.next_year_request == nxt.initial_budget:
            exact[y] = exact.get(y, 0) + 1

    assert set(cq20) == set(both_years), (cq20, both_years)
    for y, (req_both, init_both, both, exact_count) in cq20.items():
        assert req_both == requested_both[y], (y, req_both, requested_both)
        assert init_both == initial_both[y], (y, init_both, initial_both)
        assert both == both_years[y], (y, both, both_years)
        assert exact_count == exact.get(y, 0), (y, exact_count, exact)
