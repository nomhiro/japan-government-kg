// 最小限のハッシュルータ。フレームワークを入れない方針(controllerの設計1)
// なので、この規模(画面3つ)には十分。
//
// **ハッシュルーティングを選ぶ理由。** パスベースのルーティング
// (`/entity/...`)にすると、深い階層のURLを直接開いたときにCloudflare
// Pagesの`_redirects`でSPAフォールバック(`/*  /index.html  200`)を
// 追加する必要がある。**そのワイルドカードが`/def/*`(オントロジーの
// 恒久的なLOD識別子)を誤って書き換えるリスクを新しく作り込む**——
// 実在するファイルへのリクエストはCloudflareが`_redirects`より先に
// 静的ファイルを返す設計だが、この前提を確かめずに導入するのは危険が
// 大きい。ハッシュはサーバに送られないので、この種のインフラ変更が
// 一切不要になる(この判断の根拠はD-5報告に明記する)。
//
// **`id_path`をハッシュに入れるときのエンコード方針**: `id_path`(パス
// セグメント用の値)はAPIに渡すときと同じ形(そのまま。裁定B59/B69)で
// ハッシュのパス部分に置く——`id_path`は既にパーセントエンコード済みで
// URLフラグメントとして合法な文字だけを含むため、追加のエンコードは
// 不要かつ有害(二重エンコードになる)。クエリ部分の値は`encodeURIComponent`/
// `decodeURIComponent`で一貫させる(`api/client.ts`のクエリ値と同じ理由。
// `URLSearchParams`は使わない——`+`とスペースの扱いが食い違うため)。

export type Route =
  | { name: "search"; q: string }
  | { name: "entity"; idPath: string }
  | { name: "path"; from?: string; to?: string };

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

export function parseHash(hash: string): Route {
  const body = hash.replace(/^#\/?/, "");
  const [pathPart = "", queryPart = ""] = body.split("?");
  const segments = pathPart.split("/").filter((s) => s.length > 0);

  if (segments[0] === "entity" && segments.length > 1) {
    // id_pathは複数セグメントを含む(例: unresolved/jurisdiction/...)。
    // 先頭の"entity"だけを外し、残りを"/"で結合し直して元のid_pathに戻す。
    return { name: "entity", idPath: segments.slice(1).join("/") };
  }
  if (segments[0] === "path") {
    const q = parseQuery(queryPart);
    return { name: "path", from: q.from, to: q.to };
  }
  const q = parseQuery(queryPart);
  return { name: "search", q: q.q ?? "" };
}

export function routeToHash(route: Route): string {
  switch (route.name) {
    case "search":
      return route.q ? `#/?${buildQuery({ q: route.q })}` : "#/";
    case "entity":
      return `#/entity/${route.idPath}`;
    case "path":
      return `#/path?${buildQuery({ from: route.from, to: route.to })}`;
  }
}

export function navigate(route: Route): void {
  location.hash = routeToHash(route);
}

export function onRouteChange(handler: (route: Route) => void): void {
  const fire = () => handler(parseHash(location.hash));
  window.addEventListener("hashchange", fire);
  fire();
}
