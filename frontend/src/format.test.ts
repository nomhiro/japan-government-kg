import { describe, expect, it } from "vitest";
import type { EntityRef, PathResponse, Provenance } from "./api/client";
import { describePathResult, provenanceHtml, truncationNotice } from "./format";

const REF: EntityRef = { id: "https://jgkg.norr-tech.com/id/x", id_path: "x", type: "Law", label: "テスト法令" };

function basePath(overrides: Partial<PathResponse> = {}): PathResponse {
  return {
    start: REF,
    goal: REF,
    nodes: [],
    edges: [],
    graphs: {},
    found: false,
    max_depth: 4,
    visit_budget: 400,
    visited: 10,
    searched_depth: 2,
    budget_exhausted: false,
    depth_limited: false,
    fanout_limit: 50,
    fanout_truncated: false,
    exhaustive: false,
    undirected: true,
    ...overrides,
  };
}

// =============================================================================
// 裁定B82(3): found=falseの読み方(裁定B77の族)を自動テストで縛る
// =============================================================================

describe("describePathResult", () => {
  it("kind=found のとき、他のフラグが何であってもfoundを返す", () => {
    expect(describePathResult(basePath({ found: true, exhaustive: false }))).toEqual({ kind: "found" });
  });

  it("found=false かつ exhaustive=true のときだけ「経路は存在しない」(not-found-exhaustive)", () => {
    const result = describePathResult(
      basePath({ found: false, exhaustive: true, budget_exhausted: false, depth_limited: false, fanout_truncated: false }),
    );
    expect(result).toEqual({ kind: "not-found-exhaustive" });
  });

  it("**核心**: budget_exhausted=trueならexhaustiveは真になれない。真になっていたら『無い』という嘘を報告する", () => {
    // このテストの主張は「exhaustive=trueかつbudget_exhausted=trueという入力は
    // 意味的に矛盾する(API側の裁定B77が保証するはず)」ではなく、
    // 「describePathResultはexhaustiveフラグそのものを見て判定する」こと——
    // 呼び出し側(path.ts)がexhaustiveを無視して他のフラグだけで
    // 「見つからなかった」/「存在しない」を決めるような実装に戻ったら、
    // このテストは落ちなければならない。
    const result = describePathResult(
      basePath({ found: false, exhaustive: false, budget_exhausted: true }),
    );
    expect(result.kind).toBe("not-found-inconclusive");
    if (result.kind === "not-found-inconclusive") {
      expect(result.reasons.join("・")).toContain("訪問予算");
    }
  });

  it("found=false かつ exhaustive=false のとき、reasonsに理由を全部含める(budget/depth/fanoutの3つ)", () => {
    const result = describePathResult(
      basePath({
        found: false,
        exhaustive: false,
        budget_exhausted: true,
        depth_limited: true,
        fanout_truncated: true,
        max_depth: 4,
        visit_budget: 400,
      }),
    );
    expect(result.kind).toBe("not-found-inconclusive");
    if (result.kind === "not-found-inconclusive") {
      expect(result.reasons).toHaveLength(3);
      expect(result.reasons.some((r) => r.includes("訪問予算(400件)"))).toBe(true);
      expect(result.reasons.some((r) => r.includes("深さ上限(4)"))).toBe(true);
      expect(result.reasons.some((r) => r.includes("分岐数の上限"))).toBe(true);
    }
  });

  it("found=false かつ exhaustive=false かつ他の打ち切りフラグも無いとき、reasonsは空配列(理由不明のまま『存在しない』と言わない)", () => {
    const result = describePathResult(basePath({ found: false, exhaustive: false }));
    expect(result).toEqual({ kind: "not-found-inconclusive", reasons: [] });
  });
});

// =============================================================================
// truncationNotice: truncatedが真のときだけ出す(仕様§9.2「黙って切らない」)
// =============================================================================

describe("truncationNotice", () => {
  it("truncated=false のときは何も表示しない(空文字列)", () => {
    expect(truncationNotice(false, 50, "関係")).toBe("");
  });

  it("truncated=true のとき、上限件数と対象名を含む注記を出す", () => {
    const html = truncationNotice(true, 50, "関係");
    expect(html).toContain("50");
    expect(html).toContain("関係");
  });
});

// =============================================================================
// provenanceHtml: available=falseのとき空リンクを描かない(D-5ブリーフ拘束条件(d))
// =============================================================================

describe("provenanceHtml", () => {
  const AVAILABLE: Provenance = {
    graph: "g1",
    source: "https://laws.e-gov.go.jp/api/2/laws",
    fetched_on: "2026-08-25",
    license: "PDL1.0",
    available: true,
  };

  it("available=false のとき、リンクを描かず「出典が取れていない」と明示する", () => {
    const html = provenanceHtml({ ...AVAILABLE, available: false, source: "" });
    expect(html).not.toContain("<a ");
    expect(html).toContain("出典が取れていない");
  });

  it("provenanceが無い(undefined)ときも同じく空リンクを描かない", () => {
    const html = provenanceHtml(undefined);
    expect(html).not.toContain("<a ");
    expect(html).toContain("出典が取れていない");
  });

  it("available=true のとき、一次資料へのリンクと取得日時を出す", () => {
    const html = provenanceHtml(AVAILABLE);
    expect(html).toContain(`<a href="${AVAILABLE.source}"`);
    expect(html).toContain(AVAILABLE.fetched_on);
  });
});
