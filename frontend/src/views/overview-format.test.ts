import { describe, expect, it } from "vitest";
import { computeApiUnavailableReason } from "../api/client";
import type { MinistryBudget, TypeCount } from "../api/client";
import {
  OVERVIEW_UNAVAILABLE_TEXT,
  cqNumberFromFilename,
  latestFiscalYear,
  localNameFromIri,
  ministryDisplayName,
  scaleExcludingTopNote,
  sourceCitation,
  sumMinistryBudgets,
  typeInstanceCount,
} from "./overview-format";

function ministry(overrides: Partial<MinistryBudget> = {}): MinistryBudget {
  return {
    id: "https://jgkg.norr-tech.com/id/org/1",
    id_path: "org/1",
    label: "厚生労働省",
    fiscal_year: 2025,
    total_budget: 91_789_031_491_000,
    project_count: 1176,
    ...overrides,
  };
}

// =============================================================================
// localNameFromIri: `src/jgkg/api/queries.py`の`_local_name`と同じ規則
// (#優先・無ければ/)。TypeCount.typeは完全IRIで返る(表示側で切り出す)。
// =============================================================================

describe("localNameFromIri", () => {
  it("#の後ろをローカル名として取り出す", () => {
    expect(localNameFromIri("https://jgkg.norr-tech.com/def/budget#BudgetProject")).toBe("BudgetProject");
  });

  it("#が無いときは/の後ろを取り出す", () => {
    expect(localNameFromIri("https://jgkg.norr-tech.com/id/org/6000012070001")).toBe("6000012070001");
  });

  it("区切りが無いときはそのまま返す", () => {
    expect(localNameFromIri("BudgetProject")).toBe("BudgetProject");
  });
});

// =============================================================================
// typeInstanceCount: CQ18(kg-scale)の行から件数を引く。0で静かに間違えない
// (見つからなければnull)。フォールバック名を複数渡せる。
// =============================================================================

describe("typeInstanceCount", () => {
  const ROWS: TypeCount[] = [
    { type: "https://jgkg.norr-tech.com/def/budget#BudgetProject", instance_count: 5794 },
    { type: "https://jgkg.norr-tech.com/def/law#Law", instance_count: 9550 },
    { type: "https://jgkg.norr-tech.com/def/law#LawRevision", instance_count: 9550 },
  ];

  it("一致するローカル名の件数を返す", () => {
    expect(typeInstanceCount(ROWS, "BudgetProject")).toBe(5794);
  });

  it("先に渡した名前が無ければ、次の名前で引く(フォールバック)", () => {
    expect(typeInstanceCount(ROWS, "Organization", "Law")).toBe(9550);
  });

  it("**核心**: どの名前にも一致しなければ0ではなくnull(欠損を既定値に落とさない)", () => {
    expect(typeInstanceCount(ROWS, "Organization")).toBeNull();
  });

  it("空配列でもnull", () => {
    expect(typeInstanceCount([], "BudgetProject")).toBeNull();
  });
});

// =============================================================================
// ministryDisplayName: label=nullのときはIRIの経路形(id_path)を出す
// (「(表示名なし)」のような合成文言にしない。裁定B78/B88に抵触しない)。
// =============================================================================

describe("ministryDisplayName", () => {
  it("labelがあればそれを返す", () => {
    expect(ministryDisplayName(ministry({ label: "厚生労働省" }))).toBe("厚生労働省");
  });

  it("**核心**: labelがnullのときはid_pathを返す(表示名を合成しない)", () => {
    expect(ministryDisplayName(ministry({ label: null, id_path: "org/9999999999999" }))).toBe(
      "org/9999999999999",
    );
  });
});

// =============================================================================
// sumMinistryBudgets / latestFiscalYear: CQ15の行から導出する測定値
// (対応表を手で書かない。controller補足3: 測定値は導出する)。
// =============================================================================

describe("sumMinistryBudgets", () => {
  it("全府省の予算額を合計する(合計してよいのは予算額だけ。裁定B96)", () => {
    const rows = [ministry({ total_budget: 91_789_031_491_000 }), ministry({ total_budget: 6_223_531_981_000 })];
    expect(sumMinistryBudgets(rows)).toBe(98_012_563_472_000);
  });

  it("空配列なら0", () => {
    expect(sumMinistryBudgets([])).toBe(0);
  });
});

describe("latestFiscalYear", () => {
  it("行から年度を読む(書き込まない)", () => {
    expect(latestFiscalYear([ministry({ fiscal_year: 2025 })])).toBe(2025);
  });

  it("複数の年度が混在するときは最大(最新)を返す", () => {
    expect(latestFiscalYear([ministry({ fiscal_year: 2024 }), ministry({ fiscal_year: 2025 })])).toBe(2025);
  });

  it("1行も無ければnull", () => {
    expect(latestFiscalYear([])).toBeNull();
  });
});

// =============================================================================
// cqNumberFromFilename / sourceCitation: sourcesからCQ番号を導出する。
// 対応表を手で書かない(controller補足1: 再発欠陥1と同型)。
// =============================================================================

describe("cqNumberFromFilename", () => {
  it("cq15-... からCQ15を導出する", () => {
    expect(cqNumberFromFilename("cq15-ministry-budget-ranking.rq")).toBe("CQ15");
  });

  it("cq番号の形式でなければファイル名をそのまま返す(手書きの対応表で補わない)", () => {
    expect(cqNumberFromFilename("legacy-cq06-optional-inference.rq")).toBe("legacy-cq06-optional-inference.rq");
  });
});

describe("sourceCitation", () => {
  const SOURCES: Record<string, string> = {
    ministries: "cq15-ministry-budget-ranking.rq",
    budget_and_execution: "cq14-budget-and-execution-by-year.rq",
    type_counts: "cq18-kg-scale.rq",
    government_paid: "cq12-government-paid-total.rq",
  };

  it("1項目なら「出所: CQnn」", () => {
    expect(sourceCitation(SOURCES, "ministries")).toBe("出所: CQ15");
  });

  it("複数項目のときは渡した順に・で連結する", () => {
    expect(sourceCitation(SOURCES, "government_paid", "ministries", "type_counts")).toBe(
      "出所: CQ12・CQ15・CQ18",
    );
  });

  it("sourcesに無いキーは黙って落とす(無いキーを渡すのは呼び出し側の誤りだが、ここではクラッシュしない)", () => {
    expect(sourceCitation(SOURCES, "no_such_key")).toBe("出所: ");
  });
});

// =============================================================================
// scaleExcludingTopNote: 「厚労省を除いて見る」の注記文
// (モックの文言をそのまま使う。対数目盛りにしない判断ごと持ってくる)。
// =============================================================================

describe("scaleExcludingTopNote", () => {
  it("除いた府省の名前・金額・割合と、除いた後の最大府省名を文中に含む", () => {
    const text = scaleExcludingTopNote({
      excludedName: "厚生労働省",
      excludedBudget: 91_789_031_491_000,
      totalBudget: 123_080_937_002_000,
      newMaxName: "こども家庭庁",
      restCount: 22,
      totalCount: 23,
    });
    expect(text).toContain("厚生労働省");
    expect(text).toContain("91.8兆円");
    expect(text).toContain("74.6%");
    expect(text).toContain("22府省のうち最大（こども家庭庁）");
    expect(text).toContain("全23府省");
  });

  it("**核心**: 対数目盛りという語を含まない(このプロジェクトは対数を採らない判断そのものを持ってきている)", () => {
    const text = scaleExcludingTopNote({
      excludedName: "厚生労働省",
      excludedBudget: 91_789_031_491_000,
      totalBudget: 123_080_937_002_000,
      newMaxName: "こども家庭庁",
      restCount: 22,
      totalCount: 23,
    });
    expect(text).not.toContain("対数");
  });
});

// =============================================================================
// 裁定B84の教訓: 503(集約失敗)の文言は、APIそのものが未配備の文言と
// 同じであってはならない(対処が違う2つの原因を区別できないゲートの欠陥)。
// =============================================================================

describe("OVERVIEW_UNAVAILABLE_TEXT", () => {
  it("apiUnavailableReason()の文言とは異なる(2つの経路を区別できる)", () => {
    const apiUnavailable = computeApiUnavailableReason("http://localhost:8000", "jgkg.norr-tech.com");
    expect(apiUnavailable).not.toBeNull();
    expect(OVERVIEW_UNAVAILABLE_TEXT).not.toBe(apiUnavailable);
  });

  it("利用者に内部事情(503・起動時の集約)を説明しない(「503」「起動」等を含まない)", () => {
    expect(OVERVIEW_UNAVAILABLE_TEXT).not.toMatch(/503|起動|集約/);
  });
});
