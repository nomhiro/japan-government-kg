import { describe, expect, it, vi } from "vitest";
import type {
  AttributeValue,
  ChatResponse,
  ChatSource,
  EntityDetailResponse,
  EntityRef,
  PathResponse,
  Provenance,
} from "./api/client";

// labels.test.tsと同じ理由(このファイルの先頭コメント参照): 表示名がある/
// 無いときの`attributeValueHtml`の振る舞いを検査したいのであって、いま
// 実際に何が翻訳済みかを検査したいわけではない。
vi.mock("./generated/labels.json", () => ({
  default: {
    types: {},
    predicates: {},
    enumValues: { recipientMatchCategory: { resolved: "法人番号で特定できた" } },
    typeAxes: {},
  },
}));

import {
  attributeValueHtml,
  chatSourceHtml,
  describePathResult,
  formatAmountFull,
  formatAmountRounded,
  neighborhoodStatusText,
  provenanceHtml,
  toolCallLogEntryHtml,
  truncationNotice,
} from "./format";

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

// =============================================================================
// neighborhoodStatusText: 近傍グラフのステータス行(裁定B92のE-1)。
// 打ち切りのフラグが立っているのに文言が出ない状態を作ると落ちるように、
// フラグの組み合わせごとに厳密な文字列一致で検査する(「1件以上」にしない)。
// =============================================================================

describe("neighborhoodStatusText", () => {
  const BASE = { nodeCount: 5, edgeCount: 4, nodesTruncated: false, edgesTruncated: false, fanoutTruncatedCount: 0 };

  it("打ち切りが無いとき、件数だけを出し、通知文は一切出ない", () => {
    expect(neighborhoodStatusText(BASE)).toBe("ノード5件・辺4件");
  });

  it("**核心**: nodes_truncatedが真なら、通知文を含めなければならない", () => {
    const text = neighborhoodStatusText({ ...BASE, nodesTruncated: true });
    expect(text).toContain("ノード数の上限で一部を省略");
  });

  it("edges_truncatedが真なら、通知文を含めなければならない", () => {
    const text = neighborhoodStatusText({ ...BASE, edgesTruncated: true });
    expect(text).toContain("エッジ数の上限で一部を省略");
  });

  it("fanoutTruncatedCountが1件以上なら、件数入りの通知文を含めなければならない(件数を厳密に見る)", () => {
    const text = neighborhoodStatusText({ ...BASE, fanoutTruncatedCount: 3 });
    expect(text).toContain("3件のノードで分岐数の上限に達しています");
  });

  it("3種類の打ち切りが同時に真でも、3つの通知文がすべて含まれる(1つに退化しない)", () => {
    const text = neighborhoodStatusText({
      nodeCount: 100,
      edgeCount: 200,
      nodesTruncated: true,
      edgesTruncated: true,
      fanoutTruncatedCount: 7,
    });
    expect(text).toBe(
      "ノード100件・辺200件(ノード数の上限で一部を省略)(エッジ数の上限で一部を省略)" +
        "。7件のノードで分岐数の上限に達しています(⋯マーク。クリックで続きを見られます)",
    );
  });
});

// =============================================================================
// attributeValueHtml: 属性値+出典リンク(裁定B82(4a)。グラフのノード詳細
// パネルと`entity.ts`の両方から使う共通関数になった。裁定B92のE-1)
// =============================================================================

describe("attributeValueHtml", () => {
  const GRAPHS: EntityDetailResponse["graphs"] = {
    g1: { graph: "g1", source: "https://example.test/a", fetched_on: "2026-08-01", license: "PDL1.0", available: true },
    g2: { graph: "g2", source: "https://example.test/b", fetched_on: "2026-08-02", license: "PDL1.0", available: true },
  };

  it("値と出典リンクを描く", () => {
    const av: AttributeValue = { value: "厚生労働省", graphs: ["g1"] };
    const html = attributeValueHtml("ministry", av, GRAPHS);
    expect(html).toContain("厚生労働省");
    expect(html).toContain("https://example.test/a");
  });

  it("複数のグラフが同じ値を主張するとき、出典リンクを複数並べる", () => {
    const av: AttributeValue = { value: "厚生労働省", graphs: ["g1", "g2"] };
    const html = attributeValueHtml("ministry", av, GRAPHS);
    expect(html).toContain("https://example.test/a");
    expect(html).toContain("https://example.test/b");
  });

  it("列挙型の許容値は表示名に置き換える(裁定B82(4b))", () => {
    const av: AttributeValue = { value: "resolved", graphs: ["g1"] };
    const html = attributeValueHtml("recipientMatchCategory", av, GRAPHS);
    expect(html).toContain("法人番号で特定できた");
    expect(html).not.toContain(">resolved<");
  });

  it("出典が取れていない(available=false)値は、空リンクを描かない", () => {
    const graphs: EntityDetailResponse["graphs"] = {
      g1: { graph: "g1", source: "", fetched_on: "", license: "", available: false },
    };
    const av: AttributeValue = { value: "厚生労働省", graphs: ["g1"] };
    const html = attributeValueHtml("ministry", av, graphs);
    expect(html).not.toContain("<a ");
    expect(html).toContain("出典が取れていない");
  });
});

// =============================================================================
// chatSourceHtml / toolCallLogEntryHtml: チャット(E-2。裁定B92)の出典と
// 道具呼び出し履歴の描画。捏造しない(裁定2)ことをここでも直接検査する。
// =============================================================================

describe("chatSourceHtml", () => {
  const GRAPHS: ChatResponse["graphs"] = {
    g1: { graph: "g1", source: "https://example.test/a", fetched_on: "2026-08-01", license: "PDL1.0", available: true },
  };

  it("graphsが空(searchだけを使った参照)のとき、空リンクを描かず出典なしと明示する", () => {
    const source: ChatSource = { id: "x", id_path: "x", type: "Ministry", label: "厚生労働省", graphs: [] };
    const html = chatSourceHtml(source, {});
    expect(html).not.toContain("<a ");
    expect(html).toContain("出典が取れていない");
    expect(html).toContain("厚生労働省");
  });

  it("graphsが1件以上あるとき、一次資料へのリンクを描く", () => {
    const source: ChatSource = { id: "x", id_path: "x", type: "Ministry", label: "厚生労働省", graphs: ["g1"] };
    const html = chatSourceHtml(source, GRAPHS);
    expect(html).toContain('<a href="https://example.test/a"');
  });

  it("labelが無いとき「(表示名なし)」と表示する(空文字を描かない)", () => {
    const source: ChatSource = { id: "x", id_path: "x", type: "Law", label: null, graphs: [] };
    expect(chatSourceHtml(source, {})).toContain("(表示名なし)");
  });
});

// =============================================================================
// formatAmountRounded / formatAmountFull: 第1層(裁定B103)の金額整形。
// `docs/mockups/top-page.html`の`jpShort`/`jpFull`(レビュー済み)と同じ
// 境界・同じ丸め方であることをここで固定する——作り直したら壊れる。
// =============================================================================

describe("formatAmountRounded", () => {
  it("1兆円以上は兆円単位・小数1桁", () => {
    expect(formatAmountRounded(91_789_031_491_000)).toBe("91.8兆円");
    expect(formatAmountRounded(1e12)).toBe("1.0兆円");
  });

  it("1000億円以上1兆円未満は億円単位・整数(桁区切り)", () => {
    expect(formatAmountRounded(135_589_321_000)).toBe("1,356億円");
    expect(formatAmountRounded(1e11)).toBe("1,000億円");
  });

  it("1億円以上1000億円未満は億円単位・小数1桁", () => {
    expect(formatAmountRounded(30_432_969_000)).toBe("304.3億円");
    expect(formatAmountRounded(1e8)).toBe("1.0億円");
  });

  it("1万円以上1億円未満は万円単位・整数", () => {
    expect(formatAmountRounded(45_013_000)).toBe("4501万円");
    // **境界は`jpShort`と同じく1億円未満なら万円のまま**(1億円ちょうど手前で
    // 億円に切り替わらない。モックと同じ丸め方をそのまま持ってきているため)。
    expect(formatAmountRounded(99_999_999)).toBe("10000万円");
  });

  it("1万円未満は円のまま(桁区切り)", () => {
    expect(formatAmountRounded(9999)).toBe("9,999円");
    expect(formatAmountRounded(0)).toBe("0円");
  });

  // 修正ラウンド1・レビューQ6: 負値は絶対値で桁を判定し符号を戻す
  // (`>=`だけの分岐だと負値がすべて最後の分岐に落ち、未丸めの生の桁になる)。
  it("**核心**: 負値も絶対値で丸めてから符号を戻す(事業ごとの補正額は実在する負値)", () => {
    expect(formatAmountRounded(-518_000_000_000)).toBe("-5,180億円");
    expect(formatAmountRounded(-91_789_031_491_000)).toBe("-91.8兆円");
    expect(formatAmountRounded(-9999)).toBe("-9,999円");
  });

  it("非有限値(NaN/Infinity)はクラッシュせず文字列化する", () => {
    expect(formatAmountRounded(NaN)).toBe("NaN");
    expect(formatAmountRounded(Infinity)).toBe("Infinity");
    expect(formatAmountRounded(-Infinity)).toBe("-Infinity");
  });
});

describe("formatAmountFull", () => {
  it("桁区切り+「円」を付けた正確な値を返す(丸めた値と併記するための表示)", () => {
    expect(formatAmountFull(91_789_031_491_000)).toBe("91,789,031,491,000円");
    expect(formatAmountFull(0)).toBe("0円");
  });

  it("負値も桁区切りの符号付きで返す(修正ラウンド1・レビューQ6)", () => {
    expect(formatAmountFull(-518_000_000_000)).toBe("-518,000,000,000円");
  });

  it("非有限値(NaN/Infinity)はクラッシュせず文字列化する", () => {
    expect(formatAmountFull(NaN)).toBe("NaN");
    expect(formatAmountFull(Infinity)).toBe("Infinity");
  });
});

describe("toolCallLogEntryHtml", () => {
  it("道具名・引数・件数を含む", () => {
    const html = toolCallLogEntryHtml({ tool: "search_entities", arguments: { q: "厚生労働省", limit: 20 }, result_count: 2 });
    expect(html).toContain("search_entities");
    expect(html).toContain("厚生労働省");
    expect(html).toContain("2件");
  });

  it("**核心**: 件数0のときも0件と正確に表示する(1件以上に丸めない)", () => {
    const html = toolCallLogEntryHtml({ tool: "get_entity", arguments: { id_path: "x" }, result_count: 0 });
    expect(html).toContain("0件");
  });
});
