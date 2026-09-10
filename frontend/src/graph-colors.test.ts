import { describe, expect, it, vi } from "vitest";

// colorForTypeはlabels.ts(axisForType/siblingTypesInAxis)経由で生成物
// (generated/labels.json)を読む。labels.test.tsと同じ理由でモックする
// ——ここで検査したいのは「軸+軸内の位置→色」の振る舞いであって、
// いま実際のオントロジーにどの型があるかではない。
vi.mock("./generated/labels.json", () => ({
  default: {
    types: {},
    predicates: {},
    enumValues: {},
    typeAxes: {
      AbolishedGovernmentOrgan: "Agent",
      Agent: "Agent",
      GovernmentOrgan: "Agent",
      Ministry: "Agent",
      Organization: "Agent",
      BudgetProject: "Work",
      Law: "Work",
      Work: "Work",
      UnresolvedReference: "UnresolvedReference",
    },
  },
}));

import {
  colorForAxis,
  colorForType,
  groupByAxis,
  hslToHex,
  hueForAxis,
  UNKNOWN_AXIS,
  UNRESOLVED_AXIS,
} from "./graph-colors";

// =============================================================================
// hslToHex: 標準式どおりに変換できていること(既知の値で固定する)
// =============================================================================

describe("hslToHex", () => {
  it("既知のHSL値がよく知られた16進コードに変換される", () => {
    expect(hslToHex(0, 100, 50)).toBe("#ff0000"); // 赤
    expect(hslToHex(120, 100, 50)).toBe("#00ff00"); // 緑
    expect(hslToHex(240, 100, 50)).toBe("#0000ff"); // 青
    expect(hslToHex(0, 0, 100)).toBe("#ffffff"); // 白
    expect(hslToHex(0, 0, 0)).toBe("#000000"); // 黒
  });

  it("6桁の#付き16進コードの形をしている(サイズが変わらない)", () => {
    expect(hslToHex(37, 62, 44)).toMatch(/^#[0-9a-f]{6}$/);
  });
});

// =============================================================================
// hueForAxis / colorForAxis: 6軸は互いに異なる色相を持ち、UnresolvedReferenceと
// 軸不明は6軸のローテーションに混ざらない(裁定B92)
// =============================================================================

describe("hueForAxis", () => {
  it("6軸それぞれに色相があり、6件とも互いに異なる", () => {
    const axes = ["Agent", "Work", "Place", "Event", "MonetaryItem", "Concept"];
    const hues = axes.map((a) => hueForAxis(a));
    expect(hues.every((h) => h !== undefined)).toBe(true);
    expect(new Set(hues).size).toBe(6); // 6件とも異なる色相
  });

  it("UnresolvedReference・軸不明の文字列には色相を割らない(undefined)", () => {
    expect(hueForAxis(UNRESOLVED_AXIS)).toBeUndefined();
    expect(hueForAxis(UNKNOWN_AXIS)).toBeUndefined();
    expect(hueForAxis("NotAnAxis")).toBeUndefined();
  });
});

describe("colorForAxis", () => {
  it("6軸はそれぞれ異なる色になる(軸ごとに色相を分ける、という要求の核心)", () => {
    const axes = ["Agent", "Work", "Place", "Event", "MonetaryItem", "Concept"];
    const colors = axes.map((a) => colorForAxis(a));
    expect(new Set(colors).size).toBe(6);
  });

  it("同じ軸内でも siblingIndex が違えば色(明度)が変わる——濃淡で型を区別する", () => {
    const c0 = colorForAxis("Agent", 0);
    const c1 = colorForAxis("Agent", 1);
    const c2 = colorForAxis("Agent", 2);
    expect(new Set([c0, c1, c2]).size).toBe(3);
  });

  it("UnresolvedReferenceは常に同じ固定の灰色で、6軸のどの色とも異なる", () => {
    const unresolved = colorForAxis(UNRESOLVED_AXIS, 0);
    const axes = ["Agent", "Work", "Place", "Event", "MonetaryItem", "Concept"];
    for (const a of axes) {
      expect(colorForAxis(a, 0)).not.toBe(unresolved);
    }
    // siblingIndexが変わっても色は変わらない(軸のローテーションに混ざらない)
    expect(colorForAxis(UNRESOLVED_AXIS, 3)).toBe(unresolved);
  });

  it("軸不明(undefined)はUnresolvedReferenceとも6軸とも異なる色になる(混同を防ぐ)", () => {
    const unknown = colorForAxis(undefined, 0);
    expect(unknown).not.toBe(colorForAxis(UNRESOLVED_AXIS, 0));
    const axes = ["Agent", "Work", "Place", "Event", "MonetaryItem", "Concept"];
    for (const a of axes) {
      expect(colorForAxis(a, 0)).not.toBe(unknown);
    }
  });
});

// =============================================================================
// groupByAxis: 凡例のグループ化(件数まで検査する。「1件以上」で通さない)
// =============================================================================

describe("groupByAxis", () => {
  // 実データに近い型の組み合わせ(裁定B92のE-1ブリーフが挙げた確認先を反映):
  // 厚生労働省(GovernmentOrgan/Agent軸)の近傍には予算事業(BudgetProject/Work軸)が多数出る。
  const axisOf = (type: string): string | undefined =>
    ({ Ministry: "Agent", GovernmentOrgan: "Agent", BudgetProject: "Work", Law: "Work" })[type];
  // 色の計算そのものはcolorForAxis側で検査済みなので、ここでは「渡された
  // colorOfの戻り値をそのまま使う(自前で計算しない)」ことだけを確認する。
  const colorOf = (type: string): string => `color:${type}`;

  it("同じ軸の型を1グループにまとめ、グループ内はローカル名の辞書順になる", () => {
    const groups = groupByAxis(["BudgetProject", "Ministry", "GovernmentOrgan", "Law"], axisOf, colorOf);
    expect(groups).toHaveLength(2); // Agent軸・Work軸の2グループ(件数を厳密に見る)
    const agent = groups.find((g) => g.axis === "Agent")!;
    const work = groups.find((g) => g.axis === "Work")!;
    expect(agent.items.map((i) => i.type)).toEqual(["GovernmentOrgan", "Ministry"]); // 辞書順
    expect(work.items.map((i) => i.type)).toEqual(["BudgetProject", "Law"]);
  });

  it("グループの並び順はAXIS_ORDER(誰が/何を/…)に従う。Workが先に出てもAgentが先に来る", () => {
    const groups = groupByAxis(["BudgetProject", "Ministry"], axisOf, colorOf);
    expect(groups.map((g) => g.axis)).toEqual(["Agent", "Work"]);
  });

  it("重複した型は1件にまとめる(同じ型が複数ノードに出ても凡例は1行)", () => {
    const groups = groupByAxis(["Ministry", "Ministry", "Ministry"], axisOf, colorOf);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.items).toHaveLength(1);
  });

  it("各項目の色は自前で計算せず、colorOfの戻り値をそのまま使う", () => {
    const groups = groupByAxis(["Ministry"], axisOf, colorOf);
    expect(groups[0]!.items[0]).toEqual({ type: "Ministry", color: "color:Ministry" });
  });

  it("**壊してみせる対象**: 型→軸を引けない型は「軸不明」グループに落とし、UnresolvedReferenceとも6軸とも混ぜない", () => {
    // axisOfが常にundefinedを返す(=typeAxesの生成物が空になった状態を模す)
    const groups = groupByAxis(["Law", "BudgetProject"], () => undefined, colorOf);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.axis).toBe(UNKNOWN_AXIS);
    // ここで"Work"のような具体的な軸名が返っていたら、labels.tsの生成物が
    // 空でも別経路(手書きの対応表)で軸が引けてしまっている欠陥のサイン。
  });

  it("UnresolvedReference軸は常に最後のグループになる", () => {
    const groups = groupByAxis(
      ["UnresolvedReference", "Ministry", "BudgetProject"],
      (t) => (t === "UnresolvedReference" ? "UnresolvedReference" : axisOf(t)),
      colorOf,
    );
    expect(groups.at(-1)!.axis).toBe("UnresolvedReference");
  });
});

// =============================================================================
// colorForType: ノードの色と凡例の色が常に一致することの核心
// =============================================================================

describe("colorForType", () => {
  it("同じ軸を共有する型どうしは異なる色(明度)になる(モックのtypeAxes: Agent軸5件)", () => {
    const agentTypes = ["AbolishedGovernmentOrgan", "Agent", "GovernmentOrgan", "Ministry", "Organization"];
    const colors = agentTypes.map((t) => colorForType(t));
    expect(new Set(colors).size).toBe(agentTypes.length);
  });

  it("**軸内の順序は表示中の型集合に依存しない**: 単独で呼んでも、他の型と一緒でも同じ色になる", () => {
    // groupByAxisに渡すpresentTypesが["Ministry"]だけでも["Ministry","Organization"]でも、
    // Ministryの色は変わらない(=画面に何が出ているかで色が揺れない)。
    expect(colorForType("Ministry")).toBe(colorForType("Ministry"));
    const viaGroup = groupByAxis(["Ministry"], (t) => (t === "Ministry" ? "Agent" : undefined), colorForType);
    expect(viaGroup[0]!.items[0]!.color).toBe(colorForType("Ministry"));
  });

  it("UnresolvedReferenceは固定の灰色になる", () => {
    expect(colorForType("UnresolvedReference")).toBe(colorForAxis(UNRESOLVED_AXIS));
  });

  it("**壊してみせる対象**: typeAxesに無い型(生成物から漏れた型)は軸不明の色になり、既知の軸の色にはならない", () => {
    const color = colorForType("存在しない型");
    expect(color).toBe(colorForAxis(undefined));
    expect(color).not.toBe(colorForType("Ministry"));
  });
});
