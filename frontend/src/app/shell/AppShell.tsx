import { useRef, type JSX, type ReactNode } from "react";
import type { Route } from "../../router";
import { Omnibox } from "./Omnibox";
import { ThemeToggle } from "./ThemeToggle";
import "./shell.css";

// 共通シェル(仕様 §2.1): 告知(index.html の静的 div。ここでは描かない)の下に
// header(ワードマーク・オムニボックス・ナビ・テーマ切替)と main。
// Phase 0 のナビは**いま存在するルートだけ**を並べる。「つながりを辿る」(#/explore)は
// Phase 3、「データとAPI」(#/data)は Phase 1 で足す——存在しないハッシュへのリンクは
// ルータのフォールバックで検索へ落ちるので、置かない。

interface NavItem {
  label: string;
  href: string;
  isActive: (route: Route) => boolean;
}

const NAV: readonly NavItem[] = [
  { label: "全体を見る", href: "#/", isActive: (r) => r.name === "search" },
  { label: "経路", href: "#/path", isActive: (r) => r.name === "path" },
  { label: "聞く", href: "#/chat", isActive: (r) => r.name === "chat" },
];

export function AppShell({ route, children }: { route: Route; children: ReactNode }): JSX.Element {
  const mainRef = useRef<HTMLElement>(null);
  return (
    <div className="jgkg-shell">
      {/* スキップは <a href="#main"> にしない——ハッシュルータが "#main" を検索ルートに
          解釈して画面遷移してしまう。ボタンで main にフォーカスを移す。 */}
      <button type="button" className="jgkg-skip" onClick={() => mainRef.current?.focus()}>
        本文へ移動
      </button>
      <header className="jgkg-shell-header">
        <a className="jgkg-brand" href="#/">
          <span className="jgkg-brand-name">日本政府ナレッジグラフ</span>
          <span className="jgkg-brand-sub">非公式・第三者による構造化データ</span>
        </a>
        {route.name !== "search" ? <Omnibox /> : null}
        <nav className="jgkg-shell-nav" aria-label="主要なページ">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              aria-current={item.isActive(route) ? "page" : undefined}
            >
              {item.label}
            </a>
          ))}
          <a href="/def/">データとAPI</a>
        </nav>
        <ThemeToggle />
      </header>
      <main id="main" className="jgkg-shell-main" tabIndex={-1} ref={mainRef}>
        {children}
      </main>
    </div>
  );
}
