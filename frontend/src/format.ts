// 画面全体で使う小さな表示ヘルパー。KGの値(法令名・機関名等)は利用者の
// 入力ではないが、外部データである以上エスケープを徹底する。
//
// **この中でも`describePathResult`は特に重い(裁定B82(3))。** `found=false`を
// 「無い」と描くのは、このプロジェクトが繰り返し最も重い欠陥として扱って
// きた「報告が嘘をつく」型そのもの——DOM組み立てから分離した純粋関数にして、
// `format.test.ts`で「文言の選択」だけを直接検査できるようにしてある。
import type { AttributeValue, EntityDetailResponse, PathResponse, Provenance } from "./api/client";
import { enumValueLabel } from "./labels";

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
 * 近傍グラフのステータス行(「ノードN件・辺M件」+ 打ち切りの通知)。
 *
 * **このプロジェクトで最も高くついた欠陥の型(欠陥型10・裁定B77: 打ち切りが
 * 黙って消える)をここでも再発させないため**、DOM組み立て(`graph.ts`)から
 * 分離した純粋関数にし、`format.test.ts`で打ち切りフラグごとの文言を直接
 * 検査できるようにする(`truncationNotice`/`describePathResult`と同じ方針)。
 * `nodes_truncated`/`edges_truncated`/`fanout_truncated_nodes`のいずれかが
 * 真でも、この関数を呼ぶ側がその結果を捨てれば通知は出ない——「表示する側が
 * 必ず使う」ことは`graph.test.ts`のDOM側の確認(実ブラウザ確認)で担保する。
 */
export interface NeighborhoodStatus {
  nodeCount: number;
  edgeCount: number;
  nodesTruncated: boolean;
  edgesTruncated: boolean;
  fanoutTruncatedCount: number;
}

export function neighborhoodStatusText(s: NeighborhoodStatus): string {
  return (
    `ノード${s.nodeCount}件・辺${s.edgeCount}件` +
    (s.nodesTruncated ? "(ノード数の上限で一部を省略)" : "") +
    (s.edgesTruncated ? "(エッジ数の上限で一部を省略)" : "") +
    (s.fanoutTruncatedCount > 0
      ? `。${s.fanoutTruncatedCount}件のノードで分岐数の上限に達しています(⋯マーク。クリックで続きを見られます)`
      : "")
  );
}

/**
 * 属性の1つの値(`AttributeValue`)を、値そのものと出典リンクで描く。
 *
 * 元は`entity.ts`にあった(裁定B82(4a))。グラフのノードをクリックしたときの
 * 概要パネル(裁定B92のE-1)でも同じ描画が必要になったため、DOM文字列を
 * 組み立てる純粋関数としてここに移し、両方の画面から使う——手書きの重複を
 * 避ける(このモジュールの他の関数と同じ「表示の判断を1箇所に置く」方針)。
 *
 * **`available === false`のときは空リンクを描かない**(`provenanceHtml`が
 * 既に守る。裁定B82)。`graphs`が複数あれば(同じ値を複数の名前付きグラフが
 * 主張する場合)一次資料リンクを複数並べる。
 *
 * **`pred`(述語のローカル名)を`enumValueLabel`に渡して列挙型の許容値を
 * 日本語に引き当てる**(裁定B82(4b))。列挙型を範囲に持たない述語の値は
 * 表示名が無いので`av.value`がそのまま返る(フォールバックは
 * `enumValueLabel`自身が持つ)。
 */
export function attributeValueHtml(
  pred: string,
  av: AttributeValue,
  graphs: EntityDetailResponse["graphs"],
): string {
  const provenances = av.graphs.map((g) => provenanceHtml(graphs[g])).join(" / ");
  return (
    `<span class="jgkg-attr-value">${esc(enumValueLabel(pred, av.value))}</span>` +
    `<span class="jgkg-muted jgkg-attr-prov"> (${provenances})</span>`
  );
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
