// グラフ描画の色を**CSSのトークンから読む**(裁定B95)。
//
// **Sigma.jsはCSSを見ない。** ノードラベルの色は`settings.labelColor`で
// 明示しない限り既定の**黒(`#000`)**で描かれる——`style.css`が
// `prefers-color-scheme: dark`で`--ink`を明るい色に切り替えても、
// **キャンバスの文字だけが黒のまま**残る。
//
// ユーザーの報告(2026-09-11):
//   > ダークモードでも見やすいように。いまは文字が黒色で見にくいところがある。
//
// グラフが画面の主役になった(E-1)ことで、この欠陥が主要な読みにくさに
// なっていた。**色の単一の出典はCSSのトークンに置き、こちらはそれを読む**
// ——TypeScript側にダーク用の色を書き足すと、トークンと二重管理になる
// (再発欠陥1「導出すべき値を手書きする」の変種)。

/** `getComputedStyle`が返す形だけを要求する(テストからスタブできるように)。 */
export interface ComputedStyleLike {
  getPropertyValue(property: string): string;
}

export interface GraphTheme {
  /** ノード/辺のラベルの文字色(`--ink`) */
  label: string;
  /** 辺の線の色(`--rule`より濃く、`--ink`より薄い`--muted`) */
  edge: string;
}

/**
 * CSSのカスタムプロパティからグラフの色を読む。
 *
 * **空文字列が返る場合に備える。** `getPropertyValue`は未定義のプロパティに
 * 対して空文字列を返す(例外にならない)ので、そのままSigmaに渡すと
 * 色指定が壊れる。**代替値はライトモードの値**にする——ダークを既定に
 * すると、トークンが読めない環境で白背景に白文字になりうる。
 */
export function readGraphTheme(style: ComputedStyleLike): GraphTheme {
  const pick = (name: string, fallback: string): string => {
    const v = style.getPropertyValue(name).trim();
    return v === "" ? fallback : v;
  };
  return {
    label: pick("--ink", "#16191d"),
    edge: pick("--muted", "#5c636d"),
  };
}
