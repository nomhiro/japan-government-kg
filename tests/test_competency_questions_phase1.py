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
from rdflib import Dataset, URIRef

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


# =============================================================================
# CQ1: この府省令の所管府省はどこか
# =============================================================================


def test_cq1_jurisdiction_of_ordinance(kg):
    rows = _query(kg, "cq01-jurisdiction-of-ordinance.rq")
    assert rows, "CQ1に答えられない"
    assert len(rows) == 1, f"厚生労働省令の所管は1件のはず: {rows}"
    ministry, name = rows[0]
    assert ministry == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(name) == "厚生労働省"


# =============================================================================
# CQ2: この府省が所管する予算事業は何か。年度ごとの総額はいくらか
# =============================================================================


def test_cq2_ministry_budget_by_year(kg):
    """厚生労働省の3事業(FY2025×2・FY2024×1)が年度別に正しく集計されること。

    何があれば落ちるか: ministryのURIがずれたら0件になる。年度でGROUP BYせず
    全事業を1本に合計したら年度が2行に分かれず1行になる。budgetAmountの
    代わりにExpenditureを合計する実装に変えたら、B20の役割二重計上
    (PROJECT_ROLE_DEMO)の影響で2025年度の総額が狂う。
    """
    rows = _query(kg, "cq02-ministry-budget-by-year.rq")
    assert rows, "CQ2に答えられない"
    by_year = {int(y): (int(total), int(count)) for y, total, count in rows}
    assert by_year == {
        2025: (100_000_000 + 10_000_000, 2),  # PROJECT_CORE + PROJECT_ROLE_DEMO
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
    """
    rows = _query(kg, "cq05-ministry-of-basis-law.rq")
    assert rows, "CQ5に答えられない"
    matches = [r for r in rows if r[0] == _uri("law", fx.OLD_KOUSEISHO_LAW_ID)]
    assert len(matches) == 1, f"旧厚生省令を根拠とする事業は1件のはず: {matches}"
    _law, project, ministry, ministry_name = matches[0]
    assert project == URIRef(f"{BASE}/id/budget/2025/{fx.PROJECT_CORE}")
    assert ministry == _uri("org", fx.KOUSEIROUDOU_BANGOU)
    assert str(ministry_name) == "厚生労働省"


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


def test_cq10_release_freshness_covers_all_four_sources(kg):
    """P0-4は2ソースだったが、law/budgetを加えたこのfixtureでは4ソース
    (houjin-bangou・ministry-codes・egov-law・rs-system)すべてが返ること。

    何があれば落ちるか: ソースが1つでも欠けたら落ちる。egov-law/rs-system
    はrecorded_onを持たないため両方「取得日」になるはず — 「記録日」に
    化けたら(ministry-codesの値を誤って流用したら)落ちる。
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
    }, by_source
