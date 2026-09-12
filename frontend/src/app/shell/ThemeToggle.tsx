import { useEffect, useState, useSyncExternalStore, type JSX } from "react";
import {
  THEME_STORAGE_KEY,
  applyPreference,
  nextPreference,
  readStoredPreference,
  resolveTheme,
  type ThemePreference,
} from "../theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

// jsdom(vitest)には window.matchMedia が無い。無い環境では「OSはライト」とみなし、
// 購読もしない——テストのためだけに matchMedia をモックで生やすより、
// 部品が無い環境でも壊れないほうを採る。
function subscribeSystemDark(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const mq = window.matchMedia(DARK_QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}
function getSystemDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

function safeStorage(): Pick<Storage, "getItem" | "setItem"> {
  // プライベートウィンドウ等で localStorage が投げる環境でも画面を止めない。
  try {
    return window.localStorage;
  } catch {
    return { getItem: () => null, setItem: () => undefined };
  }
}

// ライト/ダークの切替。ボタンは「いま見えている色の反対」を明示設定にする(theme.ts)。
// **既知の制限(Phase 0)**: 旧 entity 画面の Sigma ラベル色は views/graph.ts が
// prefers-color-scheme の変化しか購読していないため、このボタンで切り替えても
// グラフ内の文字色は再読み込みまで追随しない。Phase 3 のワークベンチで graph-theme.ts
// を data-theme の変化にも追随させる。
export function ThemeToggle(): JSX.Element {
  const [pref, setPref] = useState<ThemePreference>(() => readStoredPreference(safeStorage()));
  const systemDark = useSyncExternalStore(subscribeSystemDark, getSystemDark, getSystemDark);
  const resolved = resolveTheme(pref, systemDark);

  useEffect(() => {
    applyPreference(document.documentElement, pref);
    if (pref !== "system") safeStorage().setItem(THEME_STORAGE_KEY, pref);
  }, [pref]);

  const target = nextPreference(resolved);
  const targetLabel = target === "dark" ? "ダーク" : "ライト";
  return (
    <button
      type="button"
      className="jgkg-theme-toggle"
      aria-label={`表示を${targetLabel}に切り替える`}
      onClick={() => setPref(target)}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        {resolved === "dark" ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          </>
        ) : (
          <path d="M12 3a9 9 0 1 0 9 9c-5 0-9-4-9-9z" />
        )}
      </svg>
      <span>{targetLabel}</span>
    </button>
  );
}
