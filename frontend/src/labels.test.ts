import { describe, expect, it, vi } from "vitest";

// **`generated/labels.json`をモックする。** 実際の生成物(オントロジーの
// dcterms:titleから導出。裁定B78)を使うと、オントロジーが変わるたびに
// このテストの前提(「この型は表示名を持つ/持たない」)が崩れる——
// ここで検査したいのは「表示名がある/無いときの`typeLabel`/`predicateLabel`
// の振る舞い」であって、いま実際に何が翻訳済みかではない。
vi.mock("./generated/labels.json", () => ({
  default: {
    types: { Law: "法令" },
    predicates: { basisLaw: "根拠法令" },
    enumValues: { recipientMatchCategory: { resolved: "法人番号で特定できた" } },
  },
}));

import { enumValueLabel, predicateLabel, typeLabel } from "./labels";

// =============================================================================
// 表示名の引き当て(D-5ブリーフ「専門用語を避けた表示名」・裁定B78)
// =============================================================================

describe("typeLabel", () => {
  it("dcterms:titleがある型は日本語表示名を返す", () => {
    expect(typeLabel("Law")).toBe("法令");
  });

  it("**フォールバック**: dcterms:titleが無い型(裁定B78の対象外)はローカル名をそのまま返す", () => {
    // 列挙型の許容値(resolved/bundled等)や、まだ表示名が付いていない型が
    // ここを通る。手書きの対応表で補わず、技術名がそのまま出ることで
    // 「表示名が未整備」であることが利用者にも(専門家には)分かる形にする。
    expect(typeLabel("RecipientMatchCategoryEnum")).toBe("RecipientMatchCategoryEnum");
  });
});

describe("predicateLabel", () => {
  it("dcterms:titleがある述語は日本語表示名を返す", () => {
    expect(predicateLabel("basisLaw")).toBe("根拠法令");
  });

  it("フォールバック: dcterms:titleが無い述語はローカル名をそのまま返す", () => {
    expect(predicateLabel("unresolved_reason")).toBe("unresolved_reason");
  });
});

describe("enumValueLabel", () => {
  it("表示名がある述語+値の組は日本語表示名を返す", () => {
    expect(enumValueLabel("recipientMatchCategory", "resolved")).toBe("法人番号で特定できた");
  });

  it("フォールバック: 値が未翻訳(表示名テーブルに無い)なら値をそのまま返す", () => {
    // recipientMatchCategoryは表示名テーブルに載っているが、"bundled"は
    // このモックには無い——`resolved`だけを持つ述語でも他の値まで
    // 引けてしまわないことを確認する
    expect(enumValueLabel("recipientMatchCategory", "bundled")).toBe("bundled");
  });

  it("フォールバック: 列挙型を範囲に持たない述語なら値をそのまま返す", () => {
    expect(enumValueLabel("basisLaw", "resolved")).toBe("resolved");
  });
});
