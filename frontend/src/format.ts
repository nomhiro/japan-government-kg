// 画面全体で使う小さな表示ヘルパー(純粋関数だけ)。
//
// **HTML文字列を返す関数はここに置かない。** React化(裁定B106)で
// `esc`/`provenanceHtml`/`attributeValueHtml`/`chatSourceHtml`/
// `toolCallLogEntryHtml`/`truncationNotice` は不要になったので削除した ——
// エスケープはReactがやり、出典・打ち切り・型バッジの描画は
// `components/ui.tsx` の部品(`SourceNote`/`Truncation`/`TypeBadge`)が持つ。
// それらが縛っていた不変条件(available=false で空リンクを描かない、
// truncated=false で何も出さない等)は部品のテストが引き継いでいる。
//
// **`describePathResult`は特に重い(裁定B82(3))。** `found=false`を
// 「無い」と描くのは、このプロジェクトが繰り返し最も重い欠陥として扱って
// きた「報告が嘘をつく」型そのもの——描画から分離した純粋関数にして、
// `format.test.ts`で「文言の選択」だけを直接検査できるようにしてある。
import type { PathResponse } from "./api/client";

/**
 * 円を「兆/億/万円」に丸めて表示する(第1層。裁定B103)。
 *
 * **`docs/mockups/top-page.html`の`jpShort`(レビュー済み)と同じ境界・
 * 同じ丸め方をそのまま使う**——このプロジェクトは合意した見た目を実装が
 * 独自に作り直さない(トップページ第1層ブリーフ「作り直さず写すこと」)。
 *
 * **丸めた値を出す側(呼び出し元)は、正確な値(`formatAmountFull`)を
 * 必ず併記すること**(モックのコメント: 「丸めた値を出すときは正確な値も
 * 併記する」)——この関数自体は文字列を1つ返すだけなので、その規律は
 * 呼び出し側(`views/overview.ts`)が守る。
 *
 * **負値は絶対値で桁を判定し、符号を戻す**(修正ラウンド1・レビューQ6)。
 * `>=`だけの分岐だと負値は必ず最後の分岐に落ち、"-518,000,000,000円"の
 * ような未丸めの生の桁が出る——第4節(次のタスク)以降、事業ごとの補正額
 * (裁定S7の「必ず増えるとは限らない」)には実在する負値であり、隣の
 * 正の値と桁が揃わないのは読みにくい。
 *
 * **非有限値(`NaN`/`Infinity`)はクラッシュせず文字列化する**(モックの
 * `yen()`の`isFinite`ガードと同じ意図)。第1層のCQの答えに非有限値が来る
 * ことは無いはずだが、共用関数(`format.ts`)として他画面から呼ばれても
 * 例外を投げない。
 */
export function formatAmountRounded(yen: number): string {
  if (!Number.isFinite(yen)) return String(yen);
  const sign = yen < 0 ? "-" : "";
  const n = Math.abs(yen);
  if (n >= 1e12) return `${sign}${(n / 1e12).toFixed(1)}兆円`;
  if (n >= 1e11) return `${sign}${Math.round(n / 1e8).toLocaleString("ja-JP")}億円`;
  if (n >= 1e8) return `${sign}${(n / 1e8).toFixed(1)}億円`;
  if (n >= 1e4) return `${sign}${(n / 1e4).toFixed(0)}万円`;
  return `${sign}${n.toLocaleString("ja-JP")}円`;
}

/**
 * 円をそのまま(桁区切り+「円」)表示する。`docs/mockups/top-page.html`の
 * `yen()`/`jpFull()`と同じ形——`formatAmountRounded`と併記して、丸めた値の
 * 裏にある正確な値を示すために使う。
 *
 * `toLocaleString`は負値の符号をそのまま桁区切りの前に置くので、
 * `formatAmountRounded`と違って符号を別途組み立て直す必要は無い
 * (修正ラウンド1・レビューQ6)。非有限値はクラッシュせず文字列化する。
 */
export function formatAmountFull(yen: number): string {
  if (!Number.isFinite(yen)) return String(yen);
  return `${yen.toLocaleString("ja-JP")}円`;
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

