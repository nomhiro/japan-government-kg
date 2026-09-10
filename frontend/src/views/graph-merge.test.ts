import { describe, expect, it } from "vitest";
import type { EntityRef, Relationship } from "../api/client";
import { planExpansion } from "./graph-merge";

function ref(id: string, type = "BudgetProject"): EntityRef {
  return { id, id_path: id, type, label: id };
}

function rel(relatedId: string, direction: "outgoing" | "incoming", predicate = "project"): Relationship {
  return { direction, predicate, graph: "g1", related: ref(relatedId) };
}

// =============================================================================
// planExpansion: 展開が追加するノード・辺を決める純粋関数(裁定B92のE-1)。
// **欠陥型10(裁定B77)の再発防止**: 返す辺のsource/targetは必ず
// existingNodeIds∪newNodesのどちらかに含まれる(端点の無い辺を作らない)。
// =============================================================================

describe("planExpansion", () => {
  it("新しい関連先をnewNodesに、辺をedgesに1件ずつ追加する", () => {
    const plan = planExpansion("center", [rel("a", "outgoing")], new Set(["center"]));
    expect(plan.newNodes.map((n) => n.id)).toEqual(["a"]);
    expect(plan.edges).toEqual([{ source: "center", target: "a", predicate: "project", graph: "g1" }]);
  });

  it("direction=incoming のとき、辺の向きは関連先→起点になる", () => {
    const plan = planExpansion("center", [rel("a", "incoming")], new Set(["center"]));
    expect(plan.edges).toEqual([{ source: "a", target: "center", predicate: "project", graph: "g1" }]);
  });

  it("既にグラフにあるノード(existingNodeIds)への関係は、newNodesに含めない(重複してノードを作らない)", () => {
    const plan = planExpansion("center", [rel("already-there", "outgoing")], new Set(["center", "already-there"]));
    expect(plan.newNodes).toEqual([]);
    expect(plan.edges).toHaveLength(1); // 辺は引き続き作る
  });

  it("同じ関連先へ複数の関係があっても、newNodesには1回だけ追加する(辺は関係の数だけ作る)", () => {
    const plan = planExpansion(
      "center",
      [rel("a", "outgoing", "basisLaw"), rel("a", "outgoing", "project")],
      new Set(["center"]),
    );
    expect(plan.newNodes).toHaveLength(1);
    expect(plan.edges).toHaveLength(2);
  });

  it("**欠陥型10の不変条件**: 返す辺のsource/targetは必ずexistingNodeIds∪newNodesのidに含まれる", () => {
    const rels = [rel("a", "outgoing"), rel("b", "incoming"), rel("already-there", "outgoing")];
    const existing = new Set(["center", "already-there"]);
    const plan = planExpansion("center", rels, existing);
    const known = new Set([...existing, ...plan.newNodes.map((n) => n.id)]);
    for (const e of plan.edges) {
      expect(known.has(e.source)).toBe(true);
      expect(known.has(e.target)).toBe(true);
    }
  });

  it("関係が0件なら、newNodesもedgesも空になる", () => {
    const plan = planExpansion("center", [], new Set(["center"]));
    expect(plan.newNodes).toEqual([]);
    expect(plan.edges).toEqual([]);
  });
});
