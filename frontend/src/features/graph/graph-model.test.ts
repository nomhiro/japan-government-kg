import { describe, expect, it } from "vitest";
import {
  assignLanes,
  buildGraphModel,
  displayLabel,
  mergeRawGraphs,
  rawGraphFromNeighborhood,
  relationshipGroupToRawGraph,
  relationshipToEdge,
  truncateForWidth,
} from "./graph-model";
import { entityMinistry, entityProject, nbhdMinistry, nbhdProject } from "./test-fixtures";

describe("rawGraphFromNeighborhood + buildGraphModel(厚労省の実サンプル: 26ノード・25辺)", () => {
  const nbhd = nbhdMinistry();
  const raw = rawGraphFromNeighborhood(nbhd);
  const model = buildGraphModel({
    raw,
    centerId: nbhd.center.id,
    fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes),
  });

  it("ノード26件・辺25件をそのまま運ぶ(数を数え直さない)", () => {
    expect(model.nodes).toHaveLength(26);
    expect(model.edges).toHaveLength(25);
  });

  it("中心のホップは0、直結する事業はすべてホップ1", () => {
    const center = model.nodes.find((n) => n.id === nbhd.center.id);
    expect(center?.hop).toBe(0);
    const projects = model.nodes.filter((n) => n.type === "BudgetProject");
    expect(projects).toHaveLength(25);
    expect(projects.every((n) => n.hop === 1)).toBe(true);
  });

  it("中心の次数は25(すべての辺が刺さる)、事業の次数は1", () => {
    const center = model.nodes.find((n) => n.id === nbhd.center.id);
    expect(center?.degree).toBe(25);
    const oneProject = model.nodes.find((n) => n.type === "BudgetProject");
    expect(oneProject?.degree).toBe(1);
  });

  it("Ministryは「所管」レーン、BudgetProjectは「事業」レーンに型だけで決まる", () => {
    const center = model.nodes.find((n) => n.id === nbhd.center.id);
    expect(center?.laneKey).toBe("who");
    const project = model.nodes.find((n) => n.type === "BudgetProject");
    expect(project?.laneKey).toBe("what");
  });

  it("fanout_truncated_nodesに載っている中心だけhasMoreがtrue", () => {
    const center = model.nodes.find((n) => n.id === nbhd.center.id);
    const project = model.nodes.find((n) => n.type === "BudgetProject");
    expect(center?.hasMore).toBe(true);
    expect(project?.hasMore).toBe(false);
  });

  it("hasMoreOverridesが渡されればfanout_truncated_nodesより優先される(展開後に閉じる)", () => {
    const closed = buildGraphModel({
      raw,
      centerId: nbhd.center.id,
      fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes),
      hasMoreOverrides: new Map([[nbhd.center.id, false]]),
    });
    expect(closed.nodes.find((n) => n.id === nbhd.center.id)?.hasMore).toBe(false);
  });

  it("軸はlabels.jsonのtypeAxes経由で引ける(Ministry→Agent, BudgetProject→Work)", () => {
    const center = model.nodes.find((n) => n.id === nbhd.center.id);
    const project = model.nodes.find((n) => n.type === "BudgetProject");
    expect(center?.axis).toBe("Agent");
    expect(project?.axis).toBe("Work");
  });
});

describe("assignLanes(Organizationは型で決まらず、recipient辺の的側だけ「支払先」)", () => {
  const nbhd = nbhdProject();
  const lanes = assignLanes(nbhd.nodes, nbhd.edges);

  it("recipient辺の目的語のOrganizationは「支払先」レーン", () => {
    const org = nbhd.nodes.find((n) => n.id === "https://jgkg.norr-tech.com/id/org/8700150009143");
    expect(org?.type).toBe("Organization");
    expect(lanes.get(org?.id ?? "")).toBe("recipient");
  });

  it("Ministryはrecipientの的でなくても型だけで「所管」レーン", () => {
    const ministry = nbhd.nodes.find((n) => n.type === "Ministry");
    expect(lanes.get(ministry?.id ?? "")).toBe("who");
  });

  it("UnresolvedReferenceは脇のストリップ(aside)", () => {
    const unresolved = nbhd.nodes.find((n) => n.type === "UnresolvedReference");
    expect(lanes.get(unresolved?.id ?? "")).toBe("aside");
  });

  it("ExpenditureBlockは「段・年度」レーン、Expenditureは「支出」レーン", () => {
    const block = nbhd.nodes.find((n) => n.type === "ExpenditureBlock");
    const expenditure = nbhd.nodes.find((n) => n.type === "Expenditure");
    expect(lanes.get(block?.id ?? "")).toBe("stage");
    expect(lanes.get(expenditure?.id ?? "")).toBe("payment");
  });
});

describe("relationshipToEdge / relationshipGroupToRawGraph(エンティティ詳細の展開)", () => {
  it("direction=incomingは related→subject の辺になる(厚労省サンプル)", () => {
    const detail = entityMinistry();
    const group = detail.relationships["BudgetProject"] ?? [];
    expect(group.length).toBeGreaterThan(0);
    const first = group[0];
    if (!first) throw new Error("fixture不備");
    const edge = relationshipToEdge(detail.id, first);
    expect(edge.source).toBe(first.related.id);
    expect(edge.target).toBe(detail.id);
    expect(edge.predicate).toBe("ministry");
  });

  it("direction=outgoingは subject→related の辺になる(事業サンプル)", () => {
    const detail = entityProject();
    const group = detail.relationships["Ministry"] ?? [];
    const first = group[0];
    if (!first) throw new Error("fixture不備");
    const edge = relationshipToEdge(detail.id, first);
    expect(edge.source).toBe(detail.id);
    expect(edge.target).toBe(first.related.id);
  });

  it("型グループ1件分をRawGraphにすると、辺の数とノードの数が関係の数に一致する", () => {
    const detail = entityMinistry();
    const group = detail.relationships["BudgetProject"] ?? [];
    const raw = relationshipGroupToRawGraph(detail.id, group);
    expect(raw.nodes).toHaveLength(group.length);
    expect(raw.edges).toHaveLength(group.length);
  });
});

describe("mergeRawGraphs(重複排除)", () => {
  it("同じノードid・同じ辺キーは1つにまとまる", () => {
    const nbhd = nbhdMinistry();
    const raw = rawGraphFromNeighborhood(nbhd);
    const detail = entityMinistry();
    const group = detail.relationships["BudgetProject"] ?? [];
    const addition = relationshipGroupToRawGraph(detail.id, group);

    const merged = mergeRawGraphs([raw, addition]);
    // 展開分(50件)はベースの近傍(25件のBudgetProject)と大きく重なるので、
    // 合算より少ないノード数になる(重複が消えている)ことを確かめる。
    expect(merged.nodes.length).toBeLessThan(raw.nodes.length + addition.nodes.length);
    expect(merged.nodes.length).toBeGreaterThanOrEqual(raw.nodes.length);

    const ids = merged.nodes.map((n) => n.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("displayLabel / truncateForWidth", () => {
  it("labelがnullなら「(表示名なし)」を返す(名前を合成しない)", () => {
    expect(displayLabel(null)).toBe("(表示名なし)");
    expect(displayLabel("厚生労働省")).toBe("厚生労働省");
  });

  it("maxCharsを超えるときだけ末尾を…に置き換える", () => {
    const short = truncateForWidth("厚生労働省", 10);
    expect(short).toEqual({ text: "厚生労働省", truncated: false, full: "厚生労働省" });

    const long = truncateForWidth("後期高齢者医療制度事業費補助金(健康診査事業)", 8);
    expect(long.truncated).toBe(true);
    expect(long.text).toBe("後期高齢者医療…");
    expect(long.full).toBe("後期高齢者医療制度事業費補助金(健康診査事業)");
  });
});
