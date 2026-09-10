import { describe, expect, it } from "vitest";
import type { EntityRef, Relationship } from "../api/client";
import { liveGraphCounts, planExpansion } from "./graph-merge";

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

// =============================================================================
// liveGraphCounts: 状態行の件数を「いまのグラフ」から数える(裁定B93)。
//
// **controllerが実ブラウザで踏んだ欠陥の再発防止**: 厚生労働省の予算事業
// 50件を展開した後も、状態行が「ノード27件・辺25件。1件のノードで分岐数の
// 上限に達しています」のまま残った。グラフは実際には77件になり、その分岐上限も
// もう当てはまらない——**表示が現在のグラフについて偽を主張していた**
// (再発欠陥6)。
// =============================================================================

describe("liveGraphCounts", () => {
  it("ノード数はフラグ配列の長さ、辺数は渡した値をそのまま返す", () => {
    expect(liveGraphCounts([false, false, false], 2)).toEqual({
      nodeCount: 3,
      edgeCount: 2,
      fanoutTruncatedCount: 0,
    });
  });

  it("分岐上限に達しているノードの件数を数える", () => {
    expect(liveGraphCounts([true, false, true, false, false], 4).fanoutTruncatedCount).toBe(2);
  });

  it("**展開でノードが増え、分岐上限が解消したことが件数に反映される**", () => {
    // 展開前: 27ノード・25辺・中心1件が分岐上限
    const before = liveGraphCounts([true, ...Array(26).fill(false)], 25);
    expect(before).toEqual({ nodeCount: 27, edgeCount: 25, fanoutTruncatedCount: 1 });

    // 展開後: 中心のフラグが解消し、50ノード・50辺が増える
    const after = liveGraphCounts([false, ...Array(76).fill(false)], 75);
    expect(after).toEqual({ nodeCount: 77, edgeCount: 75, fanoutTruncatedCount: 0 });

    // **件数と分岐上限の両方が変わることを縛る**(片方だけ更新しても通らない)
    expect(after.nodeCount).not.toBe(before.nodeCount);
    expect(after.fanoutTruncatedCount).not.toBe(before.fanoutTruncatedCount);
  });

  it("空のグラフでも0件を返す(空虚化防止のため明示的に確認する)", () => {
    expect(liveGraphCounts([], 0)).toEqual({
      nodeCount: 0,
      edgeCount: 0,
      fanoutTruncatedCount: 0,
    });
  });
});
