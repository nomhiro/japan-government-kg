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
  // 型のローカル名(例:"Ministry")→6軸(またはUnresolvedReference)の
  // ローカル名(例:"Agent")。裁定B92(E-1)。`frontend_labels.py`の
  // `_type_axes`が`rdfs:subClassOf`を`core#Entity`まで辿って導出した
  // 対応表を読むだけで、ここで対応表を手書きしない(再発欠陥1)。
  typeAxes: Record<string, string>;
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

/**
 * 型のローカル名(例: "Ministry")が属する6軸(または"UnresolvedReference")の
 * ローカル名(例: "Agent")。裁定B92(E-1): グラフのノードの色・凡例を
 * オントロジーの6軸から導出するための土台。
 *
 * **手書きの対応表を持たない。** `labelsJson.typeAxes`(生成物)に無い型は
 * `undefined`を返す——ここで「知っている型だけの対応表」を補うと、
 * 生成が壊れて`typeAxes`が空になっても別の経路で軸が引けてしまい、
 * 生成の欠落に気づけなくなる(`labels.test.ts`の「対応表が生成物から
 * 引けなくなると軸も引けなくなる」テストが検査する)。呼び出し側
 * (`graph-colors.ts`)は`undefined`を「軸不明」として扱う。
 */
export function axisForType(localName: string): string | undefined {
  return labels.typeAxes[localName];
}

/**
 * `localName`と同じ軸を共有する型のローカル名一覧(自分自身を含む)を
 * 辞書順で返す。軸を引けない型(`axisForType`が`undefined`)は空配列。
 *
 * **色の決定(`graph-colors.ts`)が「軸内の何番目か」に使う。** ここで
 * 順序を決めることで、同じ型は表示中の他の型が何であっても常に同じ色になる
 * ——「いま画面に出ている型だけを数えて順番を振る」と、後から展開して
 * 新しい型が増えるたびに既存ノードの色が変わってしまう(このプロジェクトが
 * 一度実データで踏んだ「凡例が別画面の型を持ち越す」欠陥〔`graph.ts`の
 * 旧コメント参照〕と同じ種類の「表示が状態に依存して揺れる」問題を、
 * 順序を生成物だけから求めることで避ける)。
 */
export function siblingTypesInAxis(localName: string): string[] {
  const axis = axisForType(localName);
  if (axis === undefined) return [];
  return Object.keys(labels.typeAxes)
    .filter((t) => labels.typeAxes[t] === axis)
    .sort();
}
