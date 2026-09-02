import { defineConfig } from "vite";

// D-5(仕様§9.2)。フレームワークを入れない方針(controllerの設計1)なので、
// Vite本体の既定に極力乗る。
//
// **ビルド時刻や乱数を出力に埋め込まない。** ここで特別な設定はしていないが、
// それ自体が意図——Viteの既定の出力(index.html + assets/*.js/css、
// ファイル名は内容のハッシュ)はビルド時刻に依存しない。再現性の検査
// (scripts/check-frontend-build.py。裁定B81)がこの前提を実際に確認する。
//
// **出力先を`../site`に直接指定しない。** Viteはproject root外のoutDirを
// 空にする(`emptyOutDir`)際、対象ディレクトリ全体を削除しうる——`site/`は
// `/def/`(オントロジーの一覧ページ含む)・`sitemap.txt`・`_headers`等、
// このアプリと無関係な内容を同居させているため、Vite自身に`site/`を
// 触らせるのは危険が大きい。既定の`dist/`にビルドし、`site.sync_app()`
// (`scripts/build-site.sh`が呼ぶ)が`index.html`と`assets/`だけを
// 差分無く同期する——影響範囲を明示的に絞る。
export default defineConfig({
  build: {
    outDir: "dist",
  },
});
