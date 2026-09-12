// 出典の見せ方(裁定B86・B106)。
//
// **旧画面の問題**: 属性1行ごとに「(一次資料 (取得: 2026-09-11 / 公共データ
// 利用規約(第1.0版)(PDL1.0)))」を繰り返しており、出典の文字数が値より長く
// なっていた。読めないほど繰り返される出典は、出典を書いていないのと同じである。
//
// **直し方**: 節ごとに1行へまとめる。値の側には「どのソース由来か」を示す
// 小さな印だけを置く。まとめた1行には、
//   - 一次資料URLの**ホスト名**(URLから機械的に取り出す。名前を発明しない)
//   - 取得日(`prov:generatedAtTime`)
//   - ライセンス表記(`dcterms:rights`)
// を出す。`available: false` のグラフはリンクを描かず「出典が取れていない」と
// 明示する(空リンクを描かない。裁定B86)。

import type { Provenance } from "../api/client";

export interface SourceLine {
  /** グラフのキー(応答の `graphs` のキー)。 */
  readonly graph: string;
  /** 一次資料URL。`available: false` のときは undefined。 */
  readonly url?: string;
  /** URLのホスト名。リンクの可読なテキストとして使う(発明ではなく抽出)。 */
  readonly host?: string;
  readonly fetchedOn?: string;
  readonly license?: string;
  readonly available: boolean;
}

/** URLからホスト名だけを取り出す。壊れたURLは undefined(推測で補わない)。 */
export function hostOf(url: string | undefined): string | undefined {
  if (!url) return undefined;
  try {
    return new URL(url).host;
  } catch {
    return undefined;
  }
}

/**
 * 応答の `graphs` を、節の下に1行で出せる形に畳む。
 *
 * 同じ一次資料・同じ取得日のグラフは1件にまとめる(実データでは
 * `houjin-bangou` と `houjin-bangou-payees` が同じURL・同じ取得日を指す)。
 * 並びは「取得日の新しい順 → ホスト名」で決定的にする。
 */
export function sourceLines(
  graphs: Readonly<Record<string, Provenance>> | undefined,
  onlyGraphs?: readonly string[],
): SourceLine[] {
  if (!graphs) return [];
  const wanted = onlyGraphs ? new Set(onlyGraphs) : undefined;
  const byKey = new Map<string, SourceLine>();

  for (const [graph, prov] of Object.entries(graphs)) {
    if (wanted && !wanted.has(graph)) continue;
    const available = prov.available !== false;
    const url = available ? prov.source : undefined;
    const host = hostOf(url);
    // 畳む鍵は「一次資料 + 取得日 + ライセンス」。ここが同じなら利用者には同じ出典。
    const key = available
      ? `${prov.source ?? ""}|${prov.fetched_on ?? ""}|${prov.license ?? ""}`
      : `unavailable|${graph}`;
    if (byKey.has(key)) continue;
    byKey.set(key, {
      graph,
      url,
      host,
      fetchedOn: prov.fetched_on,
      license: prov.license,
      available,
    });
  }

  return [...byKey.values()].sort((a, b) => {
    const d = (b.fetchedOn ?? "").localeCompare(a.fetchedOn ?? "");
    if (d !== 0) return d;
    return (a.host ?? "").localeCompare(b.host ?? "");
  });
}

/**
 * `sourceLines` が返した行から、ライセンス表記だけを重複なく集める。
 * ライセンスは全ソースで同じことが多いので、行ごとに繰り返さず末尾に1回出す。
 */
export function licenseSummary(lines: readonly SourceLine[]): string | undefined {
  const set = new Set(lines.map((l) => l.license).filter((l): l is string => !!l));
  if (set.size === 0) return undefined;
  return [...set].sort().join(" / ");
}
