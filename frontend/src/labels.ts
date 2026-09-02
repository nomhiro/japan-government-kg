// 専門用語を避けた表示名(仕様§9.2)。オントロジー側にある`dcterms:title`
// (裁定B78)から`scripts/export-frontend-labels.py`が抜き出した生成物を読む
// だけで、対応表をここで手書きしない(D-5ブリーフ「表示名はオントロジー側に
// 用意済み。手書きしないこと」)。
import labelsJson from "./generated/labels.json";

interface Labels {
  types: Record<string, string>;
  predicates: Record<string, string>;
}

const labels = labelsJson as Labels;

/**
 * 型のローカル名(例: "BudgetProject")の日本語表示名。
 *
 * **表示名が無い場合はローカル名をそのまま返す(手書きで補わない)。**
 * オントロジーに`title:`が足されていない型が将来増えても、ここで
 * フォールバック文字列を捏造すると「表示名が用意されている体で見える」
 * 偽の充足になる——ローカル名(技術名)がそのまま出ることで、
 * 表示名が未整備であることが分かる形にする。
 */
export function typeLabel(localName: string): string {
  return labels.types[localName] ?? localName;
}

/** 述語のローカル名(例: "basisLaw")の日本語表示名。`typeLabel`と同じ方針。 */
export function predicateLabel(localName: string): string {
  return labels.predicates[localName] ?? localName;
}
