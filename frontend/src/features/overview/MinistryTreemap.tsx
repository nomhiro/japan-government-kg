// トップページ再設計・第2節「府省: ツリーマップ(23タイル、面積∝予算額)」。
//
// **旧画面(23本の細い縦棒。青と灰色の2色)をやめ、面積で見せる。**
// 「厚生労働省が全体の74.6%」という集中の事実は、縦棒の並びでは伝わらない
// ——面積比なら1目で分かる(`treemap.ts`のsquarified treemap。線形。
// 対数にしない=集中の事実を消さない、という既存の判断はここでも守る)。
//
// **色は`--axis-agent`(Ministry/Organizationが属する6軸)の濃淡。**
// 新しい色体系を作らない——このアプリの色はオントロジーの6軸である
// (tokens.cssのコメント参照)。
import type { JSX } from "react";
import { useState } from "react";
import type { MinistryBudget } from "../../api/client";
import { formatAmountFull, formatAmountRounded } from "../../format";
import { navigate } from "../../router";
import {
  ministryDisplayName,
  scaleExcludingTopNote,
  sourceCitation,
  sumMinistryBudgets,
} from "../../lib/overview-format";
import { squarifiedTreemap } from "./treemap";

export interface MinistryTreemapProps {
  ministries: MinistryBudget[];
  fiscalYear: number | null;
  sources: Record<string, string>;
}

type Scale = "all" | "rest";

const VIEWBOX_WIDTH = 1200;
const VIEWBOX_HEIGHT = 440;

/** タイルの中に府省名を出せるだけの大きさがあるか(概算。日本語の全角文字を想定)。 */
function fitsLabel(width: number, height: number, text: string, charWidth = 15): boolean {
  return height >= 34 && width - 12 >= text.length * charWidth;
}

function fitsAmount(width: number, height: number, text: string, charWidth = 11): boolean {
  return height >= 56 && width - 12 >= text.length * charWidth;
}

export function MinistryTreemap({ ministries, fiscalYear, sources }: MinistryTreemapProps): JSX.Element {
  const [scale, setScale] = useState<Scale>("all");

  if (ministries.length === 0) {
    return <p className="jg-sm jg-muted">府省ごとの予算額のデータがありません。</p>;
  }

  const top = ministries[0]!;
  // **降順を信じる(既存`views/overview.ts`と同じ方針)。** `ministries`は
  // CQ15(`ORDER BY DESC(?totalBudget)`)が既に予算額の降順で返す——ここで
  // 並べ替え直さない。
  const shown = scale === "rest" ? ministries.slice(1) : ministries;

  const rects =
    shown.length > 0
      ? squarifiedTreemap(
          shown.map((m) => ({ id: m.id_path, value: m.total_budget })),
          VIEWBOX_WIDTH,
          VIEWBOX_HEIGHT,
        )
      : [];
  const byIdPath = new Map(shown.map((m) => [m.id_path, m]));
  const maxValue = shown.length > 0 ? shown[0]!.total_budget : 0;

  const yearSuffix = fiscalYear !== null ? `(${fiscalYear}年度)` : "";
  const scaleSource = sourceCitation(sources, "ministries");
  const totalBudget = sumMinistryBudgets(ministries);

  function goToMinistry(idPath: string): void {
    navigate({ name: "entity", idPath });
  }

  return (
    <div className="jg-stack jg-stack--4">
      <div className="jg-row jg-row--between">
        <p className="jg-sm jg-ink2">
          タイルの面積は予算額そのままです(対数にしていません)。クリックするとその府省のページへ移ります。
        </p>
        {ministries.length >= 2 ? (
          <div className="jg-toggle" role="group" aria-label="目盛り">
            <button type="button" aria-pressed={scale === "all"} onClick={() => setScale("all")}>
              全{ministries.length}府省
            </button>
            <button type="button" aria-pressed={scale === "rest"} onClick={() => setScale("rest")}>
              {ministryDisplayName(top)}を除いて見る
            </button>
          </div>
        ) : null}
      </div>

      {scale === "rest" && ministries.length >= 2 ? (
        <p className="jg-sm jg-ink2" aria-live="polite">
          {scaleExcludingTopNote({
            excludedName: ministryDisplayName(top),
            excludedBudget: top.total_budget,
            totalBudget,
            newMaxName: ministryDisplayName(ministries[1]!),
            restCount: ministries.length - 1,
            totalCount: ministries.length,
          })}
        </p>
      ) : null}

      <div className="jg-treemap">
        <svg
          className="jg-treemap__svg"
          viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
          role="group"
          aria-label={`府省ごとの予算額${yearSuffix}`}
          preserveAspectRatio="xMidYMid meet"
        >
          {rects.map((r) => {
            const ministry = byIdPath.get(r.id);
            if (!ministry) return null;
            const name = ministryDisplayName(ministry);
            const amountText = formatAmountRounded(ministry.total_budget);
            const fullTitle = `${name} ${formatAmountFull(ministry.total_budget)}・${ministry.project_count.toLocaleString("ja-JP")}事業`;
            const opacity = maxValue > 0 ? 0.35 + 0.65 * (ministry.total_budget / maxValue) : 1;
            const showLabel = fitsLabel(r.width, r.height, name);
            const showAmount = showLabel && fitsAmount(r.width, r.height, amountText);
            return (
              <g key={r.id} className="jg-treemap__tile">
                <rect
                  x={r.x}
                  y={r.y}
                  width={Math.max(0, r.width - 1)}
                  height={Math.max(0, r.height - 1)}
                  fill="var(--axis-agent)"
                  fillOpacity={opacity}
                  tabIndex={0}
                  role="button"
                  aria-label={fullTitle}
                  onClick={() => goToMinistry(ministry.id_path)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      goToMinistry(ministry.id_path);
                    }
                  }}
                >
                  <title>{fullTitle}</title>
                </rect>
                {showLabel ? (
                  <text x={r.x + 8} y={r.y + 20} className="jg-treemap__name" aria-hidden="true">
                    {name}
                  </text>
                ) : null}
                {showAmount ? (
                  <text x={r.x + 8} y={r.y + 40} className="jg-treemap__amount jg-num" aria-hidden="true">
                    {amountText}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>

      <ul className="jg-treemap__mobile-list">
        {shown.map((m) => (
          <li key={m.id_path}>
            <button type="button" className="jg-treemap__mobile-row" onClick={() => goToMinistry(m.id_path)}>
              <span className="jg-treemap__mobile-name">{ministryDisplayName(m)}</span>
              <span
                className="jg-treemap__mobile-bar"
                style={{ width: `${maxValue > 0 ? Math.min(100, (m.total_budget / maxValue) * 100) : 0}%` }}
              />
              <span className="jg-treemap__mobile-amount jg-num">{formatAmountRounded(m.total_budget)}</span>
            </button>
          </li>
        ))}
      </ul>

      {scaleSource ? <p className="jg-xs jg-muted">{scaleSource}</p> : null}
    </div>
  );
}
