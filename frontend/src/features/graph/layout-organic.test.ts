// `layoutOrganic`(点と線の力学配置。裁定B114)のテスト。
//
// **旧ForceAtlas2が本番で全ノードNaNになった型を、ここでも第一の検査にする**
// (裁定B112。切断された成分のホップが`Infinity`になったのが原因だった)。
// この配置はホップを使わないので同じ形では壊れないが、**壊れていないことを
// 検査で固定する**。
import { describe, expect, it } from "vitest";
import type { GraphModel, ModelEdge, ModelNode } from "./graph-model";
import { arcBetween, labelOffsets, layoutOrganic, radiusForDegree } from "./layout-organic";
import type { PlacedNode } from "./types";

function node(id: string, degree = 0): ModelNode {
  return {
    id,
    idPath: id,
    type: "BudgetProject",
    label: id,
    describedBy: null,
    axis: undefined,
    laneKey: "what",
    hop: 0,
    degree,
    hasMore: false,
  };
}

function edge(source: string, target: string, predicate = "rel"): ModelEdge {
  return { key: `${source} ${predicate} ${target} g/1`, source, target, predicate, graph: "g/1" };
}

function model(nodes: ModelNode[], edges: ModelEdge[]): GraphModel {
  return { centerId: nodes[0]?.id ?? "", nodes, edges };
}

/** 反復回数を下げて速く回す(決定性は回数を固定していることから来る)。 */
const FAST = { ticks: 60 };

describe("layoutOrganic", () => {
  it("ノードが0件なら空の結果(描かない)", () => {
    const laid = layoutOrganic(model([], []), FAST);
    expect(laid.nodes).toEqual([]);
    expect(laid.edges).toEqual([]);
  });

  it("座標にNaNが出ない(旧力学配置が本番で全ノードNaNになった型)", () => {
    const laid = layoutOrganic(
      model([node("a", 1), node("b", 1), node("iso")], [edge("a", "b")]),
      FAST,
    );
    for (const n of laid.nodes) {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
      expect(Number.isFinite(n.w)).toBe(true);
    }
    expect(laid.edges.every((e) => !/NaN|Infinity/.test(e.d))).toBe(true);
  });

  it("**切断された成分も置く**(到達できないノードを落とさない)", () => {
    const laid = layoutOrganic(
      model(
        [node("a", 1), node("b", 1), node("c", 1), node("d", 1), node("lonely")],
        [edge("a", "b"), edge("c", "d")],
      ),
      FAST,
    );
    expect(laid.nodes.map((n) => n.id).sort()).toEqual(["a", "b", "c", "d", "lonely"]);
  });

  it("**決定的**: 同じモデルを2回渡すと座標が完全に一致する", () => {
    const nodes = [node("a", 2), node("b", 1), node("c", 1), node("d", 2), node("e")];
    const edges = [edge("a", "b"), edge("a", "c"), edge("d", "b"), edge("d", "c")];
    const first = layoutOrganic(model(nodes, edges), FAST);
    // 入力の順序を変えても同じ(id順に並べ替えてから計算する)。
    const second = layoutOrganic(model([...nodes].reverse(), [...edges].reverse()), FAST);
    expect(second.nodes.map((n) => [n.id, n.x, n.y])).toEqual(
      first.nodes.map((n) => [n.id, n.x, n.y]),
    );
  });

  it("すべて円として返す(`shape: dot`)", () => {
    const laid = layoutOrganic(model([node("a", 1), node("b", 1)], [edge("a", "b")]), FAST);
    expect(laid.nodes.every((n) => n.shape === "dot")).toBe(true);
    // 外接矩形は正方形(円なので幅と高さが等しい)。
    expect(laid.nodes.every((n) => n.w === n.h)).toBe(true);
  });

  it("レーンの見出しは出さない(型で決めた列を見せない)", () => {
    const laid = layoutOrganic(model([node("a", 1), node("b", 1)], [edge("a", "b")]), FAST);
    expect(laid.lanes).toEqual([]);
  });

  it("円は次数が多いほど大きい(ハブが大きく見える)", () => {
    expect(radiusForDegree(0)).toBeLessThan(radiusForDegree(4));
    expect(radiusForDegree(4)).toBeLessThan(radiusForDegree(25));
    // 上限があり、1つのハブが画面を占めない。
    expect(radiusForDegree(10_000)).toBeLessThan(radiusForDegree(4) + 20);
  });

  it("円どうしが重ならない(`forceCollide`が効いている)", () => {
    const nodes = Array.from({ length: 12 }, (_, i) => node(`n${i}`, 1));
    const edges = Array.from({ length: 11 }, (_, i) => edge(`n${i}`, `n${i + 1}`));
    const laid = layoutOrganic(model(nodes, edges), { ticks: 400 });
    for (let i = 0; i < laid.nodes.length; i += 1) {
      for (let j = i + 1; j < laid.nodes.length; j += 1) {
        const a = laid.nodes[i]!;
        const b = laid.nodes[j]!;
        const dist = Math.hypot(a.x + a.w / 2 - (b.x + b.w / 2), a.y + a.h / 2 - (b.y + b.h / 2));
        expect(dist).toBeGreaterThan((a.w + b.w) / 2 - 1);
      }
    }
  });

  it("自己ループは描かない(点になって意味を持たない)", () => {
    const laid = layoutOrganic(
      model([node("a", 2), node("b", 1)], [edge("a", "b"), edge("a", "a")]),
      FAST,
    );
    expect(laid.edges).toHaveLength(1);
  });

  it("同じ2点を結ぶ辺が複数あれば、経路を変えて重ねない", () => {
    const laid = layoutOrganic(
      model([node("a", 2), node("b", 2)], [edge("a", "b", "p1"), edge("a", "b", "p2")]),
      FAST,
    );
    expect(laid.edges).toHaveLength(2);
    expect(laid.edges[0]!.d).not.toBe(laid.edges[1]!.d);
    // 2本目は曲線になる(1本目は直線)。
    expect(laid.edges[0]!.d).not.toContain("Q");
    expect(laid.edges[1]!.d).toContain("Q");
  });
});

describe("arcBetween", () => {
  function dot(id: string, cx: number, cy: number, r: number): PlacedNode {
    return {
      id,
      idPath: id,
      type: "BudgetProject",
      label: id,
      describedBy: null,
      axis: undefined,
      laneKey: "what",
      hop: 0,
      degree: 1,
      hasMore: false,
      shape: "dot",
      x: cx - r,
      y: cy - r,
      w: r * 2,
      h: r * 2,
    };
  }

  it("**両端を半径分縮める**(矢印が円の内側に隠れない)", () => {
    const a = dot("a", 0, 0, 10);
    const b = dot("b", 100, 0, 10);
    expect(arcBetween(a, b)).toBe("M 10 0 L 90 0");
  });

  it("同じ位置にある2点でも壊れない(0除算にしない)", () => {
    const a = dot("a", 50, 50, 10);
    const b = dot("b", 50, 50, 10);
    expect(arcBetween(a, b)).not.toMatch(/NaN/);
  });
});

describe("labelOffsets", () => {
  function at(id: string, x: number, y: number): PlacedNode {
    return {
      id,
      idPath: id,
      type: "BudgetProject",
      label: id,
      describedBy: null,
      axis: undefined,
      laneKey: "what",
      hop: 0,
      degree: 1,
      hasMore: false,
      shape: "dot",
      x,
      y,
      w: 26,
      h: 26,
    };
  }

  it("離れているラベルはずらさない", () => {
    const offsets = labelOffsets([at("a", 0, 0), at("b", 0, 200)], new Set(["a", "b"]));
    expect(offsets.get("a")).toBe(0);
    expect(offsets.get("b")).toBe(0);
  });

  it("**近すぎるラベルは下へ逃がす**", () => {
    const offsets = labelOffsets([at("a", 0, 0), at("b", 0, 4)], new Set(["a", "b"]));
    expect(offsets.get("a")).toBe(0);
    expect(offsets.get("b")).toBeGreaterThan(0);
  });

  it("横に十分離れていれば、縦が近くてもずらさない(重ならないため)", () => {
    const offsets = labelOffsets([at("a", 0, 0), at("b", 400, 4)], new Set(["a", "b"]));
    expect(offsets.get("b")).toBe(0);
  });

  it("ラベルを出さないノードは対象にしない", () => {
    const offsets = labelOffsets([at("a", 0, 0), at("b", 0, 4)], new Set(["a"]));
    expect(offsets.has("b")).toBe(false);
  });
});
