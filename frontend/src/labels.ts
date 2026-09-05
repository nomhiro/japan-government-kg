// 専門用語を避けた表示名(仕様§9.2)。オントロジー側にある`dcterms:title`
// (裁定B78)から`scripts/export-frontend-labels.py`が抜き出した生成物を読む
// だけで、対応表をここで手書きしない(D-5ブリーフ「表示名はオントロジー側に
// 用意済み。手書きしないこと」)。
//
// `enumValues`(裁定B82(4b))は列挙型の許容値(`resolved`/`bundled`等)の
// 表示名。述語のローカル名をキーにした`{値: 表示名}`——`jgkg.frontend_labels`
// が`rdfs:range`経由で曖昧さなく解決済みなので、ここでは対応表の1段引きで足りる
// (2段の結合をランタイムで行わない判断の理由は`frontend_labels.py`docstring参照)。
import labelsJson from "./generated/labels.json";

interface Labels {
  types: Record<string, string>;
  predicates: Record<string, string>;
  enumValues: Record<string, Record<string, string>>;
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

/**
 * 列挙型の許容値(例: "resolved")の日本語表示名(裁定B82(4b))。
 *
 * **`predicateLocalName`で名前空間を分けて引く**(値だけでは引かない)。
 * 別の列挙型が将来同じ値文字列を持っても、述語ごとに`enumValues`のキーが
 * 分かれているので衝突しない(`frontend_labels.py`docstringの設計判断参照)。
 * 表示名が無い場合(未翻訳の値、または`predicateLocalName`が列挙型を
 * 持たない述語)は値をそのまま返す——`typeLabel`/`predicateLabel`と同じ
 * フォールバック方針(手書きの対応表で補わない)。
 */
export function enumValueLabel(predicateLocalName: string, value: string): string {
  return labels.enumValues[predicateLocalName]?.[value] ?? value;
}
