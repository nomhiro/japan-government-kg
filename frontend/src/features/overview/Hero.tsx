// トップページ再設計・第1節「3つの数字で国のお金を語る」。
//
// **出す数字はすべて`/overview`の答えである(裁定B103)。** ここでの
// 計算は「どの行を選ぶか」(最新年度・最新fiscal_year)と「引いた値を
// そのまま見せる」(執行率・重複額)だけで、CQに無い新しい集計は作らない
// ——`overview-format.ts`の関数だけを通す(`views/overview.ts`の
// `renderHead`/`renderSpending`と同じ計算をJSXで書き直したもの)。
//
// **3つの数字を矢印で結ばない(裁定B96/B97)。** 予算(当初予算・最新年度)・
// 執行(歳出予算現額に対する率・過去の年度)・支出(国が自ら支払った額・
// 前年度の執行実績)は年度も基準も異なる——並べて見せるが、「予算→執行→
// 支出」という単一の流れがあるように描かない。
import type { JSX } from "react";
import type {
  BudgetAndExecution,
  GovernmentPaidTotal,
  MinistryBudget,
  NaiveSumVsEntryOnly,
  TypeCount,
} from "../../api/client";
import { Amount, Caveat, LimitTag, Stat } from "../../components/ui";
import { typeLabel } from "../../labels";
import {
  sourceCitation,
  sumMinistryBudgets,
  typeInstanceCount,
} from "../../lib/overview-format";

export interface HeroProps {
  fiscalYear: number | null;
  currentMinistries: MinistryBudget[];
  budgetAndExecution: BudgetAndExecution[];
  governmentPaid: GovernmentPaidTotal[];
  naiveSumVsEntryOnly: NaiveSumVsEntryOnly[];
  typeCounts: TypeCount[];
  sources: Record<string, string>;
  computedAt: string;
}

/**
 * `computed_at`(ISO8601。プロセスが起動時に集計した時刻)を読める形にする。
 *
 * **「鮮度」と呼ばない(この応答のdocstringが明言する: KGの鮮度ではない)。**
 * タイムゾーン変換をせず、応答にある値をそのまま切り詰めて出す
 * ——ロケール依存の`toLocaleString`はテスト環境と本番で結果が変わりうる
 * ため使わない(決定的であることを優先する)。
 */
export function formatComputedAt(iso: string): string {
  const isUtc = iso.endsWith("Z") || iso.endsWith("+00:00");
  const base = iso.replace("T", " ").replace(/(\.\d+)?(Z|[+-]\d{2}:\d{2})$/, "");
  return isUtc ? `${base}(UTC)` : base;
}

/** 執行率の範囲(裁定B99: 分母は歳出予算現額。当初予算だと100%を超えて見える)。 */
export function executionRatePercents(rows: BudgetAndExecution[]): number[] {
  return rows
    .filter((r) => r.total_budget_available > 0 && r.executed_amount > 0)
    .map((r) => (r.executed_amount / r.total_budget_available) * 100);
}

export function Hero({
  fiscalYear,
  currentMinistries,
  budgetAndExecution,
  governmentPaid,
  naiveSumVsEntryOnly,
  typeCounts,
  sources,
  computedAt,
}: HeroProps): JSX.Element {
  const totalBudget = sumMinistryBudgets(currentMinistries);
  const execPercents = executionRatePercents(budgetAndExecution);
  const execRange =
    execPercents.length > 0
      ? execPercents.length === 1
        ? `${execPercents[0]!.toFixed(1)}%`
        : `${Math.min(...execPercents).toFixed(1)}〜${Math.max(...execPercents).toFixed(1)}%`
      : null;

  const paidRow = fiscalYear !== null ? governmentPaid.find((r) => r.fiscal_year === fiscalYear) : undefined;
  const naiveRow = fiscalYear !== null ? naiveSumVsEntryOnly.find((r) => r.fiscal_year === fiscalYear) : undefined;
  const duplicate = naiveRow && paidRow ? naiveRow.naive_sum - paidRow.government_paid : null;

  const projectCount = typeInstanceCount(typeCounts, "BudgetProject");
  const lawCount = typeInstanceCount(typeCounts, "Law");
  const orgCount = typeInstanceCount(typeCounts, "Organization");
  const expenditureCount = typeInstanceCount(typeCounts, "Expenditure");

  const scaleSource = sourceCitation(sources, "ministries");
  const execSource = sourceCitation(sources, "budget_and_execution");
  const paidSource = sourceCitation(sources, "naive_sum_vs_entry_only", "government_paid");
  const scaleCountSource = sourceCitation(sources, "type_counts");

  return (
    <div className="jg-hero jg-stack jg-stack--5">
      <p className="jg-xs jg-muted">
        この画面の数字を集計した時刻: {formatComputedAt(computedAt)}
        <span className="jg-sr">(ナレッジグラフ本体の鮮度ではなく、このAPIプロセスが起動時に集計した時刻です)</span>
      </p>

      <div className="jg-grid jg-grid--3 jg-hero__stats">
        <div className="jg-stack jg-stack--2">
          <Stat
            label={fiscalYear !== null ? `${fiscalYear}年度 当初予算` : "当初予算"}
            value={<Amount yen={totalBudget} />}
          />
          {scaleSource ? <p className="jg-xs jg-muted">{scaleSource}</p> : null}
        </div>

        <div className="jg-stack jg-stack--2">
          <Stat label="執行率" value={execRange ?? "—"} note="歳出予算現額に対する" />
          {execSource ? <p className="jg-xs jg-muted">{execSource}</p> : null}
        </div>

        <div className="jg-stack jg-stack--2">
          <Stat
            tone="caution"
            label="国が自ら支払った額"
            value={
              paidRow ? (
                <>
                  <Amount yen={paidRow.government_paid} /> <LimitTag>下限</LimitTag>
                </>
              ) : (
                "—"
              )
            }
          />
          {paidRow ? (
            <Caveat>
              素朴に支出の記録をすべて足すと
              {naiveRow ? <Amount yen={naiveRow.naive_sum} /> : "—"}
              になりますが、同じお金を段ごとに数えた重複(
              {duplicate !== null ? <Amount yen={duplicate} /> : "—"}
              )を除いた額です。この額自体も両方向に誤差があります。
            </Caveat>
          ) : null}
          {paidSource ? <p className="jg-xs jg-muted">{paidSource}</p> : null}
        </div>
      </div>

      <Caveat>
        この3つの数字は矢印でつながっていません。予算・執行・支出は年度も基準も違います(支出額は前年度の執行実績です)。それぞれ別の器として読んでください。
      </Caveat>

      <div className="jg-row jg-hero__scale" aria-label="国のお金と施策の規模">
        <span className="jg-hero__scale-item">
          <b className="jg-num">{projectCount !== null ? projectCount.toLocaleString("ja-JP") : "—"}</b>
          <span className="jg-xs jg-muted">{typeLabel("BudgetProject")}</span>
        </span>
        <span className="jg-hero__scale-item">
          <b className="jg-num">{currentMinistries.length.toLocaleString("ja-JP")}</b>
          <span className="jg-xs jg-muted">府省</span>
        </span>
        <span className="jg-hero__scale-item">
          <b className="jg-num">{lawCount !== null ? lawCount.toLocaleString("ja-JP") : "—"}</b>
          <span className="jg-xs jg-muted">{typeLabel("Law")}</span>
        </span>
        <span className="jg-hero__scale-item">
          <b className="jg-num">{orgCount !== null ? orgCount.toLocaleString("ja-JP") : "—"}</b>
          <span className="jg-xs jg-muted">{typeLabel("Organization")}</span>
        </span>
        <span className="jg-hero__scale-item">
          <b className="jg-num">{expenditureCount !== null ? expenditureCount.toLocaleString("ja-JP") : "—"}</b>
          <span className="jg-xs jg-muted">{typeLabel("Expenditure")}</span>
        </span>
      </div>
      {scaleCountSource ? <p className="jg-xs jg-muted">{scaleCountSource}</p> : null}
    </div>
  );
}
