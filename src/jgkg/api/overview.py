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
(1,438,620トリプル)で実測した値は、この7本のCQを走らせるのに
**コールド7.282秒・ウォーム2.772秒**(コンテナ再起動直後/ウォーム)。
第1層は全訪問者が最初に開く画面なので、リクエストごとに払える代償ではない。
また`minReplicas=1`/`maxReplicas=1`でFusekiとAPIが同じレプリカを共有して
おり、Fuseki側にクエリのタイムアウトがまだ無い(既知の未処理事項)。

**訂正**: このモジュールの計画段階の草稿はこの数字を3.999秒/3.114秒と
書いていたが、これは実測前の仮の値だった。team-leadが本番と同じ索引で
実測した値(7.282秒/2.772秒)に置き換える——このプロジェクトが繰り返し
扱う「測っていない数字を書く」欠陥をここで再発させないための訂正。
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jgkg.api.kgclient import KGClient, Row, Term
from jgkg.api.models import (
    BudgetAndExecution,
    GovernmentPaidTotal,
    MinistryBudget,
    MoneyThroughStage,
    OverviewResponse,
    RecipientIdentification,
    RequestAndInitial,
    TypeCount,
)

# **`_id_path`は`queries.py`のプライベート関数だが、改名せずそのまま使う
# (team-leadから判断を委ねられた点。報告に理由を書く)。** `queries.py`の
# 既存5箇所(`_id_path`と検索して分かる: search_entities・get_entity_detail・
# _unknown_entity_ref・_hydrate_entity_refs・_entity_exists)のうち3箇所は
# **`id_path`という名前のローカル変数/パラメータを既に持つ**
# (`get_entity_detail(client, base_uri, id_path, limit)`・
# `_entity_exists(client, base_uri, id_path)`)。この関数を`id_path`という
# 公開名に改名すると、そのローカル変数がモジュール関数を覆い隠し
# (`id_path=id_path(base_uri, entity_uri)`は「strはcallableではない」で
# 落ちる)、既存3エンドポイントを壊す。**複製を作らない**という制約の下では、
# 衝突しない別の公開名(例: `derive_id_path`)へ改名して5箇所を直すか、
# このままプライベート名を1箇所からimportするかの二択になる——後者は
# 挙動を一切変えない最小の変更であり、既に安定している`/search`・
# `/entity/{id}`・`/neighborhood/{id}`・`/path`に触れない。
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
}


def _int(row: Row, name: str) -> int:
    """束縛を整数で読む。**未束縛は0ではなく例外にする** ——
    集約の列が欠けているのは実装の誤りであり、0として通すと
    「予算0円」が画面に出る(このプロジェクトの再発欠陥: 欠損を
    既定値に落として静かに間違える)。"""
    term: Term | None = row.get(name)
    if term is None:
        raise ValueError(f"{name} が束縛されていない: {sorted(row)}")
    return int(float(term.value))


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
    """束縛を真偽値で読む。**未束縛はFalseではなく例外にする**(`_int`と同じ理由)。

    rdflib/リモートJSONのどちらでも`xsd:boolean`の字句形は`"true"`/`"false"`
    (rdflibは正規化した字句形を返す)。
    """
    term: Term | None = row.get(name)
    if term is None:
        raise ValueError(f"{name} が束縛されていない: {sorted(row)}")
    return term.value == "true"


def _parse_ministries(rows: list[Row], base_uri: str) -> list[MinistryBudget]:
    out: list[MinistryBudget] = []
    for row in rows:
        iri = _text(row, "ministry")
        if iri is None:
            continue  # 府省が未束縛の行は集約の対象外(OPTIONALの相手ではない)
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

    **`?sheetYear`は使わない(意図的な省略。気になる点として報告する)。**
    CQ14は`?sheetYear ?budgetYear ...`の9列を返すが、`BudgetAndExecution`は
    `budget_fiscal_year`(=`?budgetYear`)しか持たない——CQ14のヘッダが
    警告する「将来2つのシートが同じ`budgetYear`について食い違う」ケースが
    起きたとき、この応答だけを見る利用者は食い違いに気づけない
    (CQの生の答えには`sheetYear`が残っているので、消えるのはこの型に
    詰め替えた後だけである)。
    """
    return [
        BudgetAndExecution(
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


def _parse_money_through_stages(rows: list[Row]) -> list[MoneyThroughStage]:
    return [
        MoneyThroughStage(
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
        money_through_stages=_parse_money_through_stages(raw["money_through_stages"]),
    )
