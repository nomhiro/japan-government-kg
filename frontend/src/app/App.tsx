import type { JSX } from "react";
import { routeToHash, type Route } from "../router";
import { renderChat } from "../views/chat";
import { renderEntity } from "../views/entity";
import { renderPath } from "../views/path";
import { renderSearch } from "../views/search";
import { LegacyView, type LegacyController } from "./LegacyView";
import { AppShell } from "./shell/AppShell";
import { useRoute } from "./useRoute";

// ルート → 画面の対応表。Phase 0 では全ルートが旧ビュー(LegacyView 経由)。
// 以降の Phase で1画面ずつ React コンポーネントに差し替える(仕様 §4 移行方式)。
function mountLegacy(el: HTMLElement, route: Route): LegacyController | void {
  switch (route.name) {
    case "search":
      renderSearch(el, route.q);
      return;
    case "entity":
      return renderEntity(el, route.idPath);
    case "path":
      renderPath(el, route.from, route.to);
      return;
    case "chat":
      renderChat(el);
      return;
  }
}

export function App(): JSX.Element {
  const route = useRoute();
  // ハッシュ文字列を key にする = ハッシュが変わるたびに旧ビューを破棄して描き直す(旧 main.ts と同じ挙動)。
  // 検索ビューは入力中にハッシュを書き換えない(views/search.ts はクリック時の navigate だけ)ので、入力途中で再マウントされることはない。
  return (
    <AppShell route={route}>
      <LegacyView key={routeToHash(route)} mount={(el) => mountLegacy(el, route)} />
    </AppShell>
  );
}
