import { useMemo, useSyncExternalStore } from "react";
import { parseHash, type Route } from "../router";

// ハッシュルータ(router.ts)の React 側の入口。**購読するのは文字列の
// location.hash であって Route オブジェクトではない**——useSyncExternalStore の
// getSnapshot は同じ状態に対して同じ参照を返す必要があり、parseHash は毎回
// 新しいオブジェクトを作るため、そのまま snapshot にすると無限再描画になる。
// 文字列を snapshot にし、Route への変換は useMemo で hash が変わったときだけ行う。

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function getSnapshot(): string {
  return location.hash;
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return useMemo(() => parseHash(hash), [hash]);
}
