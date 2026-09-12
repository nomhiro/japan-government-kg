import { afterEach, describe, expect, it, vi } from "vitest";
import { computeApiUnavailableReason } from "../api/client";
import type {
  BudgetAndExecution,
  MinistryBudget,
  RecipientIdentification,
  RequestExactlyGranted,
  TypeCount,
} from "../api/client";
import {
  OVERVIEW_UNAVAILABLE_TEXT,
  barWidthPercent,
  cqNumberFromFilename,
  distinctSheetYears,
  exactMatchRatioPercent,
  historyRowYearLabel,
  historySheetYearNote,
  latestFiscalYear,
  localNameFromIri,
  ministriesForFiscalYear,
  ministryDisplayName,
  mostRecentRow,
  percentRangeText,
  recipientCountForCategory,
  recipientTotalAmount,
  requestGrantedPercent,
  requestVsGrantedRows,
  scaleExcludingTopNote,
  sourceCitation,
  sumMinistryBudgets,
  topMinistryDominancePhrase,
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

function budgetRow(overrides: Partial<BudgetAndExecution> = {}): BudgetAndExecution {
  return {
    sheet_year: 2025,
    budget_fiscal_year: 2021,
    initial_budget: 107_148_031_818_947,
    supplementary_budget: 17_309_791_593_000,
    carried_over_from_previous_year: 24_130_080_016_038,
    reserve_fund: 1_640_413_263_509,
    total_budget_available: 150_228_316_691_494,
    executed_amount: 128_147_462_147_862,
    project_count: 3575,
    ...overrides,
  };
}

function requestExactlyGrantedRow(overrides: Partial<RequestExactlyGranted> = {}): RequestExactlyGranted {
  return {
    request_fiscal_year: 2021,
    requested_both: 111_305_746_476_457,
    initial_both: 107_830_651_392_489,
    exact_matches: 1293,
    projects_in_both_years: 3574,
    ...overrides,
  };
}

function recipientRow(overrides: Partial<RecipientIdentification> = {}): RecipientIdentification {
  return {
    category: "resolved",
    total_amount: 57_500_000_000_000,
    expenditure_count: 56_607,
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
// ministriesForFiscalYear: 複数年度が混在したCQ15の行から、指定年度だけを
// 取り出す(修正ラウンド1・レビューS5)。合計・府省数・帯グラフはすべて
// この関数を通した後の行を使う前提。
// =============================================================================

describe("ministriesForFiscalYear", () => {
  it("指定した年度の行だけを、元の順序を保って返す", () => {
    const rows = [
      ministry({ id: "https://…/a", fiscal_year: 2025, total_budget: 3 }),
      ministry({ id: "https://…/b", fiscal_year: 2024, total_budget: 2 }),
      ministry({ id: "https://…/c", fiscal_year: 2025, total_budget: 1 }),
    ];
    expect(ministriesForFiscalYear(rows, 2025).map((m) => m.id)).toEqual([
      "https://…/a",
      "https://…/c",
    ]);
  });

  it("**核心**: 同じ府省IDが同じ年度に2回現れても1回に絞る(重複除去)", () => {
    const rows = [
      ministry({ id: "https://…/a", fiscal_year: 2025 }),
      ministry({ id: "https://…/a", fiscal_year: 2025 }),
    ];
    expect(ministriesForFiscalYear(rows, 2025)).toHaveLength(1);
  });

  it("fiscalYearがnullなら空配列(latestFiscalYearが行なしを返したとき)", () => {
    expect(ministriesForFiscalYear([ministry()], null)).toEqual([]);
  });

  it("一致する年度が無ければ空配列", () => {
    expect(ministriesForFiscalYear([ministry({ fiscal_year: 2024 })], 2025)).toEqual([]);
  });
});

// =============================================================================
// topMinistryDominancePhrase: 「{最大の府省}が全体の{割合}%」。
// 府省名・割合の両方をministriesから導出する(手書きしない。裁定A2/S2)。
// =============================================================================

describe("topMinistryDominancePhrase", () => {
  it("最大の府省の表示名と割合(小数1桁の%)を含む", () => {
    const rows = [
      ministry({ label: "厚生労働省", total_budget: 91_789_031_491_000 }),
      ministry({ label: "こども家庭庁", total_budget: 6_223_531_981_000 }),
    ];
    // 合計は他の21府省を省いた小さい例なので、実データの74.6%ではなく
    // この2件だけの合計に対する割合になる(=93.7%)。手計算で固定する。
    expect(topMinistryDominancePhrase(rows)).toBe("厚生労働省が全体の93.7%");
  });

  it("labelがnullの府省が最大なら、id_pathを使う(表示名を合成しない)", () => {
    const rows = [ministry({ label: null, id_path: "org/9999999999999", total_budget: 10 })];
    expect(topMinistryDominancePhrase(rows)).toBe("org/9999999999999が全体の100.0%");
  });

  it("府省が0件ならnull", () => {
    expect(topMinistryDominancePhrase([])).toBeNull();
  });

  it("合計予算が0以下(=割合を計算できない)ならnull", () => {
    expect(topMinistryDominancePhrase([ministry({ total_budget: 0 })])).toBeNull();
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

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("1項目なら「出所: CQnn」", () => {
    expect(sourceCitation(SOURCES, "ministries")).toBe("出所: CQ15");
  });

  it("複数項目のときは渡した順に・で連結する", () => {
    expect(sourceCitation(SOURCES, "government_paid", "ministries", "type_counts")).toBe(
      "出所: CQ12・CQ15・CQ18",
    );
  });

  it("**核心**: sourcesに無いキーだけを渡すと、空の主張(「出所: 」)ではなくnullを返す(修正ラウンド1・レビューQ1)", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(sourceCitation(SOURCES, "no_such_key")).toBeNull();
  });

  it("無いキーはconsole.errorに出す(調査可能にする。画面には出さない)", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    sourceCitation(SOURCES, "no_such_key");
    expect(spy).toHaveBeenCalledTimes(1);
    expect(String(spy.mock.calls[0]?.[0])).toContain("no_such_key");
  });

  it("**核心**: 一部のキーだけ無いときは、引けた分の出所だけを出す(無いキーはconsole.errorに残るが、画面から出所自体は消さない)", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(sourceCitation(SOURCES, "ministries", "no_such_key", "type_counts")).toBe(
      "出所: CQ15・CQ18",
    );
    expect(spy).toHaveBeenCalledTimes(1);
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

});

// =============================================================================
// barWidthPercent: 帯グラフの幅(線形)。**対数を採らない判断の実体はこの
// 計算そのもの**(修正ラウンド1・レビューQ2)。以前は`renderBars`の中に
// 埋め込まれ、「対数という語を含まない」という文言だけを見るテストで
// 守ろうとしていたが、それは実装を`Math.log`に変えても緑のままだった
// ——ここでは計算結果そのもの(線形であること)を直接固定する。
// =============================================================================

describe("barWidthPercent", () => {
  it("最大値ちょうどなら100", () => {
    expect(barWidthPercent(100, 100)).toBe(100);
  });

  it("**核心**: 線形である(半分の値は必ず50%。対数ならこの値にならない)", () => {
    // 対数(例: log(amount+1)/log(max+1)*100)なら、log(51)/log(101)*100 ≈ 85.5
    // になり50から大きく外れる——この期待値そのものが「線形の判断」を守る。
    expect(barWidthPercent(50, 100)).toBe(50);
    expect(barWidthPercent(1, 100)).toBe(1);
  });

  it("0なら0%", () => {
    expect(barWidthPercent(0, 100)).toBe(0);
  });

  it("maxが0以下なら0%(0除算・負のmaxでも例外を投げない)", () => {
    expect(barWidthPercent(50, 0)).toBe(0);
    expect(barWidthPercent(50, -10)).toBe(0);
  });

  it("amountがmaxを超えても100%で止める(帯が枠から溢れない)", () => {
    expect(barWidthPercent(150, 100)).toBe(100);
  });

  it("amountが負でも0%未満にはしない", () => {
    expect(barWidthPercent(-10, 100)).toBe(0);
  });
});

// =============================================================================
// distinctSheetYears / historyRowYearLabel / historySheetYearNote /
// mostRecentRow: CQ14の複数シート混在を画面が受け止める(修正ラウンド1・
// レビューS5)。
// =============================================================================

describe("distinctSheetYears", () => {
  it("重複を除いた年度を昇順で返す", () => {
    const rows = [budgetRow({ sheet_year: 2025 }), budgetRow({ sheet_year: 2025 }), budgetRow({ sheet_year: 2024 })];
    expect(distinctSheetYears(rows)).toEqual([2024, 2025]);
  });

  it("1種類だけなら1件の配列", () => {
    expect(distinctSheetYears([budgetRow({ sheet_year: 2025 })])).toEqual([2025]);
  });

  it("空配列なら空配列", () => {
    expect(distinctSheetYears([])).toEqual([]);
  });
});

describe("historyRowYearLabel", () => {
  it("シートが1種類なら年度だけ", () => {
    const row = budgetRow({ budget_fiscal_year: 2021, sheet_year: 2025 });
    expect(historyRowYearLabel(row, [2025])).toBe("2021年度");
  });

  it("**核心**: シートが2種類以上混在するときはsheet_yearを併記する(どのシートの主張か区別できるようにする)", () => {
    const row = budgetRow({ budget_fiscal_year: 2021, sheet_year: 2025 });
    expect(historyRowYearLabel(row, [2024, 2025])).toBe("2021年度(2025年度シート)");
  });
});

describe("historySheetYearNote", () => {
  it("シートが1種類のとき、その年度のシートが記録しているという文になる", () => {
    expect(historySheetYearNote([2025])).toBe(
      "この5年分は2025年度のレビューシートが記録しているものです。年度ごとに別のシートを取ってきて並べたのではありません。",
    );
  });

  it("**核心**: シートが2種類以上のとき、単一シートの断言(偽になる文)ではなく混在を正直に書く", () => {
    const text = historySheetYearNote([2024, 2025]);
    expect(text).not.toContain("この5年分は2024年度のレビューシートが記録しているもの");
    expect(text).not.toContain("この5年分は2025年度のレビューシートが記録しているもの");
    expect(text).toContain("2024・2025年度");
  });

  it("年度が1件も無ければ空文字", () => {
    expect(historySheetYearNote([])).toBe("");
  });
});

describe("mostRecentRow", () => {
  it("budget_fiscal_yearが最大の行を返す(配列の並び順を信じない)", () => {
    // 意図的に末尾行を最新年度ではない行にする(2枚目のシートで並び順が
    // budget_fiscal_year単調にならないケースの再現)。
    const rows = [
      budgetRow({ budget_fiscal_year: 2021 }),
      budgetRow({ budget_fiscal_year: 2025 }),
      budgetRow({ budget_fiscal_year: 2020 }),
    ];
    expect(mostRecentRow(rows)?.budget_fiscal_year).toBe(2025);
  });

  it("1行も無ければundefined", () => {
    expect(mostRecentRow([])).toBeUndefined();
  });
});

// =============================================================================
// requestVsGrantedRows: `RequestExactlyGranted`(CQ20。`requested_both`/
// `initial_both`込み)から「年度Yの要求 → 年度Y+1の当初予算」の表示行を
// 作る(トップページ第1層ブリーフTask4修正: 「導出の母集団が正しくなければ
// ならない」)。**核心は`RequestAndInitial`(CQ16)の全事業合計を混ぜない
// こと**——混ぜると新規事業が当初予算側だけを膨らませ、「要求より多く
// 付いた」ように見える見かけの数字になる(実測: 2022→2023年度が104.1%)。
// =============================================================================

describe("requestVsGrantedRows", () => {
  it("CQ20の1行をそのまま表示用の形(年度ラベル・requested/initial)にする", () => {
    const rows = [
      requestExactlyGrantedRow({
        request_fiscal_year: 2021,
        requested_both: 111_305_746_476_457,
        initial_both: 107_830_651_392_489,
        exact_matches: 1293,
        projects_in_both_years: 3574,
      }),
    ];
    const out = requestVsGrantedRows(rows);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      requestYear: 2021,
      grantedYear: 2022,
      requested: 111_305_746_476_457,
      initial: 107_830_651_392_489,
      exactMatches: 1293,
      projectsInBothYears: 3574,
    });
  });

  it("**核心**: RequestAndInitial(CQ16)の全事業合計は使わない。requested/initialはrequested_both/initial_bothそのもの", () => {
    // CQ16基準なら2022→2023年度は104.1%(要求112.3兆・当初117.0兆)になるが、
    // CQ20のrequested_both/initial_bothは新規事業を含まないため99.2%になる
    // (team-lead実測)。この関数はCQ20の値をそのまま渡すだけで、CQ16を
    // 一切参照しない(引数にRequestAndInitialを取らないことがその保証)。
    const rows = [
      requestExactlyGrantedRow({
        request_fiscal_year: 2022,
        requested_both: 112_336_438_903_489,
        initial_both: 111_454_687_976_040,
      }),
    ];
    const out = requestVsGrantedRows(rows)[0]!;
    expect(out.requested).toBe(112_336_438_903_489);
    expect(out.initial).toBe(111_454_687_976_040);
  });

  it("年度が配列の並び順(降順)で渡されても、出力はrequestYear昇順になる", () => {
    const rows = [
      requestExactlyGrantedRow({ request_fiscal_year: 2023 }),
      requestExactlyGrantedRow({ request_fiscal_year: 2021 }),
      requestExactlyGrantedRow({ request_fiscal_year: 2022 }),
    ];
    const out = requestVsGrantedRows(rows);
    expect(out.map((r) => r.requestYear)).toEqual([2021, 2022, 2023]);
  });

  it("空配列なら空配列", () => {
    expect(requestVsGrantedRows([])).toEqual([]);
  });
});

describe("requestGrantedPercent", () => {
  it("initial_both/requested_bothを%で返す", () => {
    const row = requestVsGrantedRows([
      requestExactlyGrantedRow({ requested_both: 111_305_746_476_457, initial_both: 107_830_651_392_489 }),
    ])[0]!;
    expect(requestGrantedPercent(row)).toBeCloseTo(96.9, 1);
  });

  it("要求額が0以下なら計算できないのでnull", () => {
    const row = requestVsGrantedRows([requestExactlyGrantedRow({ requested_both: 0 })])[0]!;
    expect(requestGrantedPercent(row)).toBeNull();
  });
});

describe("exactMatchRatioPercent", () => {
  it("exact_matches/projects_in_both_yearsを%で返す", () => {
    const row = requestVsGrantedRows([
      requestExactlyGrantedRow({ exact_matches: 1293, projects_in_both_years: 3574 }),
    ])[0]!;
    expect(exactMatchRatioPercent(row)).toBeCloseTo(36.2, 1);
  });

  it("分母(projects_in_both_years)が0以下ならnull", () => {
    const row = requestVsGrantedRows([
      requestExactlyGrantedRow({ exact_matches: 0, projects_in_both_years: 0 }),
    ])[0]!;
    expect(exactMatchRatioPercent(row)).toBeNull();
  });
});

describe("percentRangeText", () => {
  it("複数の値があれば最小〜最大を「96.9〜99.4%」の形にする", () => {
    expect(percentRangeText([96.9, 99.4, 98.1])).toBe("96.9〜99.4%");
  });

  it("**核心**: 全て同じ値(または1件)なら範囲(〜)にせず単一の%にする", () => {
    expect(percentRangeText([96.9])).toBe("96.9%");
    expect(percentRangeText([50, 50])).toBe("50.0%");
  });

  it("空配列ならnull", () => {
    expect(percentRangeText([])).toBeNull();
  });
});

// =============================================================================
// recipientTotalAmount / recipientCountForCategory: CQ17の4区分から
// 合計・件数を導出する(手書きの対応表を作らない。Step3)。
// =============================================================================

describe("recipientTotalAmount", () => {
  it("4区分の金額を合計する(排他的な分割なので合計してよい)", () => {
    const rows = [
      recipientRow({ category: "resolved", total_amount: 57_500_000_000_000 }),
      recipientRow({ category: "bundled", total_amount: 93_000_000_000_000 }),
    ];
    expect(recipientTotalAmount(rows)).toBe(150_500_000_000_000);
  });

  it("空配列なら0", () => {
    expect(recipientTotalAmount([])).toBe(0);
  });
});

describe("recipientCountForCategory", () => {
  const ROWS: RecipientIdentification[] = [
    recipientRow({ category: "resolved", expenditure_count: 56_607 }),
    recipientRow({ category: "unresolved", expenditure_count: 42 }),
  ];

  it("一致する区分の件数を返す", () => {
    expect(recipientCountForCategory(ROWS, "unresolved")).toBe(42);
  });

  it("**核心**: 一致する区分が無ければ0ではなくnull(欠損を既定値に落とさない)", () => {
    expect(recipientCountForCategory(ROWS, "sentinel_or_nonexistent_houjin_bangou")).toBeNull();
  });

  it("空配列でもnull", () => {
    expect(recipientCountForCategory([], "resolved")).toBeNull();
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
