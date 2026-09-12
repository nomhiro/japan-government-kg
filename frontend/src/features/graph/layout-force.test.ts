import { describe, expect, it } from "vitest";
import { buildGraphModel, rawGraphFromNeighborhood } from "./graph-model";
import { layoutForce } from "./layout-force";
import { nbhdMinistry, nbhdProject } from "./test-fixtures";

function modelFromMinistry() {
  const nbhd = nbhdMinistry();
  const raw = rawGraphFromNeighborhood(nbhd);
  return buildGraphModel({ raw, centerId: nbhd.center.id, fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes) });
}

describe("layoutForce(力学配置)", () => {
  it("全ノードに有限の座標が付く(NaN・Infinityにならない)", () => {
    const result = layoutForce(modelFromMinistry());
    expect(result.nodes).toHaveLength(26);
    for (const n of result.nodes) {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
    }
  });

  it("レーンの列(lanes)は空——位置を決めるのに使わないモードなので", () => {
    const result = layoutForce(modelFromMinistry());
    expect(result.lanes).toEqual([]);
  });

  it("決定的: 同じモデルを2回計算すると、座標もエッジもビット単位で一致する", () => {
    const a = layoutForce(modelFromMinistry());
    const b = layoutForce(modelFromMinistry());
    expect(a).toEqual(b);
  });

  it("反復回数を変えても(1回でも)クラッシュせず、座標は有限のまま", () => {
    const result = layoutForce(modelFromMinistry(), { iterations: 1 });
    expect(result.nodes).toHaveLength(26);
    for (const n of result.nodes) {
      expect(Number.isFinite(n.x)).toBe(true);
      expect(Number.isFinite(n.y)).toBe(true);
    }
  });

  it("辺は両端が存在するものだけ(nbhd-projectの多ホップでも欠落しない)", () => {
    const nbhd = nbhdProject();
    const raw = rawGraphFromNeighborhood(nbhd);
    const model = buildGraphModel({
      raw,
      centerId: nbhd.center.id,
      fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes),
    });
    const result = layoutForce(model);
    expect(result.edges).toHaveLength(model.edges.length);
  });

  // 実ブラウザ確認で実際に踏んだ欠陥: 強い`gravity`だとノード数の少ない
  // グラフが1点に潰れ、カードがほぼ全部重なって読めなくなった。
  // 「カード同士が重なっていない」ことを直接検査する(座標が有限、という
  // だけでは重なりを検出できない)。
  it("ノードのカードは(ほとんど)重ならない——1点に潰れない", () => {
    const nbhd = nbhdProject(); // 48ノード・54辺(実サンプル、深さ2)
    const raw = rawGraphFromNeighborhood(nbhd);
    const model = buildGraphModel({
      raw,
      centerId: nbhd.center.id,
      fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes),
    });
    const result = layoutForce(model);

    function overlaps(a: (typeof result.nodes)[number], b: (typeof result.nodes)[number]): boolean {
      return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    }

    let overlapping = 0;
    let pairs = 0;
    for (let i = 0; i < result.nodes.length; i += 1) {
      for (let j = i + 1; j < result.nodes.length; j += 1) {
        pairs += 1;
        const ni = result.nodes[i];
        const nj = result.nodes[j];
        if (ni && nj && overlaps(ni, nj)) overlapping += 1;
      }
    }
    // 力学配置は密集することもあるが、全ペアの半分以上が重なるのは
    // 「1点に潰れている」と同じ意味であり、読めるグラフではない。
    expect(overlapping / pairs).toBeLessThan(0.5);
  });
});
