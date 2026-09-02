// UIのコントロール(スライダー・セレクト等)の範囲を、生成したOpenAPI
// スキーマから導出する(D-5ブリーフ「UIのコントロールの範囲を、生成した型
// から導出してください」)。手書きで揃えると、queries.pyの上限定数
// (NEIGHBORHOOD_MAX_DEPTH等)が変わったときにUIだけ古い範囲のまま残る
// ——このプロジェクトの再発欠陥1(導出すべき値の手書き)そのものになる。
//
// **`openapi-types.ts`(生成物)からではなく`openapi.json`(生成物。同じく
// コミットする)から読む。** TypeScriptの数値型には範囲を持たせられないため、
// `openapi-typescript`は`minimum`/`maximum`をJSDocコメント(文字列)に
// しか落とせない——プログラムから安全に取り出せるのは生JSONの方だけである。
import rawOpenApi from "../../openapi.json";

interface ParamSchema {
  minimum?: number;
  maximum?: number;
  default?: number;
}

interface OpenApiParameter {
  name: string;
  schema?: ParamSchema;
}

interface OpenApiOperation {
  parameters?: OpenApiParameter[];
}

interface OpenApiDoc {
  paths: Record<string, Record<string, OpenApiOperation>>;
}

const openApi = rawOpenApi as unknown as OpenApiDoc;

export interface Bounds {
  min: number;
  max: number;
  default: number;
}

/** `path`(OpenAPIのキー。例: "/neighborhood/{entity_id}")のGETの、`name`という

 * クエリ/パスパラメータの範囲を取り出す。見つからなければ例外にする——
 * 黙ってUIの範囲を無制限にする方が、上限を守っているつもりで実は守って
 * いない状態を生むので危険(このプロジェクトが繰り返し扱う「導出元が
 * 変わったのに追随しない」欠陥の予防)。
 */
function bounds(path: string, name: string): Bounds {
  const params = openApi.paths[path]?.get?.parameters ?? [];
  const p = params.find((x) => x.name === name);
  const schema = p?.schema;
  if (!schema || schema.minimum === undefined || schema.maximum === undefined || schema.default === undefined) {
    throw new Error(
      `openapi.jsonから${path} ${name}の範囲(minimum/maximum/default)を取り出せない。` +
        "scripts/generate-frontend-types.sh を再実行したか確認すること",
    );
  }
  return { min: schema.minimum, max: schema.maximum, default: schema.default };
}

export const SEARCH_LIMIT = bounds("/search", "limit");
export const ENTITY_RELATIONSHIPS_LIMIT = bounds("/entity/{entity_id}", "limit");
export const NEIGHBORHOOD_DEPTH = bounds("/neighborhood/{entity_id}", "depth");
export const NEIGHBORHOOD_NODE_LIMIT = bounds("/neighborhood/{entity_id}", "node_limit");
export const NEIGHBORHOOD_EDGE_LIMIT = bounds("/neighborhood/{entity_id}", "edge_limit");
export const NEIGHBORHOOD_FANOUT_LIMIT = bounds("/neighborhood/{entity_id}", "fanout_limit");
export const PATH_MAX_DEPTH = bounds("/path", "max_depth");
export const PATH_VISIT_BUDGET = bounds("/path", "visit_budget");
export const PATH_FANOUT_LIMIT = bounds("/path", "fanout_limit");
