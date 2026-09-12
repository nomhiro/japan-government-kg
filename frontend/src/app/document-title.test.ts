import { describe, expect, it } from "vitest";
import { SITE_NAME, pageTitle, titleForRoute } from "./document-title";

describe("pageTitle", () => {
  it("画面名とサイト名を繋ぐ", () => {
    expect(pageTitle("探す")).toBe(`探す — ${SITE_NAME}`);
  });
});

describe("titleForRoute", () => {
  it("トップ", () => {
    expect(titleForRoute({ name: "top" })).toBe(`全体を見る — ${SITE_NAME}`);
  });

  it("検索語があれば題に入れる(どのタブがどの検索か分かるように)", () => {
    expect(titleForRoute({ name: "search", q: "年金" })).toBe(
      `「年金」の検索結果 — ${SITE_NAME}`,
    );
  });

  it("検索語が空(または空白だけ)なら「探す」", () => {
    expect(titleForRoute({ name: "search", q: "" })).toBe(`探す — ${SITE_NAME}`);
    expect(titleForRoute({ name: "search", q: "   " })).toBe(`探す — ${SITE_NAME}`);
  });

  it("エンティティはnull —— 表示名が要るので画面側が決める", () => {
    expect(titleForRoute({ name: "entity", idPath: "org/6000012070001" })).toBeNull();
  });

  it("経路・聞く・データとAPI・404", () => {
    expect(titleForRoute({ name: "path" })).toBe(`経路をたどる — ${SITE_NAME}`);
    expect(titleForRoute({ name: "chat" })).toBe(`聞く — ${SITE_NAME}`);
    expect(titleForRoute({ name: "data" })).toBe(`データとAPI — ${SITE_NAME}`);
    expect(titleForRoute({ name: "notFound", hash: "#/nope" })).toBe(
      `このページはありません — ${SITE_NAME}`,
    );
  });

  it("どのルートでもサイト名で終わる(タブが狭くても何のサイトか分かる)", () => {
    const routes = [
      { name: "top" } as const,
      { name: "search", q: "年金" } as const,
      { name: "path" } as const,
      { name: "chat" } as const,
      { name: "data" } as const,
      { name: "notFound", hash: "" } as const,
    ];
    for (const route of routes) {
      expect(titleForRoute(route)).toMatch(new RegExp(`${SITE_NAME}$`));
    }
  });
});
