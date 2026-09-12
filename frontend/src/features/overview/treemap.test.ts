import { describe, expect, it } from "vitest";
import { squarifiedTreemap } from "./treemap";

// squarified treemap(Bruls et al., 1999)の最小実装。**依存を増やさない**
// (d3-hierarchy等を入れない)ため、ここで純関数として書き、性質(不変条件)で
// 検査する——特定のライブラリが出す座標そのものと1px単位で一致させることは
// 目的ではない(「面積が予算額に比例する」ことと「箱を完全に埋める」ことが
// 守るべき性質。厚労省74.6%という集中の事実を、対数ではなく面積比で見せる
// ためのタイル計算)。

describe("squarifiedTreemap", () => {
  it("空配列を渡すと空配列を返す", () => {
    expect(squarifiedTreemap([], 100, 100)).toEqual([]);
  });

  it("幅または高さが0以下なら空配列を返す(描く場所が無い)", () => {
    expect(squarifiedTreemap([{ id: "a", value: 10 }], 0, 100)).toEqual([]);
    expect(squarifiedTreemap([{ id: "a", value: 10 }], 100, 0)).toEqual([]);
  });

  it("値が0以下の項目は落とす(面積0のタイルを描かない)", () => {
    const out = squarifiedTreemap(
      [
        { id: "a", value: 10 },
        { id: "zero", value: 0 },
        { id: "negative", value: -5 },
      ],
      100,
      100,
    );
    expect(out.map((r) => r.id)).toEqual(["a"]);
  });

  it("1項目だけなら箱全体を占める", () => {
    const [rect] = squarifiedTreemap([{ id: "only", value: 42 }], 200, 80);
    expect(rect).toEqual({ id: "only", value: 42, x: 0, y: 0, width: 200, height: 80 });
  });

  it("等しい値の2項目は箱をちょうど半分ずつに分ける", () => {
    const out = squarifiedTreemap(
      [
        { id: "a", value: 50 },
        { id: "b", value: 50 },
      ],
      200,
      100,
    );
    expect(out).toHaveLength(2);
    const totalArea = out.reduce((s, r) => s + r.width * r.height, 0);
    expect(totalArea).toBeCloseTo(200 * 100, 5);
    for (const r of out) {
      expect(r.width * r.height).toBeCloseTo(10000, 5);
    }
  });

  it("すべてのタイルの面積の合計が箱の面積と一致する(隙間も重複もない)", () => {
    const items = [
      { id: "a", value: 91789031491000 },
      { id: "b", value: 6223531981000 },
      { id: "c", value: 6004038074000 },
      { id: "d", value: 3000000000000 },
      { id: "e", value: 1200000000000 },
      { id: "f", value: 500000000000 },
      { id: "g", value: 100000000000 },
    ];
    const width = 1200;
    const height = 420;
    const out = squarifiedTreemap(items, width, height);
    expect(out).toHaveLength(items.length);
    const totalArea = out.reduce((s, r) => s + r.width * r.height, 0);
    expect(totalArea).toBeCloseTo(width * height, 3);
  });

  it("各タイルの面積は入力値に線形に比例する(対数にしない——集中の事実を消さないため)", () => {
    const items = [
      { id: "big", value: 80 },
      { id: "small", value: 20 },
    ];
    const out = squarifiedTreemap(items, 100, 100);
    const big = out.find((r) => r.id === "big")!;
    const small = out.find((r) => r.id === "small")!;
    // 線形なら big の面積は small の面積のちょうど4倍(80/20)。
    // 対数だと log(80)/log(20) ≈ 1.46 倍にしかならず、この比較で見分けられる。
    expect(big.width * big.height).toBeCloseTo(4 * (small.width * small.height), 5);
  });

  it("すべてのタイルは箱の範囲内に収まり、負の寸法を持たない", () => {
    const items = [
      { id: "a", value: 30 },
      { id: "b", value: 25 },
      { id: "c", value: 20 },
      { id: "d", value: 15 },
      { id: "e", value: 10 },
    ];
    const width = 300;
    const height = 150;
    const out = squarifiedTreemap(items, width, height);
    for (const r of out) {
      expect(r.width).toBeGreaterThanOrEqual(0);
      expect(r.height).toBeGreaterThanOrEqual(0);
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.y).toBeGreaterThanOrEqual(0);
      expect(r.x + r.width).toBeLessThanOrEqual(width + 1e-6);
      expect(r.y + r.height).toBeLessThanOrEqual(height + 1e-6);
    }
  });

  it("同じ入力なら同じ出力(Math.randomを使わない。決定的)", () => {
    const items = [
      { id: "a", value: 30 },
      { id: "b", value: 25 },
      { id: "c", value: 20 },
      { id: "d", value: 15 },
      { id: "e", value: 10 },
    ];
    const out1 = squarifiedTreemap(items, 300, 150);
    const out2 = squarifiedTreemap(items, 300, 150);
    expect(out1).toEqual(out2);
  });

  it("最大の項目(厚労省相当)が全体の74.6%を占める実データに近い比率でも、面積比がその割合を保つ", () => {
    // 実データ(overview.json)の府省予算の先頭2件相当。
    const items = [
      { id: "mhlw", value: 91789031491000 },
      { id: "rest", value: 91789031491000 * (100 / 74.6 - 1) },
    ];
    const width = 1000;
    const height = 400;
    const out = squarifiedTreemap(items, width, height);
    const mhlw = out.find((r) => r.id === "mhlw")!;
    const pct = (mhlw.width * mhlw.height) / (width * height);
    expect(pct).toBeCloseTo(0.746, 2);
  });

  it("入力順(降順である必要はない)に関わらず、同じ集合なら同じ形の出力になる(値の大きい順に並べ替えて計算する)", () => {
    const asc = squarifiedTreemap(
      [
        { id: "small", value: 10 },
        { id: "big", value: 90 },
      ],
      100,
      100,
    );
    const desc = squarifiedTreemap(
      [
        { id: "big", value: 90 },
        { id: "small", value: 10 },
      ],
      100,
      100,
    );
    const sortForCompare = (rs: typeof asc) => [...rs].sort((a, b) => a.id.localeCompare(b.id));
    expect(sortForCompare(asc)).toEqual(sortForCompare(desc));
  });
});
