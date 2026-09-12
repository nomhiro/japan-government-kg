// オントロジーを「見える形」に写すための表示側の決まり(裁定B92・B106)。
//
// **型→軸はオントロジーから導出する**(`labels.ts` の `axisForType`。
// `frontend_labels.py` が `rdfs:subClassOf` を辿って生成する)。ここで決めるのは
// その先の表示上の2つだけである:
//
// 1. **軸→CSS変数**: 色の値そのものは `styles/tokens.css`(--axis-*)にあり、
//    `graph-colors.ts` の `colorForAxis()` と同じ設計(210°から60°刻み)。
//    グラフ・バッジ・凡例がすべて同じ色体系を共有する。
// 2. **型→レーン**: 軸は「何であるか」を表す。レーンは「**資金と権限の流れの
//    どこにいるか**」を表す。両者は直交する —— 例えば Ministry と Organization は
//    どちらも Agent 軸だが、流れの中では「所管」と「支払先」で別の位置にある。
//    この並び(根拠→所管→事業→段→支出→支払先)は `schema/budget.yaml` の
//    実際の述語の向き(Expenditure--project-->BudgetProject、
//    Expenditure--recipient-->Organization、ExpenditureBlock--fundedBy-->…)から
//    読んだものであり、ここで新しい意味を発明していない。

import { axisForType, typeLabel } from "../labels";
import { UNRESOLVED_AXIS } from "../graph-colors";

/** 凡例と絞り込みチップの並び。`schema/core.yaml` 冒頭の6軸の並びに従う。 */
export const AXIS_ORDER: readonly string[] = [
  "Agent",
  "Work",
  "Event",
  "MonetaryItem",
  "Place",
  "Concept",
  UNRESOLVED_AXIS,
];

const AXIS_CSS: Readonly<Record<string, string>> = {
  Agent: "agent",
  Work: "work",
  Place: "place",
  Event: "event",
  MonetaryItem: "money",
  Concept: "concept",
  [UNRESOLVED_AXIS]: "unresolved",
};

/** 軸の前景色を指す CSS 変数式。引けない軸は無彩色に落とす(色を捏造しない)。 */
export function axisColorVar(axis: string | undefined): string {
  const key = axis ? AXIS_CSS[axis] : undefined;
  return `var(--axis-${key ?? "unresolved"})`;
}

/** 軸の背景色(バッジの地)を指す CSS 変数式。 */
export function axisBgVar(axis: string | undefined): string {
  const key = axis ? AXIS_CSS[axis] : undefined;
  return `var(--axis-${key ?? "unresolved"}-bg)`;
}

export function axisColorVarForType(type: string): string {
  return axisColorVar(axisForType(type));
}

export function axisBgVarForType(type: string): string {
  return axisBgVar(axisForType(type));
}

// ---------------------------------------------------------------------------
// レーン(流れの位置)
// ---------------------------------------------------------------------------

export interface Lane {
  /** 安定した識別子(URLやテストで使う)。 */
  readonly key: string;
  /** 画面に出す見出し。 */
  readonly title: string;
  /** このレーンに入る型のローカル名。 */
  readonly types: readonly string[];
}

/**
 * 左から右へ「根拠 → 所管 → 事業 → 段・年度 → 支出 → 支払先」。
 * これは資金と権限の流れの順序であり、この順に並べると
 * `Ministry --(ministry)-- BudgetProject --(project)-- Expenditure
 *  --(recipient)-- Organization` が一本の流れとして読める。
 */
export const LANES: readonly Lane[] = [
  { key: "basis", title: "根拠", types: ["Law", "LawRevision"] },
  {
    key: "who",
    title: "所管",
    types: ["Ministry", "GovernmentOrgan", "AbolishedGovernmentOrgan"],
  },
  { key: "what", title: "事業", types: ["BudgetProject"] },
  {
    key: "stage",
    title: "段・年度",
    types: ["ExpenditureBlock", "AnnualBudget", "IndirectCost"],
  },
  { key: "payment", title: "支出", types: ["Expenditure"] },
  { key: "recipient", title: "支払先", types: [] },
];

/** レーンに属さない型を置く脇のストリップ。 */
export const ASIDE_LANE: Lane = {
  key: "aside",
  title: "その他",
  types: ["UnresolvedReference", "Place", "Concept"],
};

const LANE_OF_TYPE: Readonly<Record<string, string>> = Object.fromEntries(
  LANES.flatMap((lane) => lane.types.map((t) => [t, lane.key] as const)),
);

/**
 * 型だけから決まるレーン。決められない型(`Organization` や未知の型)は
 * `undefined` を返す —— 呼び出し側がグラフの構造で補う(`assignLanes`)。
 *
 * `Organization` を型で固定しないのは、同じ型が流れの別の位置に現れるため。
 * 実データでは `Expenditure --recipient--> Organization` が 54,768 本ある一方、
 * `Expenditure --recipient--> GovernmentOrgan` も 1,839 本ある(裁定B30の
 * 支出先限定の帰結)。「支払先かどうか」は型ではなく辺が決める。
 */
export function laneKeyForType(type: string): string | undefined {
  return LANE_OF_TYPE[type];
}

/** レーンの並び順(`LANES` のindex)。脇のストリップは最後。 */
export function laneIndex(laneKey: string): number {
  const i = LANES.findIndex((l) => l.key === laneKey);
  return i === -1 ? LANES.length : i;
}

export function laneTitle(laneKey: string): string {
  return LANES.find((l) => l.key === laneKey)?.title ?? ASIDE_LANE.title;
}

/** 型の表示名。`labels.json` 由来(フロントで合成しない。裁定B78/B88)。 */
export function displayType(type: string): string {
  return typeLabel(type);
}
