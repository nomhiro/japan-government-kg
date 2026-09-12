// squarified treemap(Bruls, Huizing, van Wijk, 1999)の最小実装。
//
// **依存を増やさない。** d3-hierarchy等のライブラリを入れず、この画面が
// 必要とする最小限(1階層・矩形分割)だけを純関数として書く——府省23件を
// 縦棒からツリーマップに置き換える目的は「厚労省が全体の74.6%」という
// 集中の事実を面積として一目で見せることであり、そのために必要なのは
// 「値に比例した面積を持つ、正方形に近い矩形へ分割する」ことだけである。
//
// **線形であること(対数にしないこと)は、この関数の外側の判断ではなく
// この関数自身の性質である。** `value`をそのまま面積に写す(スケール
// 係数は`width*height / 合計値`の1回だけ)——対数を経由すると集中の事実が
// 視覚的に薄れる(裁定済み。`overview-format.ts`の`barWidthPercent`と
// 同じ判断をタイルの面積に対しても適用する)。
//
// **決定的であること。** `Math.random()`を使わない——同じ入力なら常に
// 同じ矩形の集合を返す(順序は値の降順・同値はidの辞書順で固定する)。

export interface TreemapItem {
  readonly id: string;
  readonly value: number;
}

export interface TreemapRect extends TreemapItem {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

interface ScaledItem extends TreemapItem {
  readonly area: number;
}

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * `items`(0件以上。`value`が0以下の項目は落とす——面積0のタイルを
 * 描く意味が無い)を、`width`×`height`の箱にsquarified treemapで
 * 割り付ける。
 *
 * `width`/`height`が0以下、または有効な項目が1件も無ければ空配列を返す。
 */
export function squarifiedTreemap(
  items: readonly TreemapItem[],
  width: number,
  height: number,
): TreemapRect[] {
  if (!(width > 0) || !(height > 0)) return [];
  const positive = items.filter((i) => i.value > 0);
  if (positive.length === 0) return [];

  // **値の降順(同値はidの辞書順)に並べ替えて計算する。** squarified
  // treemapは大きい項目から順に行へ詰めることで正方形に近い矩形を作る
  // アルゴリズムであり、入力の並び順に結果が依存してはならない
  // (同じ集合なら入力順が違っても同じ形になる、というテストが守る)。
  const sorted = [...positive].sort((a, b) => b.value - a.value || a.id.localeCompare(b.id));
  const total = sorted.reduce((s, i) => s + i.value, 0);
  const scale = (width * height) / total;
  const scaled: ScaledItem[] = sorted.map((i) => ({ id: i.id, value: i.value, area: i.value * scale }));

  const out: TreemapRect[] = [];
  let remaining = scaled;
  let rect: Rect = { x: 0, y: 0, width, height };

  while (remaining.length > 0) {
    if (remaining.length === 1) {
      const only = remaining[0]!;
      out.push({ id: only.id, value: only.value, x: rect.x, y: rect.y, width: rect.width, height: rect.height });
      break;
    }

    const shortSide = Math.min(rect.width, rect.height);
    const row = growRow(remaining, shortSide);
    const rowSum = row.reduce((s, i) => s + i.area, 0);
    const thickness = shortSide > 0 ? rowSum / shortSide : 0;

    // 短辺が箱の幅なら、行は幅いっぱいの帯として上に積む
    // (帯の厚みぶん高さを消費し、残りは下)。短辺が箱の高さなら、行は
    // 高さいっぱいの帯として左に積む(残りは右)。
    const bandIsHorizontal = rect.width <= rect.height;
    let cursor = bandIsHorizontal ? rect.x : rect.y;
    for (const item of row) {
      const length = thickness > 0 ? item.area / thickness : 0;
      if (bandIsHorizontal) {
        out.push({ id: item.id, value: item.value, x: cursor, y: rect.y, width: length, height: thickness });
      } else {
        out.push({ id: item.id, value: item.value, x: rect.x, y: cursor, width: thickness, height: length });
      }
      cursor += length;
    }

    rect = bandIsHorizontal
      ? { x: rect.x, y: rect.y + thickness, width: rect.width, height: Math.max(0, rect.height - thickness) }
      : { x: rect.x + thickness, y: rect.y, width: Math.max(0, rect.width - thickness), height: rect.height };
    remaining = remaining.slice(row.length);
  }

  return out;
}

/**
 * 先頭から項目を1つずつ試しに加え、「行の最悪アスペクト比」が改善する
 * (または変わらない)限り加え続ける。悪化する直前で止めて、その行を返す
 * (squarifyアルゴリズムの核——Bruls et al. 1999のpseudocode「squarify」)。
 */
function growRow(items: readonly ScaledItem[], shortSide: number): ScaledItem[] {
  let row: ScaledItem[] = [items[0]!];
  let rowSum = items[0]!.area;
  let i = 1;
  while (i < items.length) {
    const candidate = items[i]!;
    const candidateRow = [...row, candidate];
    const candidateSum = rowSum + candidate.area;
    if (worstAspectRatio(candidateRow, candidateSum, shortSide) <= worstAspectRatio(row, rowSum, shortSide)) {
      row = candidateRow;
      rowSum = candidateSum;
      i += 1;
    } else {
      break;
    }
  }
  return row;
}

/** `row`を厚み`rowSum/shortSide`の帯として並べたときの、最も正方形から遠い(悪い)アスペクト比。 */
function worstAspectRatio(row: readonly ScaledItem[], rowSum: number, shortSide: number): number {
  if (!(rowSum > 0) || !(shortSide > 0)) return Number.POSITIVE_INFINITY;
  const thickness = rowSum / shortSide;
  let worst = 0;
  for (const item of row) {
    const length = item.area / thickness;
    if (!(length > 0)) return Number.POSITIVE_INFINITY;
    const ratio = Math.max(thickness / length, length / thickness);
    if (ratio > worst) worst = ratio;
  }
  return worst;
}
