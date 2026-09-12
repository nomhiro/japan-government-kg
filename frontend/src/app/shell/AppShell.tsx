// 共通シェル(裁定B105・B106): 告知 → ヘッダ(ワードマーク・常設の検索欄・
// ナビ・テーマ切替)→ 本文 → フッタ。
//
// **旧シェルとの違い**: オムニボックスを検索ルートで隠していたのをやめた
// (仕様§2.1は「常設」。隠していたのは旧検索ビューが自前の検索欄を持っていた
// ための一時的な措置で、その画面はもう無い)。ナビに「データとAPI」を
// `#/data` として入れ、フッタを全画面に付けた。
import { useEffect, useRef, useState, type JSX, type ReactNode } from "react";
import { navigate, routeToHash, type Route } from "../../router";
import { Omnibox } from "./Omnibox";
import { ThemeToggle } from "./ThemeToggle";
// 土台のCSS(tokens → base)は main.tsx が読み込む。ここはシェル自身の分だけ。
import "./shell.css";

interface NavItem {
  readonly label: string;
  readonly route: Route;
  readonly isActive: (route: Route) => boolean;
}

const NAV: readonly NavItem[] = [
  { label: "全体を見る", route: { name: "top" }, isActive: (r) => r.name === "top" },
  {
    label: "つながりを辿る",
    route: { name: "search", q: "" },
    isActive: (r) => r.name === "search" || r.name === "entity",
  },
  { label: "経路", route: { name: "path" }, isActive: (r) => r.name === "path" },
  { label: "聞く", route: { name: "chat" }, isActive: (r) => r.name === "chat" },
  { label: "データとAPI", route: { name: "data" }, isActive: (r) => r.name === "data" },
];

const RELEASES_URL = "https://github.com/nomhiro/japan-government-kg/releases";
const REPO_URL = "https://github.com/nomhiro/japan-government-kg";

export function AppShell({ route, children }: { route: Route; children: ReactNode }): JSX.Element {
  const mainRef = useRef<HTMLElement>(null);
  const [navOpen, setNavOpen] = useState(false);

  // ルートが変わったら本文の先頭へ戻す。旧実装は前の画面のスクロール位置が
  // 残り、遷移したのに同じ場所を見ているように見えることがあった。
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
    setNavOpen(false);
  }, [route]);

  return (
    <div className="jg-shell">
      {/* スキップは <a href="#main"> にしない —— ハッシュルータが "#main" を
          未知のハッシュとして解釈して404画面へ飛んでしまう。 */}
      <button type="button" className="jg-skip" onClick={() => mainRef.current?.focus()}>
        本文へ移動
      </button>

      <header className="jg-header">
        <div className="jg-header__inner">
          <a
            className="jg-brand"
            href={routeToHash({ name: "top" })}
            onClick={(e) => {
              e.preventDefault();
              navigate({ name: "top" });
            }}
          >
            <span className="jg-brand__mark" aria-hidden="true">
              <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
                {/* 6軸を6つの点として置いた印。装飾ではなく、この製品が
                    「型付きのつながり」であることを示す。 */}
                <circle cx="13" cy="13" r="3.4" fill="var(--axis-work)" />
                <circle cx="13" cy="3.6" r="2.2" fill="var(--axis-agent)" />
                <circle cx="21.1" cy="8.3" r="2.2" fill="var(--axis-event)" />
                <circle cx="21.1" cy="17.7" r="2.2" fill="var(--axis-money)" />
                <circle cx="13" cy="22.4" r="2.2" fill="var(--axis-place)" />
                <circle cx="4.9" cy="17.7" r="2.2" fill="var(--axis-concept)" />
                <circle cx="4.9" cy="8.3" r="2.2" fill="var(--axis-agent)" opacity="0.55" />
                <g stroke="var(--rule-strong)" strokeWidth="1">
                  <path d="M13 13 13 3.6M13 13 21.1 8.3M13 13 21.1 17.7M13 13 13 22.4M13 13 4.9 17.7M13 13 4.9 8.3" />
                </g>
              </svg>
            </span>
            <span className="jg-brand__text">
              <span className="jg-brand__name">日本政府ナレッジグラフ</span>
              <span className="jg-brand__sub">非公式・第三者による構造化データ</span>
            </span>
          </a>

          <Omnibox />

          <button
            type="button"
            className="jg-navtoggle jg-btn jg-btn--quiet"
            aria-expanded={navOpen}
            aria-controls="jg-nav"
            onClick={() => setNavOpen((v) => !v)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
            メニュー
          </button>

          <nav
            id="jg-nav"
            className={`jg-nav${navOpen ? " jg-nav--open" : ""}`}
            aria-label="主要なページ"
          >
            {NAV.map((item) => {
              const href = routeToHash(item.route);
              const active = item.isActive(route);
              return (
                <a
                  key={item.label}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(item.route);
                  }}
                >
                  {item.label}
                </a>
              );
            })}
          </nav>

          <ThemeToggle />
        </div>
      </header>

      <main id="main" className="jg-main" tabIndex={-1} ref={mainRef}>
        {children}
      </main>

      <footer className="jg-footer">
        <div className="jg-footer__inner">
          <div className="jg-stack jg-stack--2">
            <span className="jg-eyebrow">このデータについて</span>
            <p className="jg-sm jg-ink2">
              日本国政府が公開するデータを第三者が構造化したナレッジグラフです。政府による公式なデータセットではありません。
              判断の根拠には一次資料をご確認ください。
            </p>
            <p className="jg-xs jg-muted">
              一次資料: e-Gov法令検索 ・ 法人番号公表サイト ・ 行政事業レビュー(RS)
            </p>
            <p className="jg-xs jg-muted">
              ライセンス: 公共データ利用規約(第1.0版)(PDL1.0)。編集・加工を行ったこと及びその主体の記載が必要です。
            </p>
          </div>
          <div className="jg-stack jg-stack--2">
            <span className="jg-eyebrow">データとAPI</span>
            <a className="jg-sm" href={routeToHash({ name: "data" })} onClick={(e) => { e.preventDefault(); navigate({ name: "data" }); }}>
              データとAPIの使い方
            </a>
            <a className="jg-sm" href="/def/">
              語彙(オントロジー)の一覧
            </a>
            <a className="jg-sm" href={RELEASES_URL} target="_blank" rel="noopener noreferrer">
              KG本体のダウンロード(GitHub Releases)
            </a>
            <a className="jg-sm" href={REPO_URL} target="_blank" rel="noopener noreferrer">
              ソースコード(GitHub)
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
