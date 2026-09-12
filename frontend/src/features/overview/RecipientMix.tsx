// トップページ再設計・第5節「支払先はどこまで特定できているか」。
//
// `recipient_identification`(CQ17。4区分)を積み上げ帯1本にする。
// **区分の表示名は手で書かない。** `enumValueLabel("recipientMatchCategory",
// category)`(`labels.ts`)で引く——APIは`label`を返さない
// (`RecipientIdentification`のdocstring参照)。
import type { JSX } from "react";
import type { RecipientIdentification } from "../../api/client";
import { formatAmountFull, formatAmountRounded } from "../../format";
import { enumValueLabel } from "../../labels";
import { recipientCountForCategory, recipientTotalAmount, sourceCitation } from "../../lib/overview-format";

export interface RecipientMixProps {
  rows: RecipientIdentification[];
  sources: Record<string, string>;
}

// 積み上げ帯の色。軸色を再利用せず、良い(特定できた)ほど濃い/はっきりした
// 色にする——このリポジトリは新しい色体系を増やさない方針(裁定B105/B106)
// なので、既存の`--ok`(良好)・`--muted`系トーンの濃淡だけを使う。
const CATEGORY_TONE: Readonly<Record<string, string>> = {
  resolved: "var(--ok)",
  bundled: "var(--axis-agent)",
  sentinel_or_nonexistent_houjin_bangou: "var(--muted)",
  unresolved: "var(--signal)",
};

export function RecipientMix({ rows, sources }: RecipientMixProps): JSX.Element {
  if (rows.length === 0) {
    return <p className="jg-sm jg-muted">支払先の照合区分のデータがありません。</p>;
  }
  const citation = sourceCitation(sources, "recipient_identification");
  const total = recipientTotalAmount(rows);
  const unresolvedCount = recipientCountForCategory(rows, "unresolved");

  return (
    <div className="jg-stack jg-stack--4">
      {citation ? <p className="jg-xs jg-muted">{citation}</p> : null}
      <div className="jg-recipient-bar" role="img" aria-label="支払先の照合区分ごとの金額の割合">
        {rows.map((r) => {
          const pct = total > 0 ? (r.total_amount / total) * 100 : 0;
          return (
            <span
              key={r.category}
              className="jg-recipient-bar__seg"
              style={{ width: `${pct}%`, background: CATEGORY_TONE[r.category] ?? "var(--surface-3)" }}
              title={`${enumValueLabel("recipientMatchCategory", r.category)} ${formatAmountFull(r.total_amount)}(${pct.toFixed(1)}%)`}
            />
          );
        })}
      </div>
      <ul className="jg-recipient-legend">
        {rows.map((r) => {
          const pct = total > 0 ? (r.total_amount / total) * 100 : null;
          return (
            <li key={r.category} className="jg-recipient-legend__item">
              <span
                className="jg-chip__dot"
                style={{ background: CATEGORY_TONE[r.category] ?? "var(--surface-3)" }}
                aria-hidden="true"
              />
              <span className="jg-sm">{enumValueLabel("recipientMatchCategory", r.category)}</span>
              <span className="jg-num jg-sm">{pct !== null ? `${pct.toFixed(1)}%` : "—"}</span>
              <span className="jg-num jg-sm jg-muted" title={formatAmountFull(r.total_amount)}>
                {formatAmountRounded(r.total_amount)}
              </span>
              <span className="jg-sm jg-muted">{r.expenditure_count.toLocaleString("ja-JP")}件</span>
            </li>
          );
        })}
      </ul>
      <p className="jg-sm jg-ink2">
        割合は金額です。お金の行き先が個人まで辿れないのは、一次データがそう作られているからです——年金受給者や求職者は個人であり、少額の支払先は政府が「その他」としてまとめて公表しています。
        {unresolvedCount !== null ? (
          <> 名前から法人を特定できなかったのは{unresolvedCount.toLocaleString("ja-JP")}件だけです。</>
        ) : null}
      </p>
    </div>
  );
}
