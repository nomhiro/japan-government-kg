// `entity-model.ts`の純関数のテスト。実APIの応答サンプル
// (`.superpowers/apisamples/entity-*.json`)を使う(架空の政府データを作らない)。
// マーカー計算(複数出典の対応付け)だけは、実データにその状況が無いため、
// 最小限の合成データ(政府データではない。構造だけを確認する目的)で検査する。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { EntityDetailResponse } from "../../api/client";
import {
  AMOUNT_PREDICATES,
  breadcrumbMinistryRef,
  directionArrow,
  displayLabel,
  firstAttributeValue,
  graphCaveatText,
  isAmountPredicate,
  kindOf,
  kindOneLiner,
  markerGlyph,
  NO_LABEL,
  omitRelationshipTypes,
  relationshipsGroupedFromTypes,
  relationshipsOfType,
  sectionSourceLines,
  sortedRelationshipGroups,
  totalRelationshipCount,
  valueSourceMarkers,
} from "./entity-model";

const REPO_ROOT = fileURLToPath(new URL("../../../../", import.meta.url));

function readJson<T>(relPath: string): T {
  return JSON.parse(readFileSync(`${REPO_ROOT}${relPath}`, "utf-8")) as T;
}

function entityMinistry(): EntityDetailResponse {
  return readJson<EntityDetailResponse>(".superpowers/apisamples/entity-ministry.json");
}

function entityProject(): EntityDetailResponse {
  return readJson<EntityDetailResponse>(".superpowers/apisamples/entity-project.json");
}

describe("kindOf(型からの表示分岐)", () => {
  it.each([
    ["Ministry", "ministry"],
    ["GovernmentOrgan", "ministry"],
    ["AbolishedGovernmentOrgan", "ministry"],
    ["BudgetProject", "project"],
    ["Organization", "organization"],
    ["Law", "law"],
    ["Expenditure", "expenditure"],
    ["ExpenditureBlock", "generic"],
    ["AnnualBudget", "generic"],
    ["UnresolvedReference", "generic"],
    ["何か知らない型", "generic"],
  ] as const)("%s -> %s", (type, expected) => {
    expect(kindOf(type)).toBe(expected);
  });
});

describe("relationshipsOfType(実データ: 厚生労働省)", () => {
  const entity = entityMinistry();

  it("フィルタ無しなら型の全件を返す", () => {
    expect(relationshipsOfType(entity, "BudgetProject")).toEqual(entity.relationships.BudgetProject);
  });

  it("実データの全行が predicate=ministry / direction=incoming なので、絞っても件数が変わらない", () => {
    const filtered = relationshipsOfType(entity, "BudgetProject", { predicate: "ministry", direction: "incoming" });
    expect(filtered).toEqual(entity.relationships.BudgetProject);
    expect(filtered.length).toBeGreaterThan(0);
  });

  it("一致しない predicate では空配列(捏造しない)", () => {
    expect(relationshipsOfType(entity, "BudgetProject", { predicate: "basisLaw" })).toEqual([]);
  });

  it("存在しない型キーは空配列", () => {
    expect(relationshipsOfType(entity, "Law")).toEqual([]);
  });
});

describe("relationshipsOfType(実データ: 予算事業)", () => {
  const entity = entityProject();

  it("Ministry関係(outgoing・ministry)を1件返す", () => {
    const rels = relationshipsOfType(entity, "Ministry", { predicate: "ministry", direction: "outgoing" });
    expect(rels).toHaveLength(1);
    expect(rels[0]?.related.label).toBe("厚生労働省");
  });

  it("UnresolvedReference関係(incoming・unresolvedFor)を実データの件数通り返す", () => {
    const rels = relationshipsOfType(entity, "UnresolvedReference", { predicate: "unresolvedFor", direction: "incoming" });
    expect(rels).toEqual(entity.relationships.UnresolvedReference);
  });
});

describe("omitRelationshipTypes / totalRelationshipCount / sortedRelationshipGroups", () => {
  const entity = entityProject();

  it("指定した型を除いた残りを返す(他の型はそのまま)", () => {
    const rest = omitRelationshipTypes(entity.relationships, ["Ministry", "Expenditure"]);
    expect(Object.keys(rest).sort()).toEqual(["AnnualBudget", "ExpenditureBlock", "UnresolvedReference"].sort());
    expect(rest.AnnualBudget).toEqual(entity.relationships.AnnualBudget);
  });

  it("元のオブジェクトを変更しない", () => {
    omitRelationshipTypes(entity.relationships, ["Ministry"]);
    expect(entity.relationships.Ministry).toBeDefined();
  });

  it("全型を除けば空オブジェクト", () => {
    expect(omitRelationshipTypes(entity.relationships, Object.keys(entity.relationships))).toEqual({});
  });

  it("総件数は各型の件数の合計", () => {
    const expected = Object.values(entity.relationships).reduce((n, rs) => n + rs.length, 0);
    expect(totalRelationshipCount(entity.relationships)).toBe(expected);
  });

  it("件数の多い順に並ぶ(同数はローカル名の辞書順)", () => {
    const sorted = sortedRelationshipGroups(entity.relationships);
    for (let i = 1; i < sorted.length; i++) {
      const prev = sorted[i - 1]!;
      const cur = sorted[i]!;
      expect(prev[1].length >= cur[1].length).toBe(true);
    }
  });
});

describe("relationshipsGroupedFromTypes(候補型のうち実在した型だけをキーにする)", () => {
  it("予算事業のMinistry関係だけが見つかり、他の候補型キーは作らない", () => {
    const entity = entityProject();
    const grouped = relationshipsGroupedFromTypes(
      entity,
      ["Ministry", "GovernmentOrgan", "AbolishedGovernmentOrgan", "Organization"],
      { predicate: "ministry", direction: "outgoing" },
    );
    expect(Object.keys(grouped)).toEqual(["Ministry"]);
    expect(grouped.Ministry).toEqual(entity.relationships.Ministry);
  });

  it("どの候補型にも該当が無ければ空オブジェクト", () => {
    const entity = entityMinistry();
    expect(relationshipsGroupedFromTypes(entity, ["Law", "Organization"], { predicate: "jurisdiction" })).toEqual({});
  });
});

describe("breadcrumbMinistryRef(パンくずの所管)", () => {
  it("予算事業は所管府省(厚生労働省)を返す", () => {
    const ref = breadcrumbMinistryRef(entityProject());
    expect(ref?.label).toBe("厚生労働省");
    expect(ref?.id_path).toBe("org/6000012070001");
  });

  it("府省自身には所管が無い(undefined。合成しない)", () => {
    expect(breadcrumbMinistryRef(entityMinistry())).toBeUndefined();
  });
});

describe("firstAttributeValue / isAmountPredicate", () => {
  it("予算額の属性値をそのまま返す(丸めない・変換しない)", () => {
    expect(firstAttributeValue(entityProject(), "budgetAmount")?.value).toBe("4628011000");
  });

  it("存在しない属性は undefined(値を捏造しない)", () => {
    expect(firstAttributeValue(entityProject(), "存在しない述語")).toBeUndefined();
  });

  it("金額スロットの一覧に budgetAmount / amount_jpy 等が含まれる", () => {
    expect(isAmountPredicate("budgetAmount")).toBe(true);
    expect(isAmountPredicate("amount_jpy")).toBe(true);
    expect(isAmountPredicate("fiscalYear")).toBe(false);
    expect(AMOUNT_PREDICATES.has("totalBudgetAvailable")).toBe(true);
  });
});

describe("displayLabel / directionArrow / NO_LABEL", () => {
  it("labelがnullなら既定文言(表示名を合成しない)", () => {
    expect(displayLabel({ label: null })).toBe(NO_LABEL);
    expect(displayLabel({ label: "厚生労働省" })).toBe("厚生労働省");
  });

  it("labelが無くても見分けのための属性があれば、述語のラベルを添えて出す(裁定B108)", () => {
    expect(
      displayLabel({ label: null, described_by: { predicate: "budgetFiscalYear", value: "2024" } }),
    ).toBe("予算年度 2024");
  });

  it("表示名があれば、見分けのための属性より表示名が勝つ", () => {
    expect(
      displayLabel({ label: "厚生労働省", described_by: { predicate: "budgetFiscalYear", value: "2024" } }),
    ).toBe("厚生労働省");
  });

  it("incoming=← / outgoing=→", () => {
    expect(directionArrow("incoming")).toBe("←");
    expect(directionArrow("outgoing")).toBe("→");
  });
});

describe("sectionSourceLines / valueSourceMarkers(実データ: 出典が1本に畳まれる場合)", () => {
  const entity = entityMinistry();
  // 4属性すべてが houjin-bangou / houjin-bangou-payees の2グラフを主張元に持つ。
  // 2グラフは同じURL・同じ取得日・同じライセンスなので、sourceLinesは1行に畳む。
  const allValues = Object.values(entity.attributes).flat();

  it("実データでは1行に畳まれる", () => {
    const lines = sectionSourceLines(entity.graphs, allValues);
    expect(lines).toHaveLength(1);
    expect(lines[0]?.host).toBe("www.houjin-bangou.nta.go.jp");
  });

  it("出典が1行だけなら、値に印を付けない(印を振っても意味を持たないため)", () => {
    const lines = sectionSourceLines(entity.graphs, allValues);
    for (const v of allValues) {
      expect(valueSourceMarkers(entity.graphs, lines, v)).toEqual([]);
    }
  });
});

describe("valueSourceMarkers(合成データ: 節に2つの出典が混在する場合)", () => {
  // 実データにこの状況(1つの節で出典が2つに分かれる)がまだ無いため、
  // マーカー計算のロジックだけを検査する最小限の構造データ(政府データではない)。
  const graphs: EntityDetailResponse["graphs"] = {
    "graph/a": { graph: "graph/a", source: "https://a.example.jp/x", fetched_on: "2026-01-01", license: "L1", available: true },
    "graph/b": { graph: "graph/b", source: "https://b.example.jp/y", fetched_on: "2026-02-02", license: "L2", available: true },
    "graph/c": { graph: "graph/c", source: "", fetched_on: "", license: "", available: false },
  };
  const valueFromA = { graphs: ["graph/a"] };
  const valueFromB = { graphs: ["graph/b"] };
  const valueFromBoth = { graphs: ["graph/a", "graph/b"] };
  const valueUnavailable = { graphs: ["graph/c"] };

  it("2出典なら節の出典行は2行(取得日の新しい順)", () => {
    const lines = sectionSourceLines(graphs, [valueFromA, valueFromB]);
    expect(lines.map((l) => l.host)).toEqual(["b.example.jp", "a.example.jp"]);
  });

  it("各値は自分の出典に対応する行番号(1始まり)だけを持つ", () => {
    const lines = sectionSourceLines(graphs, [valueFromA, valueFromB, valueFromBoth]);
    // lines[0] = b.example.jp(新しい), lines[1] = a.example.jp
    expect(valueSourceMarkers(graphs, lines, valueFromB)).toEqual([1]);
    expect(valueSourceMarkers(graphs, lines, valueFromA)).toEqual([2]);
    expect(valueSourceMarkers(graphs, lines, valueFromBoth)).toEqual([1, 2]);
  });

  it("出典が取れていないグラフは、そのグラフ単位で別行(他のavailable:falseと混ぜて畳まない)", () => {
    const lines = sectionSourceLines(graphs, [valueFromA, valueUnavailable]);
    expect(lines).toHaveLength(2);
    const marks = valueSourceMarkers(graphs, lines, valueUnavailable);
    expect(marks).toHaveLength(1);
    expect(lines[marks[0]! - 1]?.available).toBe(false);
  });
});

describe("kindOneLiner / graphCaveatText(型ごとの固定コピー)", () => {
  it("すべての型で空文字にならない", () => {
    for (const kind of ["ministry", "project", "organization", "law", "expenditure", "generic"] as const) {
      expect(kindOneLiner(kind).length).toBeGreaterThan(0);
      expect(graphCaveatText(kind).length).toBeGreaterThan(0);
    }
  });

  it("法令だけ、改正記録が近傍に現れないことに触れる(観察O10)", () => {
    expect(graphCaveatText("law")).toContain("改正");
    expect(graphCaveatText("ministry")).not.toContain("改正");
  });
});

describe("markerGlyph", () => {
  it("1〜20は丸数字", () => {
    expect(markerGlyph(1)).toBe("①");
    expect(markerGlyph(20)).toBe("⑳");
  });

  it("21以上は括弧数字に落とす", () => {
    expect(markerGlyph(21)).toBe("(21)");
  });
});
