// 画面ごとの `document.title`。
//
// **なぜ必要か**: ハッシュルーティングなので、どの画面に居ても静的HTMLの
// `<title>`(「JGKG — 日本政府ナレッジグラフ」)がそのまま残っていた。
// タブを並べても履歴を開いてもブックマークを見ても**全部同じ名前**で、
// どれがどの画面か分からない。支援技術も画面の切り替わりを読み上げない
// (WCAG 2.4.2 Page Titled)。この製品は「複数の事業や府省を並べて比べる」
// ために使うものなので、タブの名前が区別できないのは実害である。
//
// **表示名は合成しない(裁定B78/B88)。** エンティティ画面の題に使うのは
// APIが返した `label`(オントロジー由来)だけで、無ければ
// `(表示名なし)` と言う——`id_path` から名前をこちらで作ったりしない。
import { useEffect } from "react";
import type { Route } from "../router";

/** タブに出すサイト名。静的HTMLの `<title>` の後半と同じ。 */
export const SITE_NAME = "日本政府ナレッジグラフ";

/** 画面名をサイト名と繋いだ、そのまま `document.title` に入れられる文字列。 */
export function pageTitle(pageName: string): string {
  return `${pageName} — ${SITE_NAME}`;
}

/**
 * ルートから題を決める。**`entity` だけ `null`** を返す。
 *
 * エンティティ画面の題は「そのエンティティの表示名」であり、それはAPIの
 * 応答が来るまで分からない。`AppShell` と `EntityPage` の両方が
 * `document.title` を書くと、Reactの副作用は子→親の順で走るため親
 * (`AppShell`)が後から上書きしてしまう。**だから entity の題は
 * `EntityPage` だけが書く**(ここは触らない)。
 */
export function titleForRoute(route: Route): string | null {
  switch (route.name) {
    case "top":
      return pageTitle("全体を見る");
    case "search":
      return route.q.trim() === ""
        ? pageTitle("探す")
        : pageTitle(`「${route.q}」の検索結果`);
    case "entity":
      return null;
    case "path":
      return pageTitle("経路をたどる");
    case "chat":
      return pageTitle("聞く");
    case "data":
      return pageTitle("データとAPI");
    case "notFound":
      return pageTitle("このページはありません");
  }
}

/** `title` を `document.title` に書く。`null` のときは何もしない。 */
export function useDocumentTitle(title: string | null): void {
  useEffect(() => {
    if (title !== null) document.title = title;
  }, [title]);
}
