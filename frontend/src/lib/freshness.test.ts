import { describe, expect, it } from "vitest";
import type { ReleaseFreshness } from "../api/client";
import { foldFreshness } from "./freshness";

function row(sourceName: string, asOf: string, dateKind = "取得日"): ReleaseFreshness {
  return { source_name: sourceName, as_of: asOf, date_kind: dateKind };
}

describe("foldFreshness", () => {
  it("空なら空", () => {
    expect(foldFreshness([])).toEqual([]);
  });

  it("**同じソース・同じ日付・同じ種類の行を1つに畳み、元の件数を残す**", () => {
    // 本番で実際に起きた形(2026-09-13実測): 同じソースが同じ日付で2行。
    const folded = foldFreshness([
      row("国税庁 法人番号公表サイト 全件データ", "2026-08-23"),
      row("国税庁 法人番号公表サイト 全件データ", "2026-08-23"),
    ]);
    expect(folded).toHaveLength(1);
    expect(folded[0]!.sourceName).toBe("国税庁 法人番号公表サイト 全件データ");
    expect(folded[0]!.asOfDate).toBe("2026-08-23");
    expect(folded[0]!.graphCount).toBe(2);
  });

  it("**日付が違えば畳まない**(同じソースに2つの時点があるのは伝えるべき事実)", () => {
    const folded = foldFreshness([
      row("e-Gov法令API v2 全法令メタデータ", "2026-08-25"),
      row("e-Gov法令API v2 法令本文(law_data)", "2026-08-26"),
    ]);
    expect(folded).toHaveLength(2);
    expect(folded.map((f) => f.asOfDate)).toEqual(["2026-08-25", "2026-08-26"]);
  });

  it("日付の種類が違えば畳まない(取得日と記録日は意味が違う)", () => {
    const folded = foldFreshness([
      row("あるソース", "2026-08-23", "取得日"),
      row("あるソース", "2026-08-23", "記録日"),
    ]);
    expect(folded).toHaveLength(2);
    expect(folded.map((f) => f.dateKind)).toEqual(["取得日", "記録日"]);
  });

  it("時刻つきのISO8601でも日付部分だけを出す(タイムゾーン変換をしない)", () => {
    const folded = foldFreshness([row("あるソース", "2026-09-11T19:02:12.045010+00:00")]);
    expect(folded[0]!.asOfDate).toBe("2026-09-11");
  });

  it("入力の順序を保つ(CQ10の ORDER BY を尊重する)", () => {
    const folded = foldFreshness([row("B", "2026-01-02"), row("A", "2026-01-01")]);
    expect(folded.map((f) => f.sourceName)).toEqual(["B", "A"]);
  });
});
