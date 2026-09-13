// `buildSearchGraph` のテスト(裁定B109)。
//
// **合成データを使う理由**: 「複数のヒットの近傍を合算する」という形の
// 実サンプルが `.superpowers/apisamples/` に無い(近傍のサンプルは単一中心の
// 1本だけ)。本番の応答を手で継ぎ足すと「実サンプル」でなくなるので、
// ここは**構造だけを言う最小限の合成データ**にする。値は政府データとして
// 提示しない。実データでの挙動は本番で測った表を `search-graph.ts` の
// docstringに残してある。
import { describe, expect, it } from "vitest";
import type { EntityRef, GraphEdge, NeighborhoodResponse, SearchHit } from "../../api/client";
import { buildSearchGraph } from "./search-graph";

const BASE = "https://example.jp/id";

function hit(idPath: string, type: string, label: string): SearchHit {
  return { id: `${BASE}/${idPath}`, id_path: idPath, type, label, summary: null };
}

function ref(idPath: string, type: string, label: string | null = "x"): EntityRef {
  return { id: `${BASE}/${idPath}`, id_path: idPath, type, label };
}

function edge(source: string, target: string, predicate: string): GraphEdge {
  return { source: `${BASE}/${source}`, target: `${BASE}/${target}`, predicate, graph: "g/1" };
}

function nbhd(
  center: EntityRef,
  nodes: readonly EntityRef[],
  edges: GraphEdge[],
  overrides: Partial<NeighborhoodResponse> = {},
): NeighborhoodResponse {
  return {
    center,
    depth: 1,
    nodes: [center, ...nodes],
    edges,
    graphs: {},
    node_limit: 200,
    edge_limit: 400,
    fanout_limit: 20,
    nodes_truncated: false,
    edges_truncated: false,
    fanout_truncated_nodes: [],
    ...overrides,
  };
}

describe("buildSearchGraph", () => {
  it("ヒットが0件ならnull(空のグラフを描かない)", () => {
    expect(buildSearchGraph({ hits: [], neighborhoods: [] })).toBeNull();
  });

  it("同じ府省を所管に持つ2件のヒットが、その府省を介して繋がる", () => {
    const a = hit("budget/2025/1", "BudgetProject", "事業A");
    const b = hit("budget/2025/2", "BudgetProject", "事業B");
    const ministry = ref("org/1", "Ministry", "テスト府省");
    const g = buildSearchGraph({
      hits: [a, b],
      neighborhoods: [
        nbhd(a, [ministry], [edge("budget/2025/1", "org/1", "ministry")]),
        nbhd(b, [ministry], [edge("budget/2025/2", "org/1", "ministry")]),
      ],
    })!;

    expect(g.raw.nodes.map((n) => n.id_path).sort()).toEqual([
      "budget/2025/1",
      "budget/2025/2",
      "org/1",
    ]);
    expect(g.raw.edges).toHaveLength(2);
    expect(g.connectedHitIds.size).toBe(2);
    expect(g.isolatedHitIds.size).toBe(0);
  });

  it("**1つの事業にしか属さない記録は落とし、落とした件数を返す**", () => {
    // 年度予算・支出・支出先ブロック・間接経費は2件のヒットを繋ぎえない。
    const a = hit("budget/2025/1", "BudgetProject", "事業A");
    const internals = [
      ref("budget/2025/1/annual/2024", "AnnualBudget", null),
      ref("budget/2025/1/0", "Expenditure", "支払先"),
      ref("budget/2025/1/block/A", "ExpenditureBlock", "ブロック"),
      ref("budget/2025/1/indirect/1", "IndirectCost", "間接経費"),
    ];
    const g = buildSearchGraph({
      hits: [a],
      neighborhoods: [
        nbhd(
          a,
          internals,
          internals.map((n) => edge("budget/2025/1", n.id_path, "has")),
        ),
      ],
    })!;

    expect(g.raw.nodes.map((n) => n.id_path)).toEqual(["budget/2025/1"]);
    expect(g.droppedNodeCount).toBe(4);
    // 辺も一緒に消える(端点が無い辺を残さない)。
    expect(g.raw.edges).toHaveLength(0);
  });

  it("型が繋ぎ役でなくても、2件以上のヒットに隣接するなら残す", () => {
    const a = hit("budget/2025/1", "BudgetProject", "事業A");
    const b = hit("budget/2025/2", "BudgetProject", "事業B");
    // 本来1事業にしか属さない型だが、2件のヒットに繋がっているなら
    // 俯瞰に寄与している——型の規則より実際の辺を優先する。
    const shared = ref("shared/1", "Expenditure", "共有ノード");
    const g = buildSearchGraph({
      hits: [a, b],
      neighborhoods: [
        nbhd(a, [shared], [edge("budget/2025/1", "shared/1", "has")]),
        nbhd(b, [shared], [edge("budget/2025/2", "shared/1", "has")]),
      ],
    })!;
    expect(g.raw.nodes.map((n) => n.id_path)).toContain("shared/1");
    expect(g.droppedNodeCount).toBe(0);
  });

  it("1件のヒットにしか隣接しない非繋ぎ役は落とす(閾値は2件)", () => {
    const a = hit("budget/2025/1", "BudgetProject", "事業A");
    const b = hit("budget/2025/2", "BudgetProject", "事業B");
    const onlyA = ref("x/1", "Expenditure", "Aだけに繋がる");
    const g = buildSearchGraph({
      hits: [a, b],
      neighborhoods: [
        nbhd(a, [onlyA], [edge("budget/2025/1", "x/1", "has")]),
        nbhd(b, [], []),
      ],
    })!;
    expect(g.raw.nodes.map((n) => n.id_path)).not.toContain("x/1");
    expect(g.droppedNodeCount).toBe(1);
  });

  it("辺を持たないヒットもグラフに残し、孤立として数える(結果から消さない)", () => {
    const a = hit("law/1", "Law", "法令A");
    const g = buildSearchGraph({ hits: [a], neighborhoods: [nbhd(a, [], [])] })!;
    expect(g.raw.nodes.map((n) => n.id_path)).toEqual(["law/1"]);
    expect(g.isolatedHitIds.has(a.id)).toBe(true);
    expect(g.connectedHitIds.size).toBe(0);
  });

  it("近傍が取れなかったヒットも残し、取れなかった件数を返す", () => {
    const a = hit("law/1", "Law", "法令A");
    const b = hit("law/2", "Law", "法令B");
    const g = buildSearchGraph({ hits: [a, b], neighborhoods: [nbhd(a, [], []), null] })!;
    expect(g.raw.nodes).toHaveLength(2);
    expect(g.missingNeighborhoodCount).toBe(1);
  });

  it("**打ち切りは1つでも立っていれば立てる**(黙って隠さない)", () => {
    const a = hit("budget/2025/1", "BudgetProject", "事業A");
    const b = hit("budget/2025/2", "BudgetProject", "事業B");
    const g = buildSearchGraph({
      hits: [a, b],
      neighborhoods: [
        nbhd(a, [], [], { nodes_truncated: false, edges_truncated: false }),
        nbhd(b, [], [], { nodes_truncated: true, edges_truncated: true }),
      ],
    })!;
    expect(g.nodesTruncated).toBe(true);
    expect(g.edgesTruncated).toBe(true);
  });

  it("分岐上限の印は、残したノードの分だけ返す", () => {
    const a = hit("budget/2025/1", "BudgetProject", "事業A");
    const dropped = ref("budget/2025/1/0", "Expenditure", "落とされる");
    const g = buildSearchGraph({
      hits: [a],
      neighborhoods: [
        nbhd(a, [dropped], [edge("budget/2025/1", "budget/2025/1/0", "has")], {
          fanout_truncated_nodes: [a.id, dropped.id],
        }),
      ],
    })!;
    expect([...g.fanoutTruncatedIds]).toEqual([a.id]);
  });

  it("同じノードが複数の近傍に出てきても1つにまとまる", () => {
    const a = hit("budget/2025/1", "BudgetProject", "事業A");
    const b = hit("budget/2025/2", "BudgetProject", "事業B");
    const law = ref("law/1", "Law", "根拠法令");
    const g = buildSearchGraph({
      hits: [a, b],
      neighborhoods: [
        nbhd(a, [law], [edge("budget/2025/1", "law/1", "basisLaw")]),
        nbhd(b, [law], [edge("budget/2025/2", "law/1", "basisLaw")]),
      ],
    })!;
    expect(g.raw.nodes.filter((n) => n.id_path === "law/1")).toHaveLength(1);
  });
});
