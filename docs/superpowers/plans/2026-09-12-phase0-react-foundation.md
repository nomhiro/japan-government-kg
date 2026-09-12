# Phase 0: React 土台とアプリシェル 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存4画面(検索/エンティティ/経路/チャット)を旧ビューのまま動かしながら、React 19 の土台・共通シェル(ヘッダ・ナビ・オムニボックス・テーマ切替)・デザイントークン・DOMテスト環境を入れ、React入りのビルドがバイト単位で再現することを実証する。

**Architecture:** Strangler 方式。`main.tsx` が `#app` に `<App/>` を描き、`App` はハッシュルート(`useRoute`)ごとに旧ビューを `LegacyView`(innerHTMLビューをマウント/破棄する橋)で表示する。シェルは React、画面本体は旧TS。以降の Phase で画面を1つずつ React に置き換え、最後に `LegacyView` を消す。

**Tech Stack:** React 19.3 / `@vitejs/plugin-react` 5.2(Vite 6 のまま) / TypeScript 5.9 / vitest 3.2 + jsdom 30 + Testing Library / 既存の sigma 3 + graphology(触らない)

**Spec:** `docs/superpowers/specs/2026-09-12-frontend-redesign-design.md`(§2.1 共通シェル、§2.3 横断パターン、§3 デザイン言語、§4 技術方針、§6 Phase 0)

## Global Constraints

- ハッシュルーティングを維持する(`frontend/src/router.ts:1-20`。`/def/*` の恒久LOD識別子を壊さない)
- `frontend/index.html` の告知 `<div class="jgkg-notice">` は静的に残す(`src/jgkg/site_verify.py:536-539` が「政府による公式なデータセットではありません」を本文検査)
- `base` は `/` のまま(`site_verify.py:293` が `/assets/` 絶対パス前提)
- `frontend/public/` を作らない(`src/jgkg/site.py:153-170` の `sync_app` が `index.html`・`assets/` 以外を捨てる)
- 単一 `tsconfig.json` + `noEmit`。`tsc -b` にしない(`*.tsbuildinfo` が追跡外ファイルとしてCIを落とす)
- ビルドID・時刻・乱数を出力に埋め込むプラグインを入れない(`scripts/check-frontend-build.py` が2回ビルドの sha256 一致を要求)
- `frontend/src/api/client.ts:34-37,56-75` の `VITE_API_BASE` 判定は不変。`frontend/.env*` を置かない
- `frontend/src/generated/labels.json`・`frontend/src/api/openapi-types.ts`・`frontend/openapi.json` のパスは動かさない
- 表示名は `labels.json` / API の `label` から引く。フロントで合成・手書きしない(裁定B78・B88)
- 依存は目的ごとに1つ。`package.json` の隣か `vite.config.ts` のコメントに目的と却下案を書く
- 禁止する見た目: グラデーション背景、絵文字、左ボーダー付きカード、ガラス風、Inter/Roboto(裁定B105)
- **Phase 0 では旧ビュー(`frontend/src/views/*.ts`)のロジックを変えない。** 変えるのは入口・シェル・トークンだけ
- 作業は worktree `C:\Users\nom40\Documents\Product\Japan-Goverment-KG\.claude\worktrees\requirements-draft`(ブランチ `worktree-requirements-draft`)。push は指示があるまでしない(`main` への push は本番配信を起動する)

---

## ファイル構成(Phase 0 で作る/変える)

```
frontend/
  package.json / package-lock.json     依存追加(Task 1)
  vite.config.ts                       plugins: [react()]、方針コメントの更新(Task 1)
  tsconfig.json                        "jsx": "react-jsx"(Task 1)
  index.html                           <script src="/src/main.tsx">(Task 3)。告知divは不変
  src/main.ts                          削除(Task 3)
  src/main.tsx                         createRoot(#app) → <StrictMode><App/></StrictMode>(Task 3)
  src/router.ts                        先頭コメントの更新のみ(Task 3)
  src/app/react-smoke.test.tsx         React+jsdom+Testing Library が動くことの煙テスト(Task 1)
  src/app/useRoute.ts (+ .test.tsx)    hashchange を useSyncExternalStore で購読(Task 2)
  src/app/LegacyView.tsx (+ .test.tsx) 旧ビューをマウント/破棄する橋(Task 3)
  src/app/App.tsx                      ルート → 旧ビューの対応。AppShell で包む(Task 3, 4)
  src/app/theme.ts (+ .test.ts)        テーマ設定の純関数(Task 4)
  src/app/shell/AppShell.tsx (+ .test.tsx)  header/nav/main の骨格(Task 4)
  src/app/shell/Omnibox.tsx            常設検索欄(Task 4)
  src/app/shell/ThemeToggle.tsx        ライト/ダーク切替(Task 4)
  src/app/shell/shell.css              シェルのスタイル(Task 4)
  src/styles/tokens.css                デザイントークン(旧 style.css の :root を移し、拡張)(Task 4)
  src/style.css                        :root ブロックを削除、#app の幅指定を .jgkg-shell-main へ(Task 4)
tests/test_decision_log_references.py  対象拡張子に .tsx .css を追加(Task 3)
docs/status.md                         I節 Phase 0 行を「完了」に、バンドル実測を記録(Task 5)
```

各ファイルの責務は1つ: `useRoute` はURL→Route の購読だけ、`LegacyView` はマウント/破棄だけ、`theme.ts` はDOMに触らない判断だけ、`AppShell` は骨格だけ。

---

### Task 1: React とテスト環境の導入、ビルド再現性の実証

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`(npm が更新)
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.json:2-21`
- Create: `frontend/src/app/react-smoke.test.tsx`

**Interfaces:**
- Consumes: なし
- Produces: `react`・`react-dom`・`@testing-library/react`・`@testing-library/user-event`・`jsdom` が import 可能。`.tsx` が `tsc --noEmit` と vitest で通る

- [ ] **Step 1: 煙テストを書く(まだ依存が無いので落ちる)**

`frontend/src/app/react-smoke.test.tsx`:

```tsx
// @vitest-environment jsdom
// React + jsdom + Testing Library が実際に描画・検索できることの煙テスト。
// 「依存を入れた」ではなく「描いて読めた」を Phase 0 の最初の緑にする
// (裁定B93: 描画された≠動く。ここでは最低限「描画された」を機械で確かめる)。
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("React の土台", () => {
  it("コンポーネントを jsdom に描き、テキストで見つけられる", () => {
    render(<p>土台の煙テスト</p>);
    expect(screen.getByText("土台の煙テスト")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 落ちることを確認する**

Run(`frontend/` で): `npm test -- src/app/react-smoke.test.tsx`
Expected: FAIL。`Cannot find package '@testing-library/react'` または `Cannot find module 'react/jsx-runtime'`

- [ ] **Step 3: 依存を入れる(目的ごとに1つ)**

Run(`frontend/` で):

```bash
npm install react@^19.3.0 react-dom@^19.3.0
npm install -D @vitejs/plugin-react@^5.2.0 @types/react@^19.3.0 @types/react-dom@^19.3.0 \
  jsdom@^30.0.0 @testing-library/react@^16.3.0 @testing-library/dom@^10.0.0 @testing-library/user-event@^14.6.0
```

**なぜこの版か(実測 2026-09-12 `npm view`)**: `@vitejs/plugin-react@6.x` は Vite 8 を要求し現行 Vite 6.4.3 と共存しない。5.2.0 の peer は `vite ^4.2||^5||^6||^7||^8`。`jsdom@30` の peer `canvas` は `optional: true`(ネイティブビルドは走らない)。`@testing-library/react@16` は `@testing-library/dom@^10` を peer に要求するので明示して入れる。

- [ ] **Step 4: `vite.config.ts` に React プラグインを足し、方針コメントを更新する**

`frontend/vite.config.ts` 全体を次に置き換える:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// フロント再設計プログラム(裁定B104)。React を採る——「UIフレームワークを
// 入れない」方針は裁定B104で改めた(原則1「本体はKG、アプリは検証装置」は
// 維持。変えたのはアプリに使う投資の量であって、アプリが従う規律ではない)。
//
// **依存は目的ごとに1つ。** UIフレームワーク = react/react-dom。
// Vite プラグイン = @vitejs/plugin-react@5(6.x は Vite 8 を要求し Vite 6 と
// 共存しないことを npm view で実測。Vite のメジャー更新は別タスクにして、
// 再現性検査が赤くなったときの原因を分離する)。
//
// **ビルド時刻や乱数を出力に埋め込まない。** React の production ビルドは
// ビルド時刻を埋め込まない。この前提は scripts/check-frontend-build.py
// (裁定B81。2回ビルドして sha256 全一致)が毎回確かめる——「決定的なはず」
// ではなく実測で持つ。`define` に `Date.now()` を置く・sourcemap を出す・
// ビルドIDを埋めるプラグインを足す、はどれも禁止。
//
// **出力先を`../site`に直接指定しない。** Viteはproject root外のoutDirを
// 空にする(`emptyOutDir`)際、対象ディレクトリ全体を削除しうる——`site/`は
// `/def/`(オントロジーの一覧ページ含む)・`sitemap.txt`・`_headers`等、
// このアプリと無関係な内容を同居させているため、Vite自身に`site/`を
// 触らせるのは危険が大きい。既定の`dist/`にビルドし、`site.sync_app()`
// (`scripts/build-site.sh`が呼ぶ)が`index.html`と`assets/`だけを
// 差分無く同期する——影響範囲を明示的に絞る。`frontend/public/` も作らない
// (sync_app は index.html と assets/ 以外を捨てるので、置いた物は本番で404になる)。
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
});
```

- [ ] **Step 5: `tsconfig.json` に JSX 設定を足す**

`frontend/tsconfig.json` の `"noUncheckedIndexedAccess": true` の行の後に1行追加:

```json
    "noUncheckedIndexedAccess": true,
    "jsx": "react-jsx"
```

(結果として `compilerOptions` の末尾が `"jsx": "react-jsx"` になる。他は変えない。単一 tsconfig・`noEmit` を維持する。)

- [ ] **Step 6: 煙テストが通ることを確認する**

Run(`frontend/` で): `npm test`
Expected: PASS。既存8ファイル+新規1ファイルがすべて緑(既存148ケース+1)

- [ ] **Step 7: ビルドと再現性検査を通す(React 入りで初めて)**

Run(リポジトリルートで):

```bash
cd frontend && npm run build && cd ..
uv run python scripts/check-frontend-build.py
ls -l frontend/dist/assets/
```

Expected: `npm run build` が成功(`tsc --noEmit` を含む)。`check-frontend-build.py` が `OK 2回のビルドが完全に一致した(N ファイル)`。`ls -l` の JS/CSS のバイト数を控える(Task 5 で記録する。現行は JS 195,517 B / CSS 5,023 B)。

**もし一致しなかったら**: 原因を推測して直さない。`内容が違う:` に出たファイルを2回分保存して `diff` し、何が違うかを見てから対処する(裁定B101: 比較の両側を自分で作って突き合わせる)。

- [ ] **Step 8: コミット**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/src/app/react-smoke.test.tsx
git commit -m "frontend: React 19 と jsdom/Testing Library を導入し、React入りビルドの再現性を実証(裁定B104)"
```

---

### Task 2: `useRoute` — ハッシュを購読して `Route` を返すフック

**Files:**
- Create: `frontend/src/app/useRoute.ts`
- Create: `frontend/src/app/useRoute.test.tsx`

**Interfaces:**
- Consumes: `parseHash(hash: string): Route`、`type Route`(`frontend/src/router.ts:22-68`。不変)
- Produces: `export function useRoute(): Route` — 現在の `location.hash` を `parseHash` した値。`hashchange` で更新される

- [ ] **Step 1: 失敗するテストを書く**

`frontend/src/app/useRoute.test.tsx`:

```tsx
// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useRoute } from "./useRoute";

// jsdom は location.hash の代入で hashchange を発火するが、発火のタイミングに
// 依存しないよう、テストでは明示的にも dispatch する(同じ値のスナップショットが
// 2回届いても useSyncExternalStore は再描画しないので無害)。
function setHash(hash: string): void {
  act(() => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

afterEach(() => {
  window.location.hash = "";
});

describe("useRoute", () => {
  it("初期値は現在の location.hash を parseHash した Route", () => {
    window.location.hash = "#/chat";
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "chat" });
  });

  it("hashchange で Route が更新される", () => {
    window.location.hash = "#/";
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "search", q: "" });
    setHash("#/entity/org/6000012070001");
    expect(result.current).toEqual({ name: "entity", idPath: "org/6000012070001" });
  });

  it("パーセントエンコード済み id_path を再デコードしない(裁定B69/B73 の族)", () => {
    // router.test.ts と同じ実例(廃止府省「厚生省」)。フックを通しても往復が崩れないこと。
    const idPath = "org/abolished/%E5%8E%9A%E7%94%9F%E7%9C%81";
    window.location.hash = `#/entity/${idPath}`;
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "entity", idPath });
  });

  it("アンマウント後は hashchange の購読が外れる", () => {
    window.location.hash = "#/";
    const { result, unmount } = renderHook(() => useRoute());
    unmount();
    // 購読が残っていれば React が警告を出す/例外になる。ここでは例外が出ないことだけ固定する。
    expect(() => setHash("#/chat")).not.toThrow();
    expect(result.current).toEqual({ name: "search", q: "" });
  });
});
```

- [ ] **Step 2: 落ちることを確認する**

Run(`frontend/` で): `npm test -- src/app/useRoute.test.tsx`
Expected: FAIL。`Failed to resolve import "./useRoute"`

- [ ] **Step 3: 実装する**

`frontend/src/app/useRoute.ts`:

```ts
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
```

- [ ] **Step 4: 通ることを確認する**

Run(`frontend/` で): `npm test -- src/app/useRoute.test.tsx`
Expected: PASS(4件)

- [ ] **Step 5: コミット**

```bash
git add frontend/src/app/useRoute.ts frontend/src/app/useRoute.test.tsx
git commit -m "frontend: useRoute — hashchange を useSyncExternalStore で購読して Route を返す"
```

---

### Task 3: `LegacyView` 橋と `App`/`main.tsx` の配線 — 4画面が旧ビューのまま動く

**Files:**
- Create: `frontend/src/app/LegacyView.tsx`, `frontend/src/app/LegacyView.test.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/main.tsx`
- Delete: `frontend/src/main.ts`
- Modify: `frontend/index.html:24`
- Modify: `frontend/src/router.ts:1-2`(コメントのみ)
- Modify: `tests/test_decision_log_references.py`(`_TEXT_SUFFIXES`)

**Interfaces:**
- Consumes: `useRoute()`(Task 2)、`routeToHash(route)`(`router.ts:70`)、旧ビュー `renderSearch(container, initialQuery)` / `renderEntity(container, idPath): EntityViewController` / `renderPath(container, from?, to?)` / `renderChat(container)`(`frontend/src/views/*.ts`。不変)
- Produces: `export interface LegacyController { destroy(): void }`、`export type LegacyMount = (el: HTMLElement) => LegacyController | void`、`export function LegacyView(props: { mount: LegacyMount }): JSX.Element`、`export function App(): JSX.Element`

- [ ] **Step 1: 失敗するテストを書く**

`frontend/src/app/LegacyView.test.tsx`:

```tsx
// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LegacyView, type LegacyMount } from "./LegacyView";

describe("LegacyView(旧 innerHTML ビューを React ツリーに載せる橋)", () => {
  it("マウント時に mount(el) を1回呼び、el は DOM 上の要素である", () => {
    const mount = vi.fn<LegacyMount>((el) => {
      el.innerHTML = "<p>旧ビュー</p>";
    });
    const { container } = render(<LegacyView mount={mount} />);
    expect(mount).toHaveBeenCalledTimes(1);
    expect(container.querySelector("p")?.textContent).toBe("旧ビュー");
    expect(document.body.contains(mount.mock.calls[0]![0])).toBe(true);
  });

  it("アンマウント時に controller.destroy() を呼び、描いた内容を消す", () => {
    const destroy = vi.fn();
    const mount: LegacyMount = (el) => {
      el.innerHTML = "<canvas></canvas>";
      return { destroy };
    };
    const { unmount, container } = render(<LegacyView mount={mount} />);
    expect(container.querySelector("canvas")).not.toBeNull();
    unmount();
    expect(destroy).toHaveBeenCalledTimes(1);
  });

  it("controller を返さない旧ビュー(destroy を持たない)でもアンマウントで例外にならない", () => {
    const mount: LegacyMount = (el) => {
      el.textContent = "戻り値なし";
    };
    const { unmount } = render(<LegacyView mount={mount} />);
    expect(() => unmount()).not.toThrow();
  });

  it("key が変わると破棄→再マウントされる(ルート遷移ごとに描き直す現行挙動と同じ)", () => {
    const destroy = vi.fn();
    const mount = vi.fn<LegacyMount>(() => ({ destroy }));
    const { rerender } = render(<LegacyView key="#/" mount={mount} />);
    rerender(<LegacyView key="#/chat" mount={mount} />);
    expect(destroy).toHaveBeenCalledTimes(1);
    expect(mount).toHaveBeenCalledTimes(2);
  });

  it("key が同じなら再描画(props の関数が変わっても)で mount を呼び直さない", () => {
    const mount1 = vi.fn<LegacyMount>(() => undefined);
    const mount2 = vi.fn<LegacyMount>(() => undefined);
    const { rerender } = render(<LegacyView key="#/" mount={mount1} />);
    rerender(<LegacyView key="#/" mount={mount2} />);
    expect(mount1).toHaveBeenCalledTimes(1);
    expect(mount2).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: 落ちることを確認する**

Run(`frontend/` で): `npm test -- src/app/LegacyView.test.tsx`
Expected: FAIL。`Failed to resolve import "./LegacyView"`

- [ ] **Step 3: `LegacyView` を実装する**

`frontend/src/app/LegacyView.tsx`:

```tsx
import { useEffect, useRef, type JSX } from "react";

// 旧ビュー(frontend/src/views/*.ts。innerHTML を書く関数)を React ツリーに
// 載せるための橋。**Phase 0〜3 の移行期間だけ存在し、旧ビューが全部 React に
// 置き換わったら削除する**(仕様 §4 移行方式 Strangler)。
//
// 契約:
// - mount は**マウント時に1回だけ**呼ぶ。props.mount の参照が変わっても呼び直さない
//   (シェルのテーマ切替などで親が再描画されるたびに旧ビューが fetch し直すのを防ぐ)。
//   ルートが変わったら描き直したい親は `key` を変える(App.tsx は routeToHash(route) を key にする)。
// - アンマウント時に controller.destroy() を呼ぶ(entity 画面の Sigma/WebGL を確実に破棄する。
//   旧 main.ts:14-20 と同じ責務)。controller を返さない旧ビューも許す。
// - 開発時の <StrictMode> は effect を mount→cleanup→mount と二重実行する。旧ビューは
//   その結果 2回描かれ、entity 画面は fetch も2回走る。**本番ビルドでは起きない**。
//   StrictMode を外して隠すより、新しい React 部品の cleanup 漏れを開発中に見える方を採る。

export interface LegacyController {
  destroy(): void;
}

export type LegacyMount = (el: HTMLElement) => LegacyController | void;

export function LegacyView({ mount }: { mount: LegacyMount }): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const mountRef = useRef(mount);
  mountRef.current = mount;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const controller = mountRef.current(el);
    return () => {
      controller?.destroy();
      el.replaceChildren();
    };
    // 依存配列を空にするのは意図(上の契約)。再マウントは親の key で行う。
  }, []);

  return <div ref={ref} className="jgkg-legacy" />;
}
```

- [ ] **Step 4: 通ることを確認する**

Run(`frontend/` で): `npm test -- src/app/LegacyView.test.tsx`
Expected: PASS(5件)

- [ ] **Step 5: `App.tsx` と `main.tsx` を書き、`index.html` を切り替え、`main.ts` を消す**

`frontend/src/app/App.tsx`:

```tsx
import type { JSX } from "react";
import { routeToHash, type Route } from "../router";
import { renderChat } from "../views/chat";
import { renderEntity } from "../views/entity";
import { renderPath } from "../views/path";
import { renderSearch } from "../views/search";
import { LegacyView, type LegacyController } from "./LegacyView";
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
  // ハッシュ文字列を key にする = ハッシュが変わるたびに旧ビューを破棄して描き直す
  // (旧 main.ts の onRouteChange と同じ挙動)。検索ビューは入力中にハッシュを書き換えない
  // (views/search.ts はクリック時の navigate だけ)ので、入力途中で再マウントされることはない。
  return <LegacyView key={routeToHash(route)} mount={(el) => mountLegacy(el, route)} />;
}
```

`frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { App } from "./app/App";

const app = document.querySelector<HTMLElement>("#app");
if (!app) {
  throw new Error("#app が見つからない(frontend/index.htmlの構造が変わった可能性)");
}

createRoot(app).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`frontend/index.html` の24行目を差し替える:

```html
  <script type="module" src="/src/main.tsx"></script>
```

旧入口を削除:

```bash
git rm frontend/src/main.ts
```

`frontend/src/router.ts` の先頭2行(`// 最小限のハッシュルータ。フレームワークを入れない方針(controllerの設計1)` / `// なので、この規模(画面3つ)には十分。`)を次に置き換える(他の行は不変):

```ts
// 最小限のハッシュルータ。React 採用後(裁定B104)も React Router を入れず
// これを使う——`id_path` を再エンコード/再デコードしない往復(router.test.ts)を
// 自前で守るほうが確実で、画面数に対して依存が過剰だから。React 側の入口は
// app/useRoute.ts(hashchange の購読だけ)。
```

- [ ] **Step 6: 裁定参照テストの対象に `.tsx` と `.css` を足す**

`tests/test_decision_log_references.py` の `_TEXT_SUFFIXES` を次に変える:

```python
_TEXT_SUFFIXES = {".md", ".py", ".sh", ".yaml", ".yml", ".ts", ".tsx", ".css", ".rq", ".json", ".html"}
```

その直前のコメントに1行足す: `# .tsx/.css はフロント再設計(裁定B104)で増えた。参照を書けるファイルは全部見る。`

- [ ] **Step 7: 型検査・全テスト・再現性検査を通す**

Run(リポジトリルートで):

```bash
cd frontend && npm test && npm run build && cd ..
uv run python scripts/check-frontend-build.py
uv run pytest tests/test_decision_log_references.py -q
```

Expected: vitest 全緑(9ファイル+新規2)。`tsc --noEmit` が `main.ts` の削除後も通る(`noUnusedLocals` で未使用 import が無いこと)。再現性 OK。pytest 緑。

- [ ] **Step 8: 開発サーバで4画面が動くことを実ブラウザで確かめる**

Run(`frontend/` で。本番APIを使う。CORS は `*` で許可済み・裁定B82):

```bash
VITE_API_BASE=https://jgkg.gentlemeadow-d9ba6656.japaneast.azurecontainerapps.io npm run dev
```

ブラウザで `http://localhost:5173/` を開き、**押せるものを押す**(裁定B93):
1. `#/` — 検索欄に「年金」と入れ、結果が出る。第1層(府省の帯)が下に出る。結果を1件クリック → `#/entity/...` に遷移
2. `#/entity/...` — 属性表・グラフが出る。ノードを1つクリック → 詳細パネル。「ここから経路を探す」→ `#/path?from=...`
3. `#/path` — 終点を検索して選び「探す」→ 結果文言が出る
4. `#/chat` — 短い質問を1つ送る(LLM予算を消費するので1回だけ)→ 応答と道具履歴
5. ブラウザの戻る/進むで画面が切り替わる(旧ビューが破棄・再描画される)。DevTools コンソールに React の警告が無い(StrictMode の二重描画は開発時の仕様。エラーではない)

Expected: 4画面すべて Phase 0 前と同じに動く。

- [ ] **Step 9: コミット**

```bash
git add frontend/index.html frontend/src/main.tsx frontend/src/app/App.tsx frontend/src/app/LegacyView.tsx frontend/src/app/LegacyView.test.tsx frontend/src/router.ts tests/test_decision_log_references.py
git commit -m "frontend: React の入口(main.tsx/App)と LegacyView の橋。4画面は旧ビューのまま動く(Strangler)"
```

(`git rm` 済みの `main.ts` はステージ済み。)

---

### Task 4: デザイントークンとアプリシェル(ヘッダ・ナビ・オムニボックス・テーマ切替・本文へ移動)

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/app/theme.ts`, `frontend/src/app/theme.test.ts`
- Create: `frontend/src/app/shell/AppShell.tsx`, `frontend/src/app/shell/AppShell.test.tsx`
- Create: `frontend/src/app/shell/Omnibox.tsx`, `frontend/src/app/shell/ThemeToggle.tsx`, `frontend/src/app/shell/shell.css`
- Modify: `frontend/src/style.css:1-33`(先頭コメント・`:root` ブロック2つ・`#app` 行)
- Modify: `frontend/src/app/App.tsx`(AppShell で包む)
- Modify: `frontend/src/main.tsx`(tokens.css を最初に import)

**Interfaces:**
- Consumes: `useRoute()`(Task 2)、`navigate(route)`(`router.ts:83`)、`type Route`
- Produces:
  - `theme.ts`: `export type ThemePreference = "light" | "dark" | "system"`、`export type ResolvedTheme = "light" | "dark"`、`export const THEME_STORAGE_KEY = "jgkg-theme"`、`export function readStoredPreference(storage: Pick<Storage, "getItem">): ThemePreference`、`export function resolveTheme(pref: ThemePreference, systemDark: boolean): ResolvedTheme`、`export function nextPreference(resolved: ResolvedTheme): ThemePreference`、`export function applyPreference(root: Pick<HTMLElement, "setAttribute" | "removeAttribute">, pref: ThemePreference): void`
  - `AppShell.tsx`: `export function AppShell(props: { route: Route; children: ReactNode }): JSX.Element`
  - CSS 変数(旧名を維持): `--paper --ink --muted --rule --signal --signal-bg --accent --surface-2`。追加: `--surface --primary --focus --font-sans --radius --space-1 … --space-6`

- [ ] **Step 1: テーマ純関数の失敗するテストを書く**

`frontend/src/app/theme.test.ts`(Node 環境。DOM に触らない):

```ts
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
```

- [ ] **Step 2: 落ちることを確認する**

Run(`frontend/` で): `npm test -- src/app/theme.test.ts`
Expected: FAIL。`Failed to resolve import "./theme"`

- [ ] **Step 3: `theme.ts` を実装する**

`frontend/src/app/theme.ts`:

```ts
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
```

- [ ] **Step 4: 通ることを確認する**

Run(`frontend/` で): `npm test -- src/app/theme.test.ts`
Expected: PASS(9件)

- [ ] **Step 5: シェルの失敗するテストを書く**

`frontend/src/app/shell/AppShell.test.tsx`:

```tsx
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";

afterEach(() => {
  window.location.hash = "";
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

describe("AppShell(共通シェル)", () => {
  it("ランドマーク header / nav / main を持ち、本文を main に描く", () => {
    render(
      <AppShell route={{ name: "chat" }}>
        <p>本文</p>
      </AppShell>,
    );
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "主要なページ" })).toBeTruthy();
    expect(screen.getByRole("main").textContent).toContain("本文");
  });

  it("いまのルートに対応するナビ項目だけ aria-current=page", () => {
    render(
      <AppShell route={{ name: "path" }}>
        <p />
      </AppShell>,
    );
    expect(screen.getByRole("link", { name: "経路" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "全体を見る" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("link", { name: "聞く" }).getAttribute("aria-current")).toBeNull();
  });

  it("検索ルートではオムニボックスを出さない(旧検索ビューが自分の検索欄を持つため二重にしない)", () => {
    render(
      <AppShell route={{ name: "search", q: "" }}>
        <p />
      </AppShell>,
    );
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("オムニボックスで Enter すると #/?q=… に遷移する(値は encodeURIComponent 1回)", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    const box = screen.getByRole("searchbox", { name: "府省・事業・法人・法令を探す" });
    await user.type(box, "年金{Enter}");
    expect(window.location.hash).toBe("#/?q=%E5%B9%B4%E9%87%91");
  });

  it("空欄で Enter しても遷移しない", async () => {
    const user = userEvent.setup();
    window.location.hash = "#/chat";
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    await user.type(screen.getByRole("searchbox"), "   {Enter}");
    expect(window.location.hash).toBe("#/chat");
  });

  it("「本文へ移動」を押すと main にフォーカスが移る(href=\"#main\" を使わない——ハッシュルータが検索へ遷移してしまう)", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p>本文</p>
      </AppShell>,
    );
    await user.click(screen.getByRole("button", { name: "本文へ移動" }));
    expect(document.activeElement).toBe(screen.getByRole("main"));
    expect(window.location.hash).toBe("");
  });

  it("テーマ切替を押すと <html data-theme> が明示値になり、localStorage に保存される", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
    await user.click(screen.getByRole("button", { name: /表示を.*に切り替える/ }));
    const applied = document.documentElement.getAttribute("data-theme");
    expect(applied === "dark" || applied === "light").toBe(true);
    expect(window.localStorage.getItem("jgkg-theme")).toBe(applied);
  });
});
```

- [ ] **Step 6: 落ちることを確認する**

Run(`frontend/` で): `npm test -- src/app/shell/AppShell.test.tsx`
Expected: FAIL。`Failed to resolve import "./AppShell"`

- [ ] **Step 7: トークンを書く(旧 `:root` を移して拡張)**

`frontend/src/styles/tokens.css`:

```css
/* デザイントークン(仕様 §3。裁定B105: デジタル庁デザインシステムの寸法と原則を
   参考にする。公式ブランド色・ロゴは使わない)。
   変数名のうち --paper --ink --muted --rule --signal --signal-bg --accent --surface-2 は
   旧 style.css から引き継ぐ——旧ビュー(views/*.ts)と graph-theme.ts(Sigma のラベル色を
   --ink/--muted から読む。裁定B95)がこの名前に依存しているため、名前は変えず値だけ更新する。

   テーマの契約(app/theme.ts と対):
   - :root = ライト
   - OS がダークで、かつ明示ライトでない → ダーク
   - data-theme="dark" → ダーク(トグルの明示)
   色の唯一の定義場所はこのファイル。@media や [data-theme] の中だけで定義される色を作らない。 */
:root {
  --font-sans: "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", "Yu Gothic", system-ui, sans-serif;

  --paper: #ffffff;
  --surface: #f5f6f8;
  --surface-2: #eceef2;
  --ink: #1a1a1a;
  --muted: #5b6472;
  --rule: #d0d5dd;
  --primary: #1a4fb8;
  --accent: #1a4fb8;
  --signal: #b42318;
  --signal-bg: #fdecea;
  --focus: #ffd23f;

  --radius: 8px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #14161a;
    --surface: #1c1f25;
    --surface-2: #22262c;
    --ink: #e7e4de;
    --muted: #a1a8b2;
    --rule: #2f343b;
    --primary: #7ba7f7;
    --accent: #7ba7f7;
    --signal: #f19a8a;
    --signal-bg: #2c1d19;
    --focus: #ffd23f;
  }
}
:root[data-theme="dark"] {
  --paper: #14161a;
  --surface: #1c1f25;
  --surface-2: #22262c;
  --ink: #e7e4de;
  --muted: #a1a8b2;
  --rule: #2f343b;
  --primary: #7ba7f7;
  --accent: #7ba7f7;
  --signal: #f19a8a;
  --signal-bg: #2c1d19;
  --focus: #ffd23f;
}
```

**書体について**: Phase 0 では Web フォントを読み込まない(Google Fonts は第三者への接続を増やし、自前配信の `@fontsource/noto-sans-jp` は数MB)。Windows は Yu Gothic UI、macOS は Hiragino Sans、Noto Sans JP が入っている環境ではそれが使われる。フォールバックの見た目で足りないと判断したら Phase 5 で `@fontsource/noto-sans-jp`(assets/ にハッシュ付きで出る。sync_app の対象内)を検討する。

`frontend/src/style.css` を次のように変える:
- 1〜2行目のコメントを `/* 旧ビュー(views/*.ts)が使うスタイル。色は styles/tokens.css の変数だけを使う(裁定B105)。Phase 3 で旧ビューが消えるまで残す。 */` に置き換える
- 3〜25行目(`:root { … }` と `@media (prefers-color-scheme: dark) { :root { … } }` の2ブロック)を**削除**する(tokens.css へ移した)
- `body { font-family: "Hiragino Sans", "Yu Gothic", system-ui, sans-serif; line-height: 1.7; }` を `body { font-family: var(--font-sans); line-height: 1.7; }` に
- `#app { max-width: 60rem; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }` を**削除**する(本文の幅は shell.css の `.jgkg-shell-main` が持つ。ヘッダは全幅)
- それ以外の行は変えない

- [ ] **Step 8: シェルの部品を実装する**

`frontend/src/app/shell/Omnibox.tsx`:

```tsx
import { useState, type FormEvent, type JSX } from "react";
import { navigate } from "../../router";

// 常設の検索欄(仕様 §2.1)。Phase 0 では「Enter で #/?q= に遷移する」だけ。
// 候補のドロップダウンは Phase 1(#/search)で足す。
export function Omnibox(): JSX.Element {
  const [q, setQ] = useState("");
  function onSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const trimmed = q.trim();
    if (!trimmed) return;
    navigate({ name: "search", q: trimmed });
  }
  return (
    <form className="jgkg-omnibox" role="search" onSubmit={onSubmit}>
      <input
        type="search"
        className="jgkg-omnibox-input"
        aria-label="府省・事業・法人・法令を探す"
        placeholder="府省・事業・法人・法令を探す"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
    </form>
  );
}
```

`frontend/src/app/shell/ThemeToggle.tsx`:

```tsx
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
```

`frontend/src/app/shell/AppShell.tsx`:

```tsx
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
```

`frontend/src/app/shell/shell.css`:

```css
/* 共通シェル。色・寸法はすべて styles/tokens.css の変数から(裁定B105)。
   タップ領域は 44px 以上、フォーカスリングは太く高コントラスト(--focus)。 */
.jgkg-shell { min-height: 100vh; display: flex; flex-direction: column; }

.jgkg-skip {
  position: absolute; left: var(--space-2); top: var(--space-2);
  transform: translateY(-200%);
  padding: var(--space-2) var(--space-4); min-height: 44px;
  background: var(--ink); color: var(--paper); border: 0; border-radius: var(--radius);
  font: inherit;
}
.jgkg-skip:focus-visible { transform: none; outline: 3px solid var(--focus); outline-offset: 2px; z-index: 10; }

.jgkg-shell-header {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-3) var(--space-5);
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--rule);
  background: var(--paper);
}
.jgkg-brand { display: flex; flex-direction: column; line-height: 1.25; text-decoration: none; color: var(--ink); min-height: 44px; justify-content: center; }
.jgkg-brand-name { font-weight: 700; font-size: 1rem; }
.jgkg-brand-sub { font-size: 0.75rem; color: var(--muted); }

.jgkg-omnibox { flex: 1 1 18rem; max-width: 36rem; }
.jgkg-omnibox-input {
  width: 100%; min-height: 44px; padding: 0 var(--space-3);
  border: 1px solid var(--rule); border-radius: var(--radius);
  background: var(--surface); color: var(--ink); font: inherit; font-size: 1rem;
}

.jgkg-shell-nav { display: flex; flex-wrap: wrap; gap: var(--space-1); margin-left: auto; }
.jgkg-shell-nav a {
  display: inline-flex; align-items: center; min-height: 44px; padding: 0 var(--space-3);
  color: var(--ink); text-decoration: none; border-bottom: 2px solid transparent; font-size: 0.95rem;
}
.jgkg-shell-nav a[aria-current="page"] { border-bottom-color: var(--ink); font-weight: 600; }
.jgkg-shell-nav a:hover { color: var(--primary); }

.jgkg-theme-toggle {
  display: inline-flex; align-items: center; gap: var(--space-2);
  min-height: 44px; padding: 0 var(--space-3);
  border: 1px solid var(--rule); border-radius: var(--radius);
  background: var(--paper); color: var(--ink); font: inherit; font-size: 0.9rem; cursor: pointer;
}

.jgkg-shell-main { max-width: 60rem; width: 100%; margin: 0 auto; padding: 1.5rem 1.25rem 4rem; }
.jgkg-shell-main:focus { outline: none; }

/* フォーカスリングはシェル配下の全操作要素に共通(旧ビューの要素も含む)。 */
.jgkg-shell :is(a, button, input, select, textarea, [tabindex]):focus-visible {
  outline: 3px solid var(--focus); outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .jgkg-shell * { transition: none !important; animation: none !important; }
}
```

- [ ] **Step 9: `App.tsx` をシェルで包み、`main.tsx` の import 順を直す**

`frontend/src/app/App.tsx` の `App` を次に置き換える(`mountLegacy` と import は Task 3 のまま。`AppShell` の import を足す):

```tsx
import { AppShell } from "./shell/AppShell";
// …(既存の import はそのまま)

export function App(): JSX.Element {
  const route = useRoute();
  return (
    <AppShell route={route}>
      <LegacyView key={routeToHash(route)} mount={(el) => mountLegacy(el, route)} />
    </AppShell>
  );
}
```

`frontend/src/main.tsx` の import を次の順にする(トークンを最初に読む):

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./style.css";
import { App } from "./app/App";
```

- [ ] **Step 10: 通ることを確認する**

Run(`frontend/` で): `npm test -- src/app/shell/AppShell.test.tsx`
Expected: PASS(7件)

Run(`frontend/` で): `npm test`
Expected: 全緑(Task 3 までの件数 + theme 9 + shell 7)

- [ ] **Step 11: ビルド・再現性・実ブラウザ**

Run(リポジトリルートで):

```bash
cd frontend && npm run build && cd ..
uv run python scripts/check-frontend-build.py
```

Expected: OK。

Run(`frontend/` で): `VITE_API_BASE=https://jgkg.gentlemeadow-d9ba6656.japaneast.azurecontainerapps.io npm run dev` → ブラウザで確認:
1. ヘッダが全幅、本文は 60rem の列。告知はヘッダの上に静的に残っている
2. `#/chat` を開く → オムニボックスが出る。「年金」+Enter → `#/?q=年金` の検索画面に遷移し、結果が出る。`#/` ではオムニボックスが無い(旧検索欄のみ)
3. Tab を1回押す → 「本文へ移動」が現れる。Enter → フォーカスが本文へ。ハッシュは変わらない
4. テーマ切替を押す → 全体の色が反転し、再読み込みしても保たれる。DevTools で `<html data-theme="…">` を確認。entity 画面のグラフ内ラベル色だけが追随しないことを確認(既知の制限。Phase 3)
5. 幅を 400px にする → ヘッダが折り返し、ページ全体の横スクロールが無い(`document.documentElement.scrollWidth <= 400`)
6. `#/entity/org/6000012070001`(厚生労働省)を開き、グラフのノードを押す・辺を押す・展開を押す(裁定B93 の3件)→ Phase 0 前と同じに動く

- [ ] **Step 12: コミット**

```bash
git add frontend/src/styles/tokens.css frontend/src/style.css frontend/src/app/theme.ts frontend/src/app/theme.test.ts frontend/src/app/shell/ frontend/src/app/App.tsx frontend/src/main.tsx
git commit -m "frontend: デザイントークンと共通シェル(ヘッダ・ナビ・オムニボックス・テーマ切替・本文へ移動)(裁定B105)"
```

---

### Task 5: 配信物での確認と記録

**Files:**
- Modify: `docs/status.md`(I節の Phase 0 行)

**Interfaces:**
- Consumes: Task 1〜4 の成果
- Produces: Phase 0 の完了記録(バンドル実測値、既知の制限)

- [ ] **Step 1: 本番と同じ手順でサイトを組み、検査を通す**

Run(リポジトリルートで。`VITE_API_BASE` は本番と同じ値を渡す——渡す/渡さないで sha256 が変わる。裁定B101):

```bash
VITE_API_BASE=https://jgkg.gentlemeadow-d9ba6656.japaneast.azurecontainerapps.io bash scripts/build-site.sh
uv run python scripts/check-site-build.py
uv run pytest -q
git status --porcelain
```

Expected: `site/index.html` と `site/assets/` が更新される。`check-site-build.py` OK。pytest 全緑。`git status` に追跡外ファイルが無い(`site/index.html`・`site/assets/`・`frontend/dist/` は .gitignore 済み)。

- [ ] **Step 2: 配信物を実ブラウザで確認する(dev サーバではなく site/ を配信して)**

Run(`site/` を静的配信。例):

```bash
cd site && python -m http.server 8788
```

ブラウザで `http://localhost:8788/#/` を開き、DevTools で `document.querySelectorAll('script[src]')` の `src` が **いま `site/assets/` にあるファイル名と一致**することを確認する(裁定B93/B95: 古いバンドルを見ていないか)。Task 4 Step 11 の 1〜6 をこの配信物でもう一度通す。告知の文言「政府による公式なデータセットではありません」が、JS を無効にしても表示されることを確認する(DevTools → Settings → Disable JavaScript → 再読み込み)。

- [ ] **Step 3: バンドルの増分を記録し、status.md を更新する**

Run: `ls -l site/assets/`

`docs/status.md` の I節の表の Phase 0 行を、実測値を入れて次の形に書き換える(数値は `ls -l` の出力から。**ここに書いた例の数値を転記しない**):

```
| 0 | 土台: React + Testing Library、`App.tsx`/`useRoute`/`LegacyView`、トークンとシェル。既存4画面は旧ビューのまま動く。sha256 2回一致を React 入りで実証 | **完了**(YYYY-MM-DD)。JS <実測> B(gzip <実測> B)/ CSS <実測> B。旧 JS 195,517 B / CSS 5,023 B。**既知の制限**: テーマ切替で旧 entity 画面の Sigma ラベル色は追随しない(`views/graph.ts` が prefers-color-scheme のみ購読。Phase 3 で解消)。開発時 StrictMode で旧ビューが2回描かれる(本番では起きない) |
```

gzip サイズは `gzip -c site/assets/index-*.js | wc -c` で測る。

- [ ] **Step 4: コミット**

```bash
git add docs/status.md
git commit -m "docs: Phase 0(React土台とシェル)完了。バンドル実測と既知の制限を記録"
```

---

## 自己レビュー(計画作成時に実施)

**仕様カバレッジ(§6 Phase 0 行)**: React + plugin-react + jsdom/Testing Library → Task 1 / `main.tsx`・`App.tsx`・`useRoute`・`LegacyView` → Task 2, 3 / トークンとシェル(告知・ヘッダ・オムニボックス・ナビ・テーマ切替) → Task 4(告知は静的 div のまま。フッタは Phase 1 のトップと一緒に作る——旧検索ビューが自分のフッタを持つため Phase 0 で足すと二重になる) / 既存4画面が旧ビューのまま動く → Task 3 Step 8, Task 4 Step 11 / sha256 2回一致を React 入りで実証しバンドル増分を記録 → Task 1 Step 7, Task 5 Step 3 / `.tsx` を裁定参照テストへ → Task 3 Step 6。

**§2.3 横断パターンのうち Phase 0 で効くもの**: 「押せるものを押すテスト」→ AppShell.test(オムニボックス Enter・本文へ移動・テーマ切替)。「状態はURLに」→ Omnibox は `navigate` 経由でハッシュに書く。

**プレースホルダ**: 無し(status.md の `<実測>` は「その場で測った値を入れる」指示であり、例の数値を転記させないための書き方)。

**型の整合**: `LegacyMount`/`LegacyController`(Task 3)を App が使う。`ThemePreference`/`ResolvedTheme`(Task 4 theme.ts)を ThemeToggle が使う。`Route` は router.ts のものを全タスクで共有。`useRoute(): Route`(Task 2)を App が使う。名前の食い違いなし。
