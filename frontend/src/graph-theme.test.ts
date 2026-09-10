import { describe, expect, it } from "vitest";
import { readGraphTheme } from "./graph-theme";

function style(values: Record<string, string>) {
  return { getPropertyValue: (name: string) => values[name] ?? "" };
}

// =============================================================================
// readGraphTheme: グラフの色をCSSのトークンから読む(裁定B95)。
//
// **Sigma.jsはCSSを見ない。** `labelColor`を明示しないとノードラベルは
// 黒(`#000`)で描かれ、ダークモードで**キャンバスの文字だけが読めなくなる**
// ——ユーザーが報告した症状そのもの。
// =============================================================================

describe("readGraphTheme", () => {
  it("ライトモードのトークンをそのまま読む", () => {
    expect(readGraphTheme(style({ "--ink": "#16191d", "--muted": "#5c636d" }))).toEqual({
      label: "#16191d",
      edge: "#5c636d",
    });
  });

  it("**ダークモードのトークンを読む(黒を返さない)**", () => {
    const theme = readGraphTheme(style({ "--ink": "#e7e4de", "--muted": "#a1a8b2" }));
    expect(theme).toEqual({ label: "#e7e4de", edge: "#a1a8b2" });
    // **これが要点**: ダークのトークンを渡したら黒が返ってはいけない
    expect(theme.label).not.toBe("#000");
    expect(theme.label).not.toBe("#16191d");
  });

  it("トークンが読めなければライトモードの値に落とす(白背景に白文字を作らない)", () => {
    // `getPropertyValue`は未定義のプロパティに空文字列を返す(例外にならない)
    const theme = readGraphTheme(style({}));
    expect(theme.label).toBe("#16191d");
    expect(theme.edge).toBe("#5c636d");
  });

  it("前後の空白を落とす(CSSの値は空白付きで返ることがある)", () => {
    expect(readGraphTheme(style({ "--ink": "  #abcdef  ", "--muted": " #123456 " }))).toEqual({
      label: "#abcdef",
      edge: "#123456",
    });
  });
});
