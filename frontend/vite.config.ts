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
