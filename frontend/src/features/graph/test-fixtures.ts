// テスト専用: 実APIの応答サンプル(`.superpowers/apisamples/*.json`)を読む。
// 架空のデータを作らない(team-leadの指示)ので、テストからは常にこれを経由する。
// `fs`で読む(importでtsconfigの`include`外を参照する形にしない)。
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { EntityDetailResponse, NeighborhoodResponse } from "../../api/client";

// `import.meta.url`はテスト実行環境(jsdom)によって`file://`にならないことが
// あるため使わない。vitestはリポジトリの`frontend/`をカレントディレクトリに
// して実行される(`npm test`が`frontend/`で動く)前提で、そこから1つ上を
// リポジトリルートとする。
const REPO_ROOT = resolve(process.cwd(), "..");

function readJson<T>(relPath: string): T {
  return JSON.parse(readFileSync(resolve(REPO_ROOT, relPath), "utf-8")) as T;
}

export function nbhdMinistry(): NeighborhoodResponse {
  return readJson<NeighborhoodResponse>(".superpowers/apisamples/nbhd-ministry.json");
}

export function nbhdProject(): NeighborhoodResponse {
  return readJson<NeighborhoodResponse>(".superpowers/apisamples/nbhd-project.json");
}

export function entityMinistry(): EntityDetailResponse {
  return readJson<EntityDetailResponse>(".superpowers/apisamples/entity-ministry.json");
}

export function entityProject(): EntityDetailResponse {
  return readJson<EntityDetailResponse>(".superpowers/apisamples/entity-project.json");
}
