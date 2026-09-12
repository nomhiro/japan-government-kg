import type { JSX } from "react";
import { navigate, type Route } from "../router";
import { renderChat } from "../views/chat";
import { renderEntity } from "../views/entity";
import { renderPath } from "../views/path";
import { renderSearch } from "../views/search";
import { LegacyView, type LegacyController } from "./LegacyView";
import { AppShell } from "./shell/AppShell";
import { useRoute } from "./useRoute";

// **移行中の状態**(裁定B106)。新しい画面(features/*)を1つずつ差し替えている。
// まだ React になっていないルートは LegacyView 経由で旧ビューを載せる。
// 旧ビューが全部消えたら LegacyView と views/ ごと削除する。
function mountLegacy(el: HTMLElement, route: Route): LegacyController | void {
  switch (route.name) {
    case "top":
      // 新トップができるまでは旧検索画面(検索窓+第1層)を出す。
      renderSearch(el, "");
      return;
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
    case "data":
    case "notFound":
      return;
  }
}

function NotFound({ hash }: { hash: string }): JSX.Element {
  return (
    <div className="jg-band">
      <div className="jg-inner jg-stack jg-stack--4" style={{ paddingBlock: "var(--sp-9)" }}>
        <span className="jg-eyebrow">404</span>
        <h1 className="jg-h1">このページはありません</h1>
        <p className="jg-lead">
          <code>{hash || "(空)"}</code> に対応する画面がありません。リンクが古いか、URLが途中で切れている可能性があります。
        </p>
        <div className="jg-row">
          <button type="button" className="jg-btn jg-btn--primary" onClick={() => navigate({ name: "top" })}>
            全体を見る
          </button>
          <button type="button" className="jg-btn" onClick={() => navigate({ name: "search", q: "" })}>
            探す
          </button>
        </div>
      </div>
    </div>
  );
}

function Placeholder({ title }: { title: string }): JSX.Element {
  return (
    <div className="jg-band">
      <div className="jg-inner jg-stack jg-stack--4" style={{ paddingBlock: "var(--sp-9)" }}>
        <h1 className="jg-h1">{title}</h1>
        <p className="jg-lead">この画面はいま作っています。</p>
      </div>
    </div>
  );
}

export function App(): JSX.Element {
  const route = useRoute();

  let body: JSX.Element;
  if (route.name === "notFound") {
    body = <NotFound hash={route.hash} />;
  } else if (route.name === "data") {
    body = <Placeholder title="データとAPI" />;
  } else {
    // ハッシュ文字列を key にする = ハッシュが変わるたびに旧ビューを破棄して描き直す
    // (旧 main.ts と同じ挙動)。
    body = <LegacyView key={JSON.stringify(route)} mount={(el) => mountLegacy(el, route)} />;
  }

  return <AppShell route={route}>{body}</AppShell>;
}
