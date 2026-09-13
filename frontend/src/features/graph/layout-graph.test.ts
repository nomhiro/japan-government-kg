// `layoutGraph`(構造配置。裁定B112)のテスト。
//
// **旧`layoutForce`が本番で壊れていたことを踏まえた検査を先に置く。**
// 切断された成分のホップ数が`Infinity`になり、初期位置の計算で
// 全ノードの座標が`NaN`になっていた(「AI」の検索44ノード全部が
// `translate(NaN,NaN)`。本番で実測)。**座標にNaNが無いこと**と
// **辺で繋がっていないノードも置かれること**を、この配置の第一の要求にする。
import { describe, expect, it } from "vitest";
import type { GraphModel, ModelEdge, ModelNode } from "./graph-model";
import { layoutGraph, pathThroughPoints } from "./layout-graph";

function node(id: string, type: string, laneKey = "what"): ModelNode {
  return {
    id,
    idPath: id,
    type,
    label: id,
    describedBy: null,
    axis: undefined,
    laneKey,
    hop: 0,
    degree: 0,
    hasMore: false,
  };
}

function edge(source: string, target: string, predicate = "rel"): ModelEdge {
  return { key: `${source} ${predicate} ${target} g/1`, source, target, predicate, graph: "g/1" };
}

function model(nodes: ModelNode[], edges: ModelEdge[]): GraphModel {
  return { centerId: nodes[0]?.id ?? "", nodes, edges };
}

describe("layoutGraph", () => {
  it("座標にNaNが出ない(旧力学配置が本番で全ノードNaNになった欠陥の型)", () => {
    const laid = layoutGraph(
      model([node("a", "BudgetProject"), node("b", "Ministry")], [edge("a", "b")]),
    );
    for (const n of laid.nodes) {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
    }
    expect(laid.edges.every((e) => !/NaN|Infinity/.test(e.d))).toBe(true);
  });

  it("**辺が1本も無いノードも置く**(切断された成分を落とさない)", () => {
    const laid = layoutGraph(
      model(
        [node("a", "BudgetProject"), node("b", "Ministry"), node("iso", "Law")],
        [edge("a", "b")],
      ),
    );
    expect(laid.nodes).toHaveLength(3);
    const iso = laid.nodes.find((n) => n.id === "iso")!;
    expect(Number.isFinite(iso.x)).toBe(true);
    expect(Number.isFinite(iso.y)).toBe(true);
  });

  it("**層は辺から決まる。型では決まらない**", () => {
    // 同じ型が別の層に来ることがある(鎖の途中にいるかどうかで決まる)。
    const laid = layoutGraph(
      model(
        [node("law", "Law"), node("min", "Ministry"), node("prj", "BudgetProject")],
        [edge("law", "min"), edge("min", "prj")],
      ),
    );
    const x = new Map(laid.nodes.map((n) => [n.id, n.x]));
    expect(x.get("law")!).toBeLessThan(x.get("min")!);
    expect(x.get("min")!).toBeLessThan(x.get("prj")!);
  });

  it("同じ型が同じ層に固定されない(型ごとの列を作らない)", () => {
    // `Law` が2つあり、一方は鎖の先頭・もう一方は末尾にいる。
    const laid = layoutGraph(
      model(
        [node("law1", "Law"), node("mid", "Ministry"), node("law2", "Law")],
        [edge("law1", "mid"), edge("mid", "law2")],
      ),
    );
    const x = new Map(laid.nodes.map((n) => [n.id, n.x]));
    expect(x.get("law1")).not.toBe(x.get("law2"));
  });

  it("**レーンの見出しは出さない**(型で決めた列を見せないのが主旨)", () => {
    const laid = layoutGraph(model([node("a", "Law"), node("b", "Ministry")], [edge("a", "b")]));
    expect(laid.lanes).toEqual([]);
  });

  it("**決定的**: 同じモデルを2回渡すと座標が完全に一致する", () => {
    const nodes = [
      node("a", "BudgetProject"),
      node("b", "Ministry"),
      node("c", "Law"),
      node("d", "Organization"),
    ];
    const edges = [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d")];
    const first = layoutGraph(model(nodes, edges));
    // 入力の順序を変えても同じ結果になる(id順に挿入しているため)。
    const second = layoutGraph(model([...nodes].reverse(), [...edges].reverse()));
    expect(second.nodes.map((n) => [n.id, n.x, n.y])).toEqual(
      first.nodes.map((n) => [n.id, n.x, n.y]),
    );
    expect(second.edges.map((e) => e.d)).toEqual(first.edges.map((e) => e.d));
  });

  it("同じ2点を結ぶ別の述語の辺を両方残す(多重辺)", () => {
    const laid = layoutGraph(
      model(
        [node("a", "BudgetProject"), node("b", "Ministry")],
        [edge("a", "b", "ministry"), edge("a", "b", "jurisdiction")],
      ),
    );
    expect(laid.edges).toHaveLength(2);
    expect(new Set(laid.edges.map((e) => e.predicate))).toEqual(
      new Set(["ministry", "jurisdiction"]),
    );
  });

  it("自己ループは層を消費しない(図が横に伸びるだけで何も足さない)", () => {
    const withLoop = layoutGraph(
      model([node("a", "BudgetProject"), node("b", "Ministry")], [edge("a", "b"), edge("a", "a")]),
    );
    const withoutLoop = layoutGraph(
      model([node("a", "BudgetProject"), node("b", "Ministry")], [edge("a", "b")]),
    );
    expect(withLoop.nodes.map((n) => n.x)).toEqual(withoutLoop.nodes.map((n) => n.x));
    // 自己ループ自体は描かない(経路が点になるため)。
    expect(withLoop.edges).toHaveLength(1);
  });

  it("辺の向きは source→target のまま(矢印を反転させない)", () => {
    const laid = layoutGraph(
      model([node("a", "BudgetProject"), node("b", "Ministry")], [edge("a", "b")]),
    );
    expect(laid.edges[0]!.source).toBe("a");
    expect(laid.edges[0]!.target).toBe("b");
    expect(laid.edges[0]!.flip).toBe(false);
  });

  it("幅と高さが内容を包む大きさになる", () => {
    const laid = layoutGraph(
      model([node("a", "Law"), node("b", "Ministry"), node("c", "BudgetProject")], [
        edge("a", "b"),
        edge("b", "c"),
      ]),
    );
    const maxX = Math.max(...laid.nodes.map((n) => n.x + n.w));
    const maxY = Math.max(...laid.nodes.map((n) => n.y + n.h));
    expect(laid.width).toBeGreaterThanOrEqual(maxX);
    expect(laid.height).toBeGreaterThanOrEqual(maxY);
  });
});

describe("pathThroughPoints", () => {
  it("点が無ければ空文字", () => {
    expect(pathThroughPoints([])).toBe("");
  });

  it("点が2つなら直線", () => {
    expect(pathThroughPoints([{ x: 0, y: 0 }, { x: 10, y: 20 }])).toBe("M 0 0 L 10 20");
  });

  it("3点以上は中間点を通る曲線にする(角を立てない)", () => {
    const d = pathThroughPoints([
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 20, y: 10 },
    ]);
    expect(d.startsWith("M 0 0")).toBe(true);
    expect(d).toContain("Q");
    expect(d.endsWith("L 20 10")).toBe(true);
  });

  it("座標は小数第1位までに丸める(`d`が無駄に長くならない)", () => {
    expect(pathThroughPoints([{ x: 1.23456, y: 2.98765 }, { x: 3, y: 4 }])).toBe(
      "M 1.2 3 L 3 4",
    );
  });
});
