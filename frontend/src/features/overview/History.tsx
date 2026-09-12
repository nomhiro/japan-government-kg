// トップページ再設計・第4節「年度の推移: 予算と執行(5年)」+「要求と査定」。
//
// **分母は歳出予算現額(裁定B99)。** 当初予算を分母にすると執行率が
// 100%を超えて見える年度がある——`total_budget_available`(補正予算・
// 前年度繰越・予備費を含む「その年度に実際に使える額」)を全体とし、
// `executed_amount`を塗りにする。既存`overview-format.ts`の
// `distinctSheetYears`/`historyRowYearLabel`/`historySheetYearNote`/
// `mostRecentRow`をそのまま使う——年度の対応付け・複数シート混在の扱いを
// このファイルで作り直さない。
//
// **要求と査定は必ず母集団の注記を添える(裁定B103追記5)。** 「全体では
// ほぼ満額」と「事業ごとの完全一致は32.7〜44.0%程度」は矛盾ではなく、
// 見ている対象が違う——これを両方出さないと誤読させる。
import type { JSX } from "react";
import type { BudgetAndExecution, RequestExactlyGranted } from "../../api/client";
import { Amount, Caveat } from "../../components/ui";
import { formatAmountFull } from "../../format";
import {
  barWidthPercent,
  distinctSheetYears,
  exactMatchRatioPercent,
  historyRowYearLabel,
  historySheetYearNote,
  mostRecentRow,
  percentRangeText,
  requestGrantedPercent,
  requestVsGrantedRows,
  sourceCitation,
} from "../../lib/overview-format";

export interface HistoryProps {
  budgetAndExecution: BudgetAndExecution[];
  requestExactlyGranted: RequestExactlyGranted[];
  sources: Record<string, string>;
}

export function History({ budgetAndExecution, requestExactlyGranted, sources }: HistoryProps): JSX.Element {
  return (
    <div className="jg-stack jg-stack--7">
      <BudgetExecutionBands rows={budgetAndExecution} sources={sources} />
      <RequestVsGranted rows={requestExactlyGranted} sources={sources} />
    </div>
  );
}

function BudgetExecutionBands({
  rows,
  sources,
}: {
  rows: BudgetAndExecution[];
  sources: Record<string, string>;
}): JSX.Element {
  const citation = sourceCitation(sources, "budget_and_execution");
  if (rows.length === 0) {
    return <p className="jg-sm jg-muted">年度ごとの予算と執行のデータがありません。</p>;
  }
  const sheetYears = distinctSheetYears(rows);
  const maxAvailable = Math.max(...rows.map((r) => r.total_budget_available));
  const latest = mostRecentRow(rows);

  return (
    <div className="jg-stack jg-stack--4">
      <h3 className="jg-h3">予算はいくら付いて、いくら使われたか(5年分)</h3>
      {citation ? <p className="jg-xs jg-muted">{citation}</p> : null}
      <div className="jg-history">
        {rows.map((r) => {
          const widthPct = barWidthPercent(r.total_budget_available, maxAvailable);
          const execPct = barWidthPercent(r.executed_amount, r.total_budget_available);
          const initPct = barWidthPercent(r.initial_budget, r.total_budget_available);
          const rate =
            r.total_budget_available > 0 && r.executed_amount > 0
              ? `${((r.executed_amount / r.total_budget_available) * 100).toFixed(1)}%`
              : "—";
          return (
            <div className="jg-history__row" key={`${r.sheet_year}-${r.budget_fiscal_year}`}>
              <span className="jg-history__year jg-sm">{historyRowYearLabel(r, sheetYears)}</span>
              <span className="jg-history__track" style={{ width: `${widthPct.toFixed(2)}%` }}>
                <span className="jg-history__fill" style={{ width: `${execPct.toFixed(2)}%` }} />
                <span
                  className="jg-history__tick"
                  style={{ left: `${initPct.toFixed(2)}%` }}
                  title={`当初予算 ${formatAmountFull(r.initial_budget)}`}
                />
              </span>
              <span className="jg-history__rate jg-num jg-sm">
                {r.executed_amount > 0 ? rate : "未執行"}
              </span>
            </div>
          );
        })}
      </div>
      <p className="jg-sm jg-ink2">
        帯の全体が歳出予算現額(その年度に実際に使える額)、塗った部分が執行額、縦線が当初予算の位置です。当初予算より使える額が大きいのは、補正予算・前年度からの繰越し・予備費が加わるためです。ただし、これらは事業ごとに見ると負になることもあります(必ず増えるとは限りません)。
        {latest && latest.executed_amount === 0 ? (
          <> {latest.budget_fiscal_year}年度の執行額が「未執行」なのは、まだ執行されていないからです(執行率0%ではありません)。</>
        ) : null}
      </p>
      <p className="jg-sm jg-ink2">{historySheetYearNote(sheetYears)}</p>
    </div>
  );
}

function RequestVsGranted({
  rows,
  sources,
}: {
  rows: RequestExactlyGranted[];
  sources: Record<string, string>;
}): JSX.Element {
  const citation = sourceCitation(sources, "request_exactly_granted");
  const items = requestVsGrantedRows(rows);
  if (items.length === 0) {
    return <p className="jg-sm jg-muted">要求額と当初予算の対応データがありません。</p>;
  }

  const overallPercents = items.map(requestGrantedPercent).filter((p): p is number => p !== null);
  const matchPercents = items.map(exactMatchRatioPercent).filter((p): p is number => p !== null);
  const overallRange = percentRangeText(overallPercents);
  const matchRange = percentRangeText(matchPercents);

  return (
    <div className="jg-stack jg-stack--4">
      <h3 className="jg-h3">いくら要求して、いくら付いたか</h3>
      {citation ? <p className="jg-xs jg-muted">{citation}</p> : null}
      <p className="jg-sm jg-ink2">
        この表は両方の年度に事業として存在するものだけを対象にしています(新規・廃止事業は含みません)。
      </p>
      <div className="jg-request">
        {items.map((r) => {
          const pct = requestGrantedPercent(r);
          const widthPct = pct !== null ? barWidthPercent(pct, 100) : 0;
          return (
            <div className="jg-request__row" key={r.requestYear}>
              <span className="jg-sm">
                {r.requestYear}年度に要求 → {r.grantedYear}年度に付いた
              </span>
              <span className="jg-request__track">
                <span className="jg-request__fill" style={{ width: `${widthPct.toFixed(2)}%` }} />
              </span>
              <span className="jg-num jg-sm">
                <Amount yen={r.requested} /> → <Amount yen={r.initial} />
              </span>
              <span className="jg-num jg-sm">{pct !== null ? `${pct.toFixed(1)}%` : "—"}</span>
              <span className="jg-sm jg-muted">
                完全一致 {r.exactMatches.toLocaleString("ja-JP")}/{r.projectsInBothYears.toLocaleString("ja-JP")}
              </span>
            </div>
          );
        })}
      </div>
      {overallRange !== null ? (
        <Caveat>
          全体では要求の<b>{overallRange}</b>が付いています。ただし
          {matchRange !== null ? (
            <>
              {" "}
              事業ごとに見ると額が完全一致した事業は<b>{matchRange}程度</b>です。
            </>
          ) : null}
          「ほぼ満額」という言い方は全体の話に限ります。事業単位ではそう言えません。
        </Caveat>
      ) : null}
    </div>
  );
}
