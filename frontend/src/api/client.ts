// API層(D-3/D-4)への薄いクライアント。表示だけを作る段(D-5ブリーフ)なので、
// ここにドメインロジックを持たせない——SPARQLもURL組み立ての規則も、
// 既にAPIが決めている。ここでやるのは「その規則を守って呼ぶ」だけ。
import type { components } from "./openapi-types";

export type SearchResponse = components["schemas"]["SearchResponse"];
export type SearchHit = components["schemas"]["SearchHit"];
export type EntityRef = components["schemas"]["EntityRef"];
export type EntityDetailResponse = components["schemas"]["EntityDetailResponse"];
export type NeighborhoodResponse = components["schemas"]["NeighborhoodResponse"];
export type GraphEdge = components["schemas"]["GraphEdge"];
export type Provenance = components["schemas"]["Provenance"];
export type PathResponse = components["schemas"]["PathResponse"];
export type Relationship = components["schemas"]["Relationship"];

// **APIの本番URLを直書きしない(base_uriと同じ規律。D-5ブリーフ)。**
// ビルド時の設定値にする——D-6b(配備先)が未決なため、既定はローカルの
// `uv run uvicorn jgkg.api.app:create_production_app --factory`(既定ポート8000)。
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

/**
 * クエリ文字列の値を正しくエンコードする(裁定B73)。
 *
 * `URLSearchParams`は使わない——`application/x-www-form-urlencoded`の
 * シリアライズはスペースを`+`に変換するが、`app.py`の`/path`ハンドラは
 * `urllib.parse.unquote`(plain)を1回かけるだけで、`+`を空白に戻す
 * `unquote_plus`ではない。`id_path`は既にパーセントエンコード済みの文字列
 * (`%E5%8E%9A...`)を含むので、それをさらに`encodeURIComponent`で
 * 1回だけエンコードしたものをサーバに送る——サーバ側の`unquote`1回で
 * 元の`id_path`(パスセグメント経由で受け取る形と同じ)に戻る。
 */
function encodeQueryValue(v: string): string {
  return encodeURIComponent(v);
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined) continue;
    parts.push(`${encodeQueryValue(k)}=${encodeQueryValue(String(v))}`);
  }
  return parts.join("&");
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(url: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new ApiError(0, `APIに接続できません(${API_BASE})。ローカルで開発中の場合は ` +
      "`uv run uvicorn jgkg.api.app:create_production_app --factory` を起動してください。" +
      `(${String(e)})`);
  }
  if (res.status === 404) {
    // 404はエラーではなく「見つからなかった」という値として呼び出し側に返す
    // (呼び出し側の型で null として表現する)。
    throw new ApiError(404, "not found");
  }
  if (!res.ok) {
    throw new ApiError(res.status, `APIが${res.status}を返しました: ${url}`);
  }
  return (await res.json()) as T;
}

export async function search(q: string, limit?: number): Promise<SearchResponse> {
  return getJson<SearchResponse>(`${API_BASE}/search?${buildQuery({ q, limit })}`);
}

/**
 * `idPath`は`EntityRef.id_path`をそのまま渡す(裁定B59/B69)。
 * ここでURLを組み立て直したり、`id`(完全IRI)からパスを作ったりしない。
 */
export async function entityDetail(
  idPath: string,
  limit?: number,
): Promise<EntityDetailResponse | null> {
  const qs = limit !== undefined ? `?${buildQuery({ limit })}` : "";
  try {
    return await getJson<EntityDetailResponse>(`${API_BASE}/entity/${idPath}${qs}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export interface NeighborhoodParams {
  depth?: number;
  node_limit?: number;
  edge_limit?: number;
  fanout_limit?: number;
}

export async function neighborhood(
  idPath: string,
  params: NeighborhoodParams = {},
): Promise<NeighborhoodResponse | null> {
  const qs = buildQuery(params as Record<string, number | undefined>);
  const url = qs ? `${API_BASE}/neighborhood/${idPath}?${qs}` : `${API_BASE}/neighborhood/${idPath}`;
  try {
    return await getJson<NeighborhoodResponse>(url);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export interface FindPathParams {
  max_depth?: number;
  visit_budget?: number;
  fanout_limit?: number;
}

export async function findPath(
  fromIdPath: string,
  toIdPath: string,
  params: FindPathParams = {},
): Promise<PathResponse | null> {
  const qs = buildQuery({ from: fromIdPath, to: toIdPath, ...params });
  try {
    return await getJson<PathResponse>(`${API_BASE}/path?${qs}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}
