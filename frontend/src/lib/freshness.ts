// 鮮度(CQ10)の表示用の畳み込み(裁定B111)。
//
// **CQ10は名前付きグラフ1つにつき1行を返す。** 1つのソースが複数のグラフに
// 分かれていれば、同じソース名が複数行に並ぶ ——それがクエリの正しい答えで
// あり、APIはそのまま返す。**画面で畳むのは表示側の判断である。**
//
// **本番の実データで踏んだ**(2026-09-13): 6行のうち
// 「国税庁 法人番号公表サイト 全件データ」が**同じ日付で2行**あった。
// fixtureでは重複が無く、「ソース名は一意」と書いたテストが緑になっていた
// ——実データに当てて初めて崩れた前提である。
//
// 同じことを既にやっている前例が `components/provenance.ts` の `sourceLines`
// にある(ソース・取得日・ライセンスが同じグラフを1行に畳む)。ここも
// **同じ3つ組(ソース名・いつ時点か・日付の種類)が一致する行を1つにする**。
// 日付が違えば畳まない ——「同じソースについて2つの時点がある」は
// 利用者に伝えるべき事実だからである。
import type { ReleaseFreshness } from "../api/client";

/**
 * 表示用に畳んだ鮮度の1行。
 *
 * `graphCount` は畳んだ元の行数。1より大きいとき、そのソースが複数の
 * 名前付きグラフに分かれていることを意味する ——**黙って1つに見せない**
 * ために件数を持つ(画面が出すかどうかは画面の判断)。
 */
export interface FoldedFreshness {
  readonly sourceName: string;
  /** `as_of` の日付部分だけ。タイムゾーン変換はしない。 */
  readonly asOfDate: string;
  readonly dateKind: string;
  readonly graphCount: number;
}

/**
 * 同じ(ソース名・日付・種類)の行を1つに畳む。順序は入力のまま
 * (CQ10が `ORDER BY ?sourceName` で返した順を尊重する)。
 */
export function foldFreshness(rows: readonly ReleaseFreshness[]): FoldedFreshness[] {
  const byKey = new Map<string, { row: FoldedFreshness; count: number }>();
  const order: string[] = [];
  for (const row of rows) {
    const asOfDate = row.as_of.slice(0, 10);
    // **区切り文字を使わずJSONで鍵を作る。** ソース名にどんな文字が来ても
    // 曖昧にならない。NUL文字を区切りに使うとgitがファイルをバイナリ扱い
    // にする(このプロジェクトで実際に踏んだ。裁定B106のグラフモデル)。
    const key = JSON.stringify([row.source_name, asOfDate, row.date_kind]);
    const found = byKey.get(key);
    if (found) {
      found.count += 1;
      continue;
    }
    byKey.set(key, {
      row: { sourceName: row.source_name, asOfDate, dateKind: row.date_kind, graphCount: 1 },
      count: 1,
    });
    order.push(key);
  }
  return order.map((key) => {
    const entry = byKey.get(key)!;
    return { ...entry.row, graphCount: entry.count };
  });
}
