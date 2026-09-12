// テーマ(ライト/ダーク)の判断だけを置く。DOM・localStorage・matchMedia の
// 実物には触らない(引き渡された最小インターフェースだけを使う)ので Node 環境の
// vitest で全分岐を検査できる——graph-theme.ts と同じ規律。
//
// CSS 側の契約(styles/tokens.css):
//   :root                                   … ライトの値
//   @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { … } } … OS がダークで、明示ライトでないとき
//   :root[data-theme="dark"]                … 明示ダーク
// だから "system" は data-theme を**消す**ことで表現する。

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "jgkg-theme";

export function readStoredPreference(storage: Pick<Storage, "getItem">): ThemePreference {
  const v = storage.getItem(THEME_STORAGE_KEY);
  return v === "light" || v === "dark" ? v : "system";
}

export function resolveTheme(pref: ThemePreference, systemDark: boolean): ResolvedTheme {
  if (pref === "system") return systemDark ? "dark" : "light";
  return pref;
}

export function nextPreference(resolved: ResolvedTheme): ThemePreference {
  return resolved === "dark" ? "light" : "dark";
}

export function applyPreference(
  root: Pick<HTMLElement, "setAttribute" | "removeAttribute">,
  pref: ThemePreference,
): void {
  if (pref === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", pref);
  }
}
