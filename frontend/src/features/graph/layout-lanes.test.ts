import { describe, expect, it } from "vitest";
import { buildGraphModel, rawGraphFromNeighborhood } from "./graph-model";
import { CARD_H, CARD_W, DEFAULT_MAX_PER_LANE, layoutLanes } from "./layout-lanes";
import { nbhdMinistry, nbhdProject } from "./test-fixtures";

function modelFromMinistry() {
  const nbhd = nbhdMinistry();
  const raw = rawGraphFromNeighborhood(nbhd);
  return buildGraphModel({ raw, centerId: nbhd.center.id, fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes) });
}

describe("layoutLanes(厚労省の実サンプル: 中心1件+事業25件、レーンは「所管」と「事業」の2列だけ)", () => {
  const model = modelFromMinistry();
  // 「事業」レーンは25件で既定の折り畳み上限(18件)を超えるので、
  // 全件を対象にした検査は明示的に展開した結果を使う。
  const result = layoutLanes(model, { expandedLanes: new Set(["what"]) });

  it("すべてのノードに位置が付く(26件)", () => {
    expect(result.nodes).toHaveLength(26);
  });

  it("占有されている2レーン(所管・事業)だけが列になる。根拠・段・年度・支出・支払先の列は無い", () => {
    expect(result.lanes.map((l) => l.key)).toEqual(["who", "what"]);
  });

  it("「所管」レーンが「事業」レーンより左(x が小さい)にある(流れの順序)", () => {
    const who = result.lanes.find((l) => l.key === "who");
    const what = result.lanes.find((l) => l.key === "what");
    expect(who!.x).toBeLessThan(what!.x);
  });

  it("同じレーン内のカードは重ならない(y が全部違う)", () => {
    const whatNodes = result.nodes.filter((n) => n.laneKey === "what");
    const ys = whatNodes.map((n) => n.y);
    expect(new Set(ys).size).toBe(ys.length);
  });

  it("カードの寸法はCARD_W×CARD_Hで統一されている", () => {
    for (const n of result.nodes) {
      expect(n.w).toBe(CARD_W);
      expect(n.h).toBe(CARD_H);
    }
  });

  it("辺はすべて配置済み(両端が可視ノードなので25本すべて描ける)", () => {
    expect(result.edges).toHaveLength(25);
  });

  it("事業→所管の辺はレーンの並びと逆(事業が右・所管が左)なのでflip=trueになる", () => {
    // 実データ: source=BudgetProject(事業/右), target=Ministry(所管/左)。
    // 視覚上は左(所管)→右(事業)に流したいので、描画時に反転が必要。
    expect(result.edges.every((e) => e.flip)).toBe(true);
  });

  it("width/heightは正の値で、全ノードがその範囲に収まる", () => {
    expect(result.width).toBeGreaterThan(0);
    expect(result.height).toBeGreaterThan(0);
    for (const n of result.nodes) {
      expect(n.x + n.w).toBeLessThanOrEqual(result.width);
      expect(n.y + n.h).toBeLessThanOrEqual(result.height);
    }
  });

  it("決定的: 同じモデル・同じオプションを2回レイアウトすると同じ座標になる", () => {
    const again = layoutLanes(modelFromMinistry(), { expandedLanes: new Set(["what"]) });
    expect(again).toEqual(result);
  });
});

describe("layoutLanes: レーンの折り畳み(maxPerLane超え)", () => {
  const model = modelFromMinistry(); // 「事業」レーンは25件 > 既定18件
  const result = layoutLanes(model);
  const expanded = layoutLanes(model, { expandedLanes: new Set(["what"]) });

  it("既定では「事業」レーンの表示は上限(18件)までに切り詰められる", () => {
    const shown = result.nodes.filter((n) => n.laneKey === "what");
    expect(shown).toHaveLength(DEFAULT_MAX_PER_LANE);
  });

  it("LaneBand.countは切り詰め前の全件数(25件)を報告する(偽の件数を出さない)", () => {
    const band = result.lanes.find((l) => l.key === "what");
    expect(band?.count).toBe(25);
  });

  it("expandedLanesに指定すると全件(25件)表示される", () => {
    const shown = expanded.nodes.filter((n) => n.laneKey === "what");
    expect(shown).toHaveLength(25);
  });

  it("切り詰められて非表示のノードへの辺は描かれない(存在しない位置に描かない)", () => {
    expect(result.edges.length).toBeLessThan(25);
    expect(expanded.edges).toHaveLength(25);
  });
});

describe("layoutLanes: 脇のストリップ(aside)", () => {
  it("UnresolvedReferenceはどのレーン列にも属さず、asideとして別に配置される", () => {
    const nbhd = nbhdProject();
    const raw = rawGraphFromNeighborhood(nbhd);
    const model = buildGraphModel({
      raw,
      centerId: nbhd.center.id,
      fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes),
    });
    const result = layoutLanes(model);

    expect(result.lanes.some((l) => l.key === "aside")).toBe(false);
    const asideNodes = result.nodes.filter((n) => n.laneKey === "aside");
    expect(asideNodes.length).toBeGreaterThan(0);
    // asideは本流レーンより下に置かれる。
    const mainMaxY = Math.max(
      ...result.nodes.filter((n) => n.laneKey !== "aside").map((n) => n.y + n.h),
    );
    for (const n of asideNodes) {
      expect(n.y).toBeGreaterThanOrEqual(mainMaxY);
    }
  });
});
