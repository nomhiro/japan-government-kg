// 画面全体で使う小さな表示ヘルパー。KGの値(法令名・機関名等)は利用者の
// 入力ではないが、外部データである以上エスケープを徹底する。
//
// **この中でも`describePathResult`は特に重い(裁定B82(3))。** `found=false`を
// 「無い」と描くのは、このプロジェクトが繰り返し最も重い欠陥として扱って
// きた「報告が嘘をつく」型そのもの——DOM組み立てから分離した純粋関数にして、
// `format.test.ts`で「文言の選択」だけを直接検査できるようにしてある。
import type { PathResponse, Provenance } from "./api/client";

export function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * 出典(一次資料へのリンクと取得日時。仕様§9.2)を描く。
 *
 * `available === false`(裁定D-4)のときは**空リンクを描かない**——
 * 「出典が取れていない」と明示する(D-5ブリーフ拘束条件(d))。空文字列の
 * `source`をそのまま`<a href="">`にすると、リンクらしき見た目だけが残り、
 * 「取れていない」ことが黙って隠れる。
 */
export function provenanceHtml(prov: Provenance | undefined): string {
  if (!prov || !prov.available) {
    return '<span class="jgkg-muted">出典が取れていない</span>';
  }
  return (
    `<a href="${esc(prov.source)}" target="_blank" rel="noopener noreferrer">一次資料</a>` +
    `<span class="jgkg-muted"> (取得: ${esc(prov.fetched_on)} / ${esc(prov.license)})</span>`
  );
}

/** 件数系の打ち切り通知(仕様§9.2「黙って切らない」)。truncatedが真のときだけ表示する。 */
export function truncationNotice(truncated: boolean, limit: number, what: string): string {
  if (!truncated) return "";
  return `<p class="jgkg-notice">${esc(what)}が${limit}件を超えています。すべてではなく先頭${limit}件を表示しています。</p>`;
}

/**
 * パス探索の`found=false`をどう読むかの判定(裁定B77の族。裁定B82(3))。
 *
 * **`exhaustive=true`のときだけ「経路は存在しない」と言ってよい。**
 * それ以外(`budget_exhausted`/`depth_limited`/`fanout_truncated`のいずれかで
 * 打ち切った)は「この深さ・この予算では見つからなかった」であって
 * 「無い」ではない——空の結果だけを返すと利用者は後者だと読んでしまう。
 */
export type PathResultDescription =
  | { kind: "found" }
  | { kind: "not-found-exhaustive" }
  | { kind: "not-found-inconclusive"; reasons: string[] };

export function describePathResult(res: PathResponse): PathResultDescription {
  if (res.found) return { kind: "found" };
  if (res.exhaustive) return { kind: "not-found-exhaustive" };

  const reasons: string[] = [];
  if (res.budget_exhausted) reasons.push(`訪問予算(${res.visit_budget}件)を使い切りました`);
  if (res.depth_limited) reasons.push(`探索の深さ上限(${res.max_depth})に達しました`);
  if (res.fanout_truncated) reasons.push("分岐数の上限で一部の経路を切り落としました");
  return { kind: "not-found-inconclusive", reasons };
}
