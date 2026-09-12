// 画面共通の小部品(裁定B106)。
// 色・寸法は tokens.css の変数から。ここで値を直書きしない。
import type { JSX, ReactNode } from "react";
import type { Provenance } from "../api/client";
import { formatAmountFull, formatAmountRounded } from "../format";
import { axisBgVarForType, axisColorVarForType, displayType } from "../lib/ontology-view";
import { licenseSummary, sourceLines } from "./provenance";
import "./ui.css";

// --- 面と帯 ---------------------------------------------------------------

export function Band({
  children,
  sunken = false,
  ruled = false,
  wide = false,
  full = false,
  id,
}: {
  children: ReactNode;
  sunken?: boolean;
  ruled?: boolean;
  wide?: boolean;
  full?: boolean;
  id?: string;
}): JSX.Element {
  const band = ["jg-band", sunken ? "jg-band--sunken" : "", ruled ? "jg-band--ruled" : ""]
    .filter(Boolean)
    .join(" ");
  const inner = ["jg-inner", wide ? "jg-inner--wide" : "", full ? "jg-inner--full" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={band} id={id}>
      <div className={inner}>{children}</div>
    </div>
  );
}

/**
 * 節。見出しと、その節の数字がどのCQの答えかを並べて出す(裁定B103)。
 * `note` は「この数字の限界」を質的な文で書く場所(裁定B103追記6)。
 */
export function Section({
  title,
  eyebrow,
  source,
  note,
  actions,
  children,
}: {
  title: string;
  eyebrow?: string;
  source?: string | null;
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}): JSX.Element {
  return (
    <section className="jg-section jg-stack jg-stack--4">
      <div className="jg-row jg-row--between jg-section__head">
        <div className="jg-stack jg-stack--2">
          {eyebrow ? <span className="jg-eyebrow">{eyebrow}</span> : null}
          <h2 className="jg-h2">{title}</h2>
        </div>
        {actions ? <div className="jg-row jg-row--tight">{actions}</div> : null}
      </div>
      {source ? <p className="jg-xs jg-muted">{source}</p> : null}
      {note ? <div className="jg-sm jg-ink2 jg-section__note">{note}</div> : null}
      {children}
    </section>
  );
}

// --- データを持つ小部品 ---------------------------------------------------

/** 型バッジ。地と文字は6軸の色(オントロジー由来)。 */
export function TypeBadge({ type, size = "md" }: { type: string; size?: "md" | "sm" }): JSX.Element {
  return (
    <span
      className={`jg-badge${size === "sm" ? " jg-badge--sm" : ""}`}
      style={{ color: axisColorVarForType(type), background: axisBgVarForType(type) }}
    >
      {displayType(type)}
    </span>
  );
}

/**
 * 金額。丸めた値を見せ、正確な値は `title` と読み上げに必ず添える
 * (丸めを単独で出さない。既存 `views/overview.ts` と同じ規律)。
 */
export function Amount({
  yen,
  className,
}: {
  yen: number | null | undefined;
  className?: string;
}): JSX.Element {
  if (yen === null || yen === undefined || !Number.isFinite(yen)) {
    return <span className="jg-muted">—</span>;
  }
  const exact = formatAmountFull(yen);
  return (
    <span className={`jg-num${className ? ` ${className}` : ""}`} title={exact}>
      {formatAmountRounded(yen)}
      <span className="jg-sr">({exact})</span>
    </span>
  );
}

/** 大きく1つの数字を語る枠。 */
export function Stat({
  label,
  value,
  unit,
  note,
  tone = "plain",
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  note?: ReactNode;
  tone?: "plain" | "caution";
}): JSX.Element {
  return (
    <div className={`jg-stat${tone === "caution" ? " jg-stat--caution" : ""}`}>
      <span className="jg-eyebrow">{label}</span>
      <span className="jg-display jg-num">
        {value}
        {unit ? <span className="jg-stat__unit">{unit}</span> : null}
      </span>
      {note ? <span className="jg-sm jg-ink2">{note}</span> : null}
    </div>
  );
}

/** 数字の限界を書く枠。隠さないための場所(裁定B96/B97/B103追記6)。 */
export function Caveat({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="jg-caveat jg-sm" role="note">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d="M12 9v4M12 17h.01M10.3 3.9 2.6 17.3A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.7L13.7 3.9a2 2 0 0 0-3.4 0z" />
      </svg>
      <div>{children}</div>
    </div>
  );
}

/** 「下限である」等の短い印。数字のすぐ横に置く。 */
export function LimitTag({ children }: { children: ReactNode }): JSX.Element {
  return <span className="jg-limit-tag">{children}</span>;
}

/**
 * 打ち切りの告知(裁定B82)。`truncated` が偽なら何も描かない。
 * 「全部ではない」ことを黙って隠さないための部品。
 */
export function Truncation({
  truncated,
  limit,
  what,
  children,
}: {
  truncated: boolean;
  limit: number;
  what: string;
  children?: ReactNode;
}): JSX.Element | null {
  if (!truncated) return null;
  return (
    <p className="jg-trunc jg-sm">
      {what}は多いため、先頭{limit}件だけを出しています。{children}
    </p>
  );
}

/**
 * 節の出典を1行にまとめて出す(裁定B86)。
 * リンクの文字は一次資料URLのホスト名(URLから取り出した事実)。
 * `available: false` のグラフはリンクを描かず、取れていないことを書く。
 */
export function SourceNote({
  graphs,
  onlyGraphs,
  prefix = "出典",
}: {
  graphs: Readonly<Record<string, Provenance>> | undefined;
  onlyGraphs?: readonly string[];
  prefix?: string;
}): JSX.Element | null {
  const lines = sourceLines(graphs, onlyGraphs);
  if (lines.length === 0) return null;
  const license = licenseSummary(lines);
  return (
    <p className="jg-xs jg-muted jg-source">
      {prefix}:{" "}
      {lines.map((l, i) => (
        <span key={l.graph}>
          {i > 0 ? " ・ " : ""}
          {l.available && l.url ? (
            <a href={l.url} target="_blank" rel="noopener noreferrer">
              {l.host ?? "一次資料"}
            </a>
          ) : (
            <span className="jg-source__missing">出典が取れていない</span>
          )}
          {l.fetchedOn ? `(${l.fetchedOn} 取得)` : ""}
        </span>
      ))}
      {license ? <span className="jg-source__license"> — {license}</span> : null}
    </p>
  );
}

// --- 状態 -----------------------------------------------------------------

export function Loading({ label = "読み込み中" }: { label?: string }): JSX.Element {
  return (
    <div className="jg-loading" role="status">
      <span className="jg-loading__bar" />
      <span className="jg-sm jg-muted">{label}…</span>
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="jg-error" role="alert">
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }): JSX.Element {
  return <p className="jg-sm jg-muted">{children}</p>;
}
