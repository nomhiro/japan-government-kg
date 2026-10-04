import type { OverviewResponse } from "../../api/client";
import { displayName } from "../../lib/display-name";
import { latestFiscalYear, ministriesForFiscalYear, sourceCitation } from "../../lib/overview-format";
import { routeToHash } from "../../router";
import { ThemeEntrances } from "./ThemeEntrances";
import "./explore.css";

/** 問いは編集上の入口。事実・対象の名前・リンクはAPI応答から取る。 */
export function Discovery({ data, primary = false }: { data?: OverviewResponse; primary?: boolean }) {
  const year = latestFiscalYear(data?.ministries ?? []);
  const ministries = ministriesForFiscalYear(data?.ministries ?? [], year)
    .sort((a, b) => displayName(a).localeCompare(displayName(b), "ja"));
  const Heading = primary ? "h1" : "h2";
  return (
    <section className="jg-discovery jg-stack jg-stack--4" aria-label="調べる入口">
      <div className="jg-row jg-row--between">
        <div>
          <p className="jg-eyebrow">何が行われ、どんな主体・制度とつながるか</p>
          <Heading className={primary ? "jg-h1" : "jg-h2"}>政府の活動と、関わる組織・制度を辿る</Heading>
        </div>
        <a className="jg-btn" href={routeToHash({ name: "search", q: "" })}>名前・キーワードで探す →</a>
      </div>
      <p className="jg-sm jg-muted">検索語が決まっていなくても、テーマや組織から始められます。活動の根拠、所管、つながる事業を調べ、必要なときに予算や支出へ進めます。</p>
      <ThemeEntrances />
      {ministries.length ? (
        <details className="jg-discovery-catalog">
          <summary>府省から選ぶ</summary>
          <p className="jg-xs jg-muted">この一覧は{year}年度の予算集計に現れる府省です。府省・行政機関全体を網羅するものではありません。府省名順に表示しています。</p>
          <ul className="jg-discovery-ministries">
            {ministries.map((m) => (
              <li key={m.id_path}>
                <a href={routeToHash({ name: "explore", center: m.id_path })}>
                  <strong>{displayName(m)}</strong>
                  <span>記録された事業 {m.project_count}件</span>
                </a>
              </li>
            ))}
          </ul>
          <p className="jg-xs jg-muted">{sourceCitation(data?.sources ?? {}, "ministries")}</p>
        </details>
      ) : null}
      <div className="jg-row jg-row--between">
        <a href={routeToHash({ name: "explore" })}>府省のつながりを開く →</a>
        <a href={routeToHash({ name: "data" })}>収録範囲と一次資料を確認する →</a>
      </div>
    </section>
  );
}
