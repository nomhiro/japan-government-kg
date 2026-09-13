// 最小限のハッシュルータ。React 採用後(裁定B104)も React Router を入れず
// これを使う——`id_path` を再エンコード/再デコードしない往復(router.test.ts)を
// 自前で守るほうが確実で、画面数に対して依存が過剰だから。React 側の入口は
// app/useRoute.ts(hashchange の購読だけ)。
//
// **ハッシュルーティングを選ぶ理由。** パスベースのルーティング
// (`/entity/...`)にすると、深い階層のURLを直接開いたときにCloudflare
// Pagesの`_redirects`でSPAフォールバック(`/*  /index.html  200`)を
// 追加する必要がある。**そのワイルドカードが`/def/*`(オントロジーの
// 恒久的なLOD識別子)を誤って書き換えるリスクを新しく作り込む**——
// 実在するファイルへのリクエストはCloudflareが`_redirects`より先に
// 静的ファイルを返す設計だが、この前提を確かめずに導入するのは危険が
// 大きい。ハッシュはサーバに送られないので、この種のインフラ変更が
// 一切不要になる。
//
// **`id_path`をハッシュに入れるときのエンコード方針**: `id_path`(パス
// セグメント用の値)はAPIに渡すときと同じ形(そのまま。裁定B59/B69)で
// ハッシュのパス部分に置く——`id_path`は既にパーセントエンコード済みで
// URLフラグメントとして合法な文字だけを含むため、追加のエンコードは
// 不要かつ有害(二重エンコードになる)。クエリ部分の値は`encodeURIComponent`/
// `decodeURIComponent`で一貫させる(`api/client.ts`のクエリ値と同じ理由。
// `URLSearchParams`は使わない——`+`とスペースの扱いが食い違うため)。

export type Route =
  | { name: "top" }
  | { name: "search"; q: string }
  | { name: "entity"; idPath: string }
  | { name: "path"; from?: string; to?: string }
  | { name: "chat" }
  | { name: "data" }
  | { name: "notFound"; hash: string };

function parseQuery(qs: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of qs.split("&")) {
    if (!part) continue;
    const eq = part.indexOf("=");
    const k = eq === -1 ? part : part.slice(0, eq);
    const v = eq === -1 ? "" : part.slice(eq + 1);
    out[decodeURIComponent(k)] = decodeURIComponent(v);
  }
  return out;
}

function buildQuery(params: Record<string, string | undefined>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined) continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.join("&");
}

function splitHash(hash: string): { segments: string[]; query: string } {
  const body = hash.replace(/^#\/?/, "");
  const [pathPart = "", queryPart = ""] = body.split("?");
  return {
    segments: pathPart.split("/").filter((s) => s.length > 0),
    query: queryPart,
  };
}

export function parseHash(hash: string): Route {
  const { segments, query } = splitHash(hash);

  if (segments.length === 0) {
    return { name: "top" };
  }
  if (segments[0] === "entity" && segments.length > 1) {
    // id_pathは複数セグメントを含む(例: unresolved/jurisdiction/...)。
    // 先頭の"entity"だけを外し、残りを"/"で結合し直して元のid_pathに戻す。
    return { name: "entity", idPath: segments.slice(1).join("/") };
  }
  if (segments[0] === "search") {
    return { name: "search", q: parseQuery(query).q ?? "" };
  }
  if (segments[0] === "path") {
    const q = parseQuery(query);
    return { name: "path", from: q.from, to: q.to };
  }
  if (segments[0] === "chat") {
    return { name: "chat" };
  }
  if (segments[0] === "data") {
    return { name: "data" };
  }
  // **知らないハッシュは検索に落とさない。** 黙ってトップに戻すと、
  // 打ち間違いや古いリンクが「何も無かった」ように見える(旧実装の挙動)。
  return { name: "notFound", hash };
}

export function routeToHash(route: Route): string {
  switch (route.name) {
    case "top":
      return "#/";
    case "search":
      return route.q ? `#/search?${buildQuery({ q: route.q })}` : "#/search";
    case "entity":
      return `#/entity/${route.idPath}`;
    case "path":
      return `#/path?${buildQuery({ from: route.from, to: route.to })}`;
    case "chat":
      return "#/chat";
    case "data":
      return "#/data";
    case "notFound":
      return route.hash;
  }
}

export function navigate(route: Route): void {
  location.hash = routeToHash(route);
}

// ---------------------------------------------------------------------------
// グラフの状態(エンティティ画面)
// ---------------------------------------------------------------------------
//
// **グラフの見え方はURLに載せる。** 深さ・並べ方・軸の絞り込み・選択中の
// ノードを共有・復元できるようにする(仕様§2.3「状態はURLに」)。
// `Route` の形は変えない —— `parseHash` の entity 分岐の戻り値に任意の
// フィールドを足すと `router.test.ts` が縛っている往復の不変条件に
// 余計な自由度が入るため、グラフの状態は別の関数で読む。

/**
 * グラフの並べ方。
 *
 * - `lanes`: 型で列を決めるレーン流れ図(根拠→所管→事業→…)。
 *   1つの事業の資金の流れを見るときはこれが意味そのもの
 * - `graph`: **層も並び順も辺から決める**構造配置(裁定B112)。
 *   辺の向きが意味を持つ集合を追うときはこちら
 * - `organic`: **円と線の力学配置**(裁定B114)。密度を取る ——
 *   カードは1件ずつ読めるが44件で縦1,470pxになり、全体が一度に見えない
 *
 * 旧 `force`(ForceAtlas2)は削除した。切断された成分のホップ数が
 * `Infinity` になって**全ノードの座標がNaNになる欠陥**があり(本番で実測)、
 * 三部グラフでは毛玉になって読めなかった。
 */
export type GraphLayout = "lanes" | "graph" | "organic";

export interface GraphParams {
  /** 近傍の深さ。APIの上限(1〜2)は呼び出し側が `api/limits.ts` から与える。 */
  readonly depth: number;
  readonly layout: GraphLayout;
  /** 表示する軸。空配列は「すべて」を意味する(絞り込みなし)。 */
  readonly axes: readonly string[];
  /** 選択中のノードの id_path。 */
  readonly selected?: string;
}

export const DEFAULT_GRAPH_PARAMS: GraphParams = {
  depth: 1,
  layout: "lanes",
  axes: [],
};

export function parseGraphParams(
  hash: string,
  options: { readonly defaultLayout?: GraphLayout } = {},
): GraphParams {
  const q = parseQuery(splitHash(hash).query);
  const depth = Number.parseInt(q.d ?? "", 10);
  // 明示された値だけを読み、無ければ呼び出し側の既定(なければ`lanes`)。
  // **検索結果の画面は`graph`を既定にする** ——型の列は集合の俯瞰に向かない。
  const layout: GraphLayout =
    q.lay === "graph" || q.lay === "lanes" || q.lay === "organic"
      ? q.lay
      : (options.defaultLayout ?? "lanes");
  const axes = (q.ax ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  return {
    depth: Number.isFinite(depth) && depth > 0 ? depth : DEFAULT_GRAPH_PARAMS.depth,
    layout,
    axes,
    selected: q.sel && q.sel.length > 0 ? q.sel : undefined,
  };
}

/** エンティティ画面のハッシュを、グラフの状態つきで組み立てる。 */
export function entityHash(idPath: string, params: GraphParams): string {
  const q = buildQuery({
    d: params.depth === DEFAULT_GRAPH_PARAMS.depth ? undefined : String(params.depth),
    lay: params.layout === DEFAULT_GRAPH_PARAMS.layout ? undefined : params.layout,
    ax: params.axes.length > 0 ? params.axes.join(",") : undefined,
    sel: params.selected,
  });
  return q ? `#/entity/${idPath}?${q}` : `#/entity/${idPath}`;
}

/**
 * 検索画面の並べ方の既定。
 *
 * **`organic`(点と線)にする(裁定B114)。** 検索結果は「俯瞰」が目的で、
 * カードは1件ずつ読める代わりに44件で縦1,470pxになり全体が一度に見えない。
 * 円なら同じ44件が1画面に入り、ハブ(複数の事業から参照される府省)が
 * 一目で分かる。名前を読みたいときは「構造」か「すべての関係を表で」に切り替える。
 */
export const SEARCH_DEFAULT_LAYOUT: GraphLayout = "organic";

/**
 * 検索画面のハッシュを、グラフの状態つきで組み立てる(裁定B109)。
 *
 * **`d`(深さ)は載せない。** 検索結果のグラフは各ヒットの深さ1を合算した
 * もので、深さという概念が無い(`search-graph.ts` 参照)。
 *
 * **`q` を必ず保つ。** ここで落とすと、グラフを操作した瞬間に検索語が
 * 消えて結果が空になる。
 */
export function searchGraphHash(q: string, params: GraphParams): string {
  const query = buildQuery({
    q: q || undefined,
    // **この画面の既定は `graph`** なので、省いてよいのは `graph` のときだけ
    // (`lanes` を省くと、読み直したときに既定の `graph` に戻ってしまう)。
    lay: params.layout === SEARCH_DEFAULT_LAYOUT ? undefined : params.layout,
    ax: params.axes.length > 0 ? params.axes.join(",") : undefined,
    sel: params.selected,
  });
  return query ? `#/search?${query}` : "#/search";
}

/** 検索画面のグラフの状態だけを差し替える(履歴を積まない)。 */
export function replaceSearchGraphParams(q: string, params: GraphParams): void {
  const next = searchGraphHash(q, params);
  if (next === location.hash) return;
  history.replaceState(null, "", next);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

/**
 * グラフの状態だけを差し替える(履歴を積まない)。
 * 深さや絞り込みの操作で「戻る」が使い物にならなくなるのを避ける。
 */
export function replaceGraphParams(idPath: string, params: GraphParams): void {
  const next = entityHash(idPath, params);
  if (next === location.hash) return;
  history.replaceState(null, "", next);
  // replaceState は hashchange を発火しない。購読側(useRoute/useGraphParams)に
  // 知らせるため、同じ形のイベントを自分で投げる。
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}
