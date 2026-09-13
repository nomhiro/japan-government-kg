"""トップページ第1層のための集約(裁定B103)。

**このモジュールは手書きのSPARQLを持たない。** `queries/cq/*.rq`を読んで
`KGClient.query`に**そのまま**渡し、返ってきた行を型に詰めるだけである。

**なぜそうするか。** 画面に出す数字を別途集計すると、KGとは別の真実が
1つ増える。設計書の原則1「本体はオントロジーとKG、アプリは検証装置」に
照らすと、**トップページはCQの答えを表示する装置**であるのが正しい
——第1層に新しい数字を出したければCQを足すことになる。

これは`warmup.py`が裁定B60で確立した規律と同じである
(「手書きのSPARQLをここに置かない。実際のコード経路を呼ぶ」)。
`tests/test_api_overview.py`がこれを固定している。

**起動時に1回だけ計算する。** team-leadが本番と同じ索引
(1,438,620トリプル)で実測した値は、Task 2時点の7本のCQを走らせるのに
**コールド7.282秒・ウォーム2.772秒**(コンテナ再起動直後/ウォーム)。
第1層は全訪問者が最初に開く画面なので、リクエストごとに払える代償ではない。
また`minReplicas=1`/`maxReplicas=1`でFusekiとAPIが同じレプリカを共有して
おり、Fuseki側にクエリのタイムアウトがまだ無い(既知の未処理事項)。

**Task 2b追記: CQ19・CQ20を足して9本になった。** controllerが本番と同じ
索引に対して単体で実測した値は、CQ19が**1.390秒**
(`queries/cq/cq19-naive-sum-vs-entry-only.rq`のヘッダ参照)、CQ20が
**3.617秒**(`BIND`を前置する形。後置`FILTER`だと13.362秒だった——
`queries/cq/cq20-request-exactly-granted.rq`のヘッダ参照)。

**9本合計の本番実測はまだ無い。** team-leadの見込みは
**約12.3秒**(=7.282秒+1.390秒+3.617秒の単純な足し算。**本人も「見込みで
あって実測ではない」と明記している**)。単純な足し算をこのモジュール自身の
主張として書くと「測った」と「測っていないものを足し算した」の区別が
付かなくなる(このモジュール自身が上で訂正した欠陥型と同型になる)ため、
**この見込み値をここでは書かない** ——9本合計の本番実測はTask 7で
controllerが行う予定(task-2b-report.md参照)。

**訂正(修正ラウンド1。レビューで誤診と指摘された)**: このdocstringの前の版は
「3.999秒/3.114秒は実測前の仮の値だった」と書いていたが、これは誤り。
`docs/decision-log.md`(裁定B103)を読むと、3.999秒/3.114秒も**実測値**である
——ただし**この設計を決める前に書いた別の5本のクエリ**を測ったものであり、
CQ15の修正を経て確定した**この7本**とは違う集合だった。実際の誤りは
「測っていない数字を書いた」ではなく「**別のクエリ集合の実測値**を、
この7本の費用として引いた」である。診断を間違えたまま「測っていない数字を
書く欠陥の再発防止」と書くと、読んだ人が学ぶべき教訓
(「引く測定値が、記述している対象の測定値かを確かめる」)ではなく、
無関係な教訓(「測らずに書くな」)を学んでしまう——このプロジェクトが
繰り返し扱う「文書が実装/実測と異なる主張をする」欠陥型そのものであり、
ここで訂正する。この7本自体の実測値(7.282秒/2.772秒。コンテナ再起動直後/
2周目)は正しい。
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jgkg.api.kgclient import KGClient, Row, Term
from jgkg.api.models import (
    BudgetAndExecution,
    GovernmentPaidTotal,
    MinistryBudget,
    MoneyThroughStage,
    NaiveSumVsEntryOnly,
    OverviewResponse,
    RecipientIdentification,
    ReleaseFreshness,
    RequestAndInitial,
    RequestExactlyGranted,
    TypeCount,
)

# **`_id_path`は`queries.py`のプライベート関数だが、改名せずそのまま使う
# (team-leadから判断を委ねられた点。報告に理由を書く)。** `queries.py`の
# 既存の呼び出し箇所(`_id_path`と検索して分かる: search_entities・
# get_entity_detail・_unknown_entity_ref・_hydrate_entity_refs・
# _entity_exists)のうち、`get_entity_detail`・`_entity_exists`は
# **`id_path`という名前のローカル変数/パラメータを既に持つ**
# (`get_entity_detail(client, base_uri, id_path, limit)`)。この関数を
# `id_path`という公開名に改名すると、そのローカル変数がモジュール関数を
# 覆い隠し(`id_path=id_path(base_uri, entity_uri)`は「strはcallableでは
# ない」で落ちる)、既存の安定したエンドポイントを壊す。**複製を作らない**
# という制約の下では、衝突しない別の公開名(例: `derive_id_path`)へ改名して
# 呼び出し箇所全てを直すか、このままプライベート名を1箇所からimportするかの
# 二択になる——後者は挙動を一切変えない最小の変更であり、既に安定している
# `/search`・`/entity/{id}`・`/neighborhood/{id}`・`/path`に触れない。
# **呼び出し箇所の個数はここに書かない**(`queries.py`の`_id_path`docstring
# 参照。件数を書けば`MinistryBudget`のように増えたときまた古くなる)。
from jgkg.api.queries import _id_path

#: 応答の項目 → CQファイル名。**ここが数字の出所の一覧である。**
#: 項目を足したければCQを足す(裁定B103)。
OVERVIEW_QUERIES: dict[str, str] = {
    "ministries": "cq15-ministry-budget-ranking.rq",
    "budget_and_execution": "cq14-budget-and-execution-by-year.rq",
    "request_and_initial": "cq16-request-vs-initial-budget.rq",
    "recipient_identification": "cq17-recipient-identification.rq",
    "type_counts": "cq18-kg-scale.rq",
    "government_paid": "cq12-government-paid-total.rq",
    "money_through_stages": "cq13-money-passing-through-stages.rq",
    # 鮮度(裁定B111)。**新しいルートは作らない** ——`/overview` に足せば
    # 裁定B103の「画面の値はCQの答え」の機構にそのまま乗り、`sources` に
    # 出所のCQ名も出る。行数はソース×リリースで決まり、構造的に小さい。
    "release_freshness": "cq10-release-freshness.rq",
    # Task 2b: CQ19(第4節「予算に対し記録を全部足すと合わない」の中心の
    # 主張そのもの)。controllerが本番と同じ索引で実測済み(モジュール
    # docstring参照)——このクエリ自体は変更しない。
    "naive_sum_vs_entry_only": "cq19-naive-sum-vs-entry-only.rq",
    # Task 2b(追加): CQ20(第3節「要求額はどれだけ付いたか」の誤読防止)。
    # CQ16の全体合計だけでは「ほぼ満額」と読めてしまう——事業ごとの
    # 完全一致率(実測3〜4割)を別に出す。BINDを前置する形が実測で3.7倍
    # 速い(controllerの実測。ヘッダ参照)——このクエリ自体は変更しない。
    "request_exactly_granted": "cq20-request-exactly-granted.rq",
}


def _int(row: Row, name: str) -> int:
    """束縛を整数で読む。**未束縛は0ではなく例外にする** ——
    集約の列が欠けているのは実装の誤りであり、0として通すと
    「予算0円」が画面に出る(このプロジェクトの再発欠陥: 欠損を
    既定値に落として静かに間違える)。

    **`float`を経由しない(レビュー要修正12)。** SPARQLの`SUM`/`COUNT`の
    結果は`"45013000.0"`のような小数表記で来ることがある(裁定B99実測)。
    `int(term.value)`で素直に通る整数表記はそのまま使い、それが失敗する
    表記だけ`Decimal`で受けて整数であることを確かめてから`int`にする——
    `float`より丸めの余地が無い。
    """
    term: Term | None = row.get(name)
    if term is None:
        raise ValueError(f"{name} が束縛されていない: {sorted(row)}")
    try:
        return int(term.value)
    except ValueError:
        pass
    try:
        decimal_value = Decimal(term.value)
    except Exception as exc:
        raise ValueError(f"{name} が整数として読めない: {term.value!r}") from exc
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"{name} が整数ではない: {term.value!r}")
    return int(decimal_value)


def _str(row: Row, name: str) -> str:
    """束縛を文字列で読む。**未束縛は空文字ではなく例外にする**(`_int`と同じ理由)。

    `_text`(下)とは対照的に、この列はSPARQL側でOPTIONALではない
    (常に束縛される)ことを型が`str`(non-null)であると宣言している列に使う。
    """
    term: Term | None = row.get(name)
    if term is None:
        raise ValueError(f"{name} が束縛されていない: {sorted(row)}")
    return term.value


def _text(row: Row, name: str) -> str | None:
    """束縛を文字列で読む。未束縛は`None`(OPTIONALな列に使う)。"""
    term: Term | None = row.get(name)
    return term.value if term is not None else None


def _bool(row: Row, name: str) -> bool:
    """束縛を真偽値で読む。**未束縛も、解釈できない値も、Falseに落とさず
    例外にする**(`_int`と同じ理由)。

    **訂正(レビュー要修正4)。** 前の版は`term.value == "true"`だけを見て
    おり、それ以外の字句形はすべて黙って`False`になっていた。`xsd:boolean`
    の正当な字句形は`"true"`/`"false"`だけでなく`"1"`/`"0"`もある
    (XML Schema Datatypes)。`?paidByGovernment`はデータから直接束縛される
    値であり、rdflibが返す字句形が正規化済みとは限らない
    (`kgclient._rdflib_term_to_term`が正規化するのはPythonの`bool`から
    作った`Literal`であって、TTLに`"1"^^xsd:boolean`と書かれていれば
    `"1"`がそのまま来る)。**`"1"`を黙って`False`にすると、入口ブロックが
    入口でなくなり、CQ13の表示(通過金/入口の区別)が狂う**——このプロジェクト
    が繰り返し扱う「欠損/解釈不能を既定値に落として静かに間違える」欠陥の
    再発になる。
    """
    term: Term | None = row.get(name)
    if term is None:
        raise ValueError(f"{name} が束縛されていない: {sorted(row)}")
    if term.value in ("true", "1"):
        return True
    if term.value in ("false", "0"):
        return False
    raise ValueError(f"{name} の値が真偽値として解釈できない: {term.value!r}")


def _parse_ministries(rows: list[Row], base_uri: str) -> list[MinistryBudget]:
    """CQ15の各行を`MinistryBudget`にする。

    **`?ministry`は`_text`(未束縛→None→黙って捨てる)ではなく`_str`
    (未束縛→例外)で読む(裁定。レビュー要検討8を受けた訂正)。**
    CQ15は`GROUP BY ?ministry ?name ?y`なので`?ministry`は常に束縛される
    ——`OPTIONAL`なのは`?name`だけである。黙って捨てる形だと、将来CQ15の
    形が変わって`?ministry`が本当に未束縛になったとき、CQ15のヘッダが
    警告する「落とすと合計が静かに減る(その府省の予算が消える)」を
    まさに`overview.py`側で再演してしまう——`_int`/`_str`/`_bool`が揃って
    宣言した「欠損は既定値ではなく例外にする」規律に、この列だけ逆行して
    いた。
    """
    out: list[MinistryBudget] = []
    for row in rows:
        iri = _str(row, "ministry")
        out.append(
            MinistryBudget(
                id=iri,
                id_path=_id_path(base_uri, iri),  # 引数の順に注意
                label=_text(row, "name"),
                fiscal_year=_int(row, "y"),
                total_budget=_int(row, "totalBudget"),
                project_count=_int(row, "projectCount"),
            )
        )
    return out


def _parse_budget_and_execution(rows: list[Row]) -> list[BudgetAndExecution]:
    """CQ14の各行を`BudgetAndExecution`にする。

    **`sheet_year`を持つ(裁定。修正ラウンド1で追加)。** 前の版は
    `?sheetYear`を使わず`budget_fiscal_year`(=`?budgetYear`)しか
    詰め替えていなかった——CQ14のヘッダが警告する「将来2つのシートが
    同じ`budgetYear`について食い違う」ケースが起きたとき、この応答だけを
    見る利用者は食い違いに気づけなかった(CQの生の答えには`sheetYear`が
    残っているので、消えるのはこの型に詰め替えた後だけだった)。
    `(sheet_year, budget_fiscal_year)`の組が一意であることは
    `tests/test_api_overview.py`が固定する。
    """
    return [
        BudgetAndExecution(
            sheet_year=_int(row, "sheetYear"),
            budget_fiscal_year=_int(row, "budgetYear"),
            initial_budget=_int(row, "initialBudget"),
            supplementary_budget=_int(row, "supplementaryBudget"),
            carried_over_from_previous_year=_int(row, "carriedOverFromPreviousYear"),
            reserve_fund=_int(row, "reserveFund"),
            total_budget_available=_int(row, "totalBudgetAvailable"),
            executed_amount=_int(row, "executedAmount"),
            project_count=_int(row, "projectCount"),
        )
        for row in rows
    ]


def _parse_request_and_initial(rows: list[Row]) -> list[RequestAndInitial]:
    return [
        RequestAndInitial(
            budget_fiscal_year=_int(row, "y"),
            requested=_int(row, "requested"),
            initial=_int(row, "initial"),
            record_count=_int(row, "recordCount"),
        )
        for row in rows
    ]


def _parse_recipient_identification(
    rows: list[Row], base_uri: str
) -> list[RecipientIdentification]:
    """CQ17の各行を`RecipientIdentification`にする。

    **`base_uri`はここでは使わない。** `?category`はIRIではなく型なしの
    文字列リテラルなので`_id_path`は要らない(CQ17ヘッダ・`models.py`の
    `RecipientIdentification`docstring参照)。`build_overview`から他の
    パーサ(`_parse_ministries`)と同じ形で呼べるように受け取るだけである。
    """
    return [
        RecipientIdentification(
            category=_str(row, "category"),
            total_amount=_int(row, "totalAmount"),
            expenditure_count=_int(row, "expenditureCount"),
        )
        for row in rows
    ]


def _parse_type_counts(rows: list[Row]) -> list[TypeCount]:
    return [
        TypeCount(type=_str(row, "type"), instance_count=_int(row, "instanceCount"))
        for row in rows
    ]


def _parse_government_paid(rows: list[Row]) -> list[GovernmentPaidTotal]:
    return [
        GovernmentPaidTotal(
            fiscal_year=_int(row, "y"),
            government_paid=_int(row, "governmentPaid"),
            item_count=_int(row, "itemCount"),
        )
        for row in rows
    ]


def _parse_money_through_stages(rows: list[Row], base_uri: str) -> list[MoneyThroughStage]:
    """CQ13の各行を`MoneyThroughStage`にする。

    **`?project`は`_str`(未束縛→例外)で読む。** CQ13のWHERE節で
    `?block budget:project ?project` は必須パターンなので常に束縛される
    ——`_parse_ministries`が`?ministry`について書いた判断と同じで、
    「欠損は既定値ではなく例外にする」規律をこの列にも適用する。
    """
    return [
        MoneyThroughStage(
            project_id=_str(row, "project"),
            project_id_path=_id_path(base_uri, _str(row, "project")),  # 引数の順に注意
            project_name=_str(row, "projectName"),
            block_id=_str(row, "blockId"),
            block_name=_text(row, "blockName"),
            paid_by_government=_bool(row, "paidByGovernment"),
            amount=_int(row, "amount"),
            source_id=_text(row, "sourceId"),
            source_name=_text(row, "sourceName"),
        )
        for row in rows
    ]


def _parse_release_freshness(rows: list[Row]) -> list[ReleaseFreshness]:
    """CQ10の各行を`ReleaseFreshness`にする。

    3列すべてを`_str`(未束縛→例外)で読む。CQ10のWHERE節は
    `?graph prov:generatedAtTime ?asOf ; dcterms:source ?sourceName` を
    必須パターンとして持ち、`?dateKind` は `BIND` で必ず束縛される
    ——「欠損は既定値ではなく例外にする」規律(`_parse_ministries`)に揃える。
    """
    return [
        ReleaseFreshness(
            source_name=_str(row, "sourceName"),
            as_of=_str(row, "asOf"),
            date_kind=_str(row, "dateKind"),
        )
        for row in rows
    ]


def _parse_naive_sum_vs_entry_only(rows: list[Row]) -> list[NaiveSumVsEntryOnly]:
    return [
        NaiveSumVsEntryOnly(
            fiscal_year=_int(row, "y"),
            naive_sum=_int(row, "naiveSum"),
            entry_only=_int(row, "entryOnly"),
            block_count=_int(row, "blockCount"),
        )
        for row in rows
    ]


def _parse_request_exactly_granted(rows: list[Row]) -> list[RequestExactlyGranted]:
    return [
        RequestExactlyGranted(
            request_fiscal_year=_int(row, "requestYear"),
            requested_both=_int(row, "requestedBoth"),
            initial_both=_int(row, "initialBoth"),
            projects_in_both_years=_int(row, "projectsInBothYears"),
            exact_matches=_int(row, "exactMatches"),
        )
        for row in rows
    ]


def build_overview(client: KGClient, base_uri: str, queries_dir: Path) -> OverviewResponse:
    raw: dict[str, list[Row]] = {}
    for key, filename in OVERVIEW_QUERIES.items():
        sparql = (queries_dir / filename).read_text(encoding="utf-8")
        raw[key] = client.query(sparql)
    return OverviewResponse(
        computed_at=datetime.now(UTC).isoformat(),
        sources={key: filename for key, filename in OVERVIEW_QUERIES.items()},
        ministries=_parse_ministries(raw["ministries"], base_uri),
        budget_and_execution=_parse_budget_and_execution(raw["budget_and_execution"]),
        request_and_initial=_parse_request_and_initial(raw["request_and_initial"]),
        recipient_identification=_parse_recipient_identification(
            raw["recipient_identification"], base_uri
        ),
        type_counts=_parse_type_counts(raw["type_counts"]),
        government_paid=_parse_government_paid(raw["government_paid"]),
        money_through_stages=_parse_money_through_stages(raw["money_through_stages"], base_uri),
        release_freshness=_parse_release_freshness(raw["release_freshness"]),
        naive_sum_vs_entry_only=_parse_naive_sum_vs_entry_only(raw["naive_sum_vs_entry_only"]),
        request_exactly_granted=_parse_request_exactly_granted(raw["request_exactly_granted"]),
    )
