import { describe, expect, it } from "vitest";
import {
  THEME_STORAGE_KEY,
  applyPreference,
  nextPreference,
  readStoredPreference,
  resolveTheme,
} from "./theme";

describe("resolveTheme", () => {
  it("system はOSの設定に従う", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
  it("明示の設定はOSの設定より優先する", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("nextPreference(切替ボタンは「いま見えている色の反対」を明示設定にする)", () => {
  it("ライトが見えていればダークへ、ダークが見えていればライトへ", () => {
    expect(nextPreference("light")).toBe("dark");
    expect(nextPreference("dark")).toBe("light");
  });
});

describe("readStoredPreference", () => {
  const storageWith = (value: string | null) => ({ getItem: (_k: string) => value });
  it("保存が無ければ system", () => {
    expect(readStoredPreference(storageWith(null))).toBe("system");
  });
  it("light/dark はそのまま返す", () => {
    expect(readStoredPreference(storageWith("light"))).toBe("light");
    expect(readStoredPreference(storageWith("dark"))).toBe("dark");
  });
  it("壊れた値は system に落とす(黙って dark にしない)", () => {
    expect(readStoredPreference(storageWith("purple"))).toBe("system");
  });
  it("鍵名は固定", () => {
    expect(THEME_STORAGE_KEY).toBe("jgkg-theme");
  });
});

describe("applyPreference(ルート要素の data-theme を書く/消す)", () => {
  function fakeRoot() {
    const attrs = new Map<string, string>();
    return {
      attrs,
      setAttribute: (k: string, v: string) => void attrs.set(k, v),
      removeAttribute: (k: string) => void attrs.delete(k),
    };
  }
  it("light/dark は data-theme を書く", () => {
    const root = fakeRoot();
    applyPreference(root, "dark");
    expect(root.attrs.get("data-theme")).toBe("dark");
    applyPreference(root, "light");
    expect(root.attrs.get("data-theme")).toBe("light");
  });
  it("system は data-theme を消す(CSS の prefers-color-scheme に任せる)", () => {
    const root = fakeRoot();
    applyPreference(root, "dark");
    applyPreference(root, "system");
    expect(root.attrs.has("data-theme")).toBe(false);
  });
});
