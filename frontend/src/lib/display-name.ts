// 画面に出す1行の名前を決める、唯一の場所(裁定B108)。
//
// **規則は3段**:
//   1. 表示名(`skos:prefLabel`)があればそれを出す
//   2. 無くて「見分けのための属性」があれば、**述語のラベルを添えて**出す
//      (例「予算年度 2024」)
//   3. どちらも無ければ「(表示名なし)」と言う
//
// **2段目は名前の合成ではない。** 表示名の出所はオントロジー側だけ、という
// 裁定B78/B88は「フロントが名前をこしらえること」を禁じている。ここが出すのは
// APIが返した述語と値の対であり、**述語のラベルを必ず一緒に出す**ことで
// 「これは属性であって名前ではない」と読める形にしてある。述語の日本語も
// `labels.json`(オントロジー由来)から引く——文言をこちらで作らない。
//
// **なぜ必要になったか**: `AnnualBudget` は一次データに固有の名前を持たない
// ので `skos:prefLabel` が無い。本番の府省グラフでは100ノードのうち17件が
// この型で、**すべて同じ「表示名なし」として並んでいた**(2026-09-13実測)。
// 年度はKGにあるのに、画面が使えていなかった。
import type { components } from "../api/openapi-types";
import { predicateLabel } from "../labels";

type DescribingValue = components["schemas"]["DescribingValue"];

/** 表示名も見分けのための属性も無いときの文言。 */
export const NO_LABEL = "(表示名なし)";

/** 名前を出せる最小限の形。`EntityRef`・`EntityDetailResponse`・グラフのノードが満たす。 */
export interface Nameable {
  readonly label: string | null;
  readonly described_by?: DescribingValue | null;
}

/** 見分けのための属性を「述語のラベル 値」にする。 */
export function describingText(described: DescribingValue): string {
  return `${predicateLabel(described.predicate)} ${described.value}`;
}

/**
 * 画面に出す1行。上の3段の規則をそのまま実装する。
 *
 * `described_by` はAPIが `label === null` のときだけ入れる(`models.py` の
 * `DescribingValue` 参照)。ここでも `label` を優先するので、仮に両方
 * 入っていても表示名が勝つ。
 */
export function displayName(ref: Nameable): string {
  if (ref.label !== null && ref.label !== undefined) return ref.label;
  if (ref.described_by) return describingText(ref.described_by);
  return NO_LABEL;
}

/**
 * その1行が**表示名なのか、属性で見分けているだけなのか**。
 *
 * 画面側がスタイルや `aria` の言い回しを変えたいときに使う——
 * 「名前ではない」ことを視覚的にも示せるようにしておく。
 */
export function isDescribedByAttribute(ref: Nameable): boolean {
  return (ref.label === null || ref.label === undefined) && Boolean(ref.described_by);
}
