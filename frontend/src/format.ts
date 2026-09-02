// 画面全体で使う小さな表示ヘルパー。KGの値(法令名・機関名等)は利用者の
// 入力ではないが、外部データである以上エスケープを徹底する。
import type { Provenance } from "./api/client";

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
