import { describe, expect, it } from "vitest";
import { DEFAULT_GRAPH_PARAMS, entityHash, exploreHash, parseGraphParams, parseHash, searchGraphHash } from "../../router";
import { buildGraphModel, rawGraphFromNeighborhood } from "./graph-model";
import { filterGraph } from "./graph-filter";
import { nbhdProject } from "./test-fixtures";

const nbhd = nbhdProject();
const model = buildGraphModel({ raw: rawGraphFromNeighborhood(nbhd), centerId: nbhd.center.id, fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes) });
describe("表示範囲とURLの復元", () => {
  it("型を絞っても起点を残し、存在しない端点へ辺を描かない", () => {
    const visible = filterGraph(model, { ...DEFAULT_GRAPH_PARAMS, types: ["Ministry"] });
    expect(visible.nodes.some((n) => n.id === model.centerId)).toBe(true);
    expect(visible.nodes.every((n) => n.id === model.centerId || n.type === "Ministry")).toBe(true);
    expect(visible.nodes.length).toBeLessThan(model.nodes.length);
    expect(visible.edges.length).toBeGreaterThan(0);
    expect(visible.edges.every((e) => visible.nodes.some((n) => n.id === e.source) && visible.nodes.some((n) => n.id === e.target))).toBe(true);
  });
  it("述語フィルタは無関係の辺と孤立点を隠し、0件でも起点を残す", () => {
    const visible = filterGraph(model, { ...DEFAULT_GRAPH_PARAMS, predicates: ["ministry"] });
    expect(visible.edges.length).toBeGreaterThan(0);
    expect(visible.edges.every((e) => e.predicate === "ministry")).toBe(true);
    expect(filterGraph(model, { ...DEFAULT_GRAPH_PARAMS, predicates: ["unknown"] }).nodes).toHaveLength(1);
  });
  it("全ルートで選択・型・関係が復元でき、探索の中心を二重デコードしない", () => {
    const center = "org/abolished/%E5%8E%9A%E7%94%9F%E7%9C%81";
    const params = { ...DEFAULT_GRAPH_PARAMS, depth: 2, types: ["Law"], predicates: ["basisLaw"], selected: center };
    for (const hash of [entityHash(center, params), searchGraphHash("年金", params), exploreHash(center, params)]) {
      expect(parseGraphParams(hash)).toEqual({ ...params, depth: hash.startsWith("#/search") ? 1 : 2 });
    }
    expect(parseHash(exploreHash(center, params))).toEqual({ name: "explore", center });
  });
});
