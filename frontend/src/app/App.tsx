import type { JSX } from "react";
import { ChatPage } from "../features/chat/ChatPage";
import { DataPage } from "../features/data/DataPage";
import { EntityPage } from "../features/entity/EntityPage";
import { TopPage } from "../features/overview/TopPage";
import { PathPage } from "../features/path/PathPage";
import { SearchPage } from "../features/search/SearchPage";
import { navigate } from "../router";
import { AppShell } from "./shell/AppShell";
import { useRoute } from "./useRoute";

// ルート → 画面。すべて React(裁定B106)。
// 旧ビュー(`views/*.ts` の innerHTML 方式)と、それを載せていた `LegacyView` は
// この結線と同時に削除した —— Strangler の橋はもう要らない。

function NotFound({ hash }: { hash: string }): JSX.Element {
  return (
    <div className="jg-band">
      <div className="jg-inner jg-stack jg-stack--5 jg-notfound">
        <span className="jg-eyebrow">404</span>
        <h1 className="jg-h1">このページはありません</h1>
        <p className="jg-lead">
          <code>{hash || "(空)"}</code> に対応する画面がありません。リンクが古いか、URLが途中で切れている可能性があります。
        </p>
        <div className="jg-row">
          <button
            type="button"
            className="jg-btn jg-btn--primary"
            onClick={() => navigate({ name: "top" })}
          >
            全体を見る
          </button>
          <button
            type="button"
            className="jg-btn"
            onClick={() => navigate({ name: "search", q: "" })}
          >
            探す
          </button>
        </div>
      </div>
    </div>
  );
}

function Body({ route }: { route: ReturnType<typeof useRoute> }): JSX.Element {
  switch (route.name) {
    case "top":
      return <TopPage />;
    case "search":
      return <SearchPage q={route.q} />;
    case "entity":
      // key を付けて、別のエンティティへ移ったら状態(選択・展開)を持ち越さない。
      return <EntityPage key={route.idPath} idPath={route.idPath} />;
    case "path":
      return <PathPage from={route.from} to={route.to} />;
    case "chat":
      return <ChatPage />;
    case "data":
      return <DataPage />;
    case "notFound":
      return <NotFound hash={route.hash} />;
  }
}

export function App(): JSX.Element {
  const route = useRoute();
  return (
    <AppShell route={route}>
      <Body route={route} />
    </AppShell>
  );
}
