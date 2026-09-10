// グラフのノード色・凡例をオントロジーの6軸から決める(裁定B92のE-1)。
//
// **「型→軸」はオントロジーから導出する(`labels.ts`の`axisForType`。
// `frontend_labels.py`が`rdfs:subClassOf`を辿って生成)。** ここで決めるのは
// その先——**「軸ごとにどの色相を使うか」だけ**であり、これはオントロジーに
// 「色」という概念が無い以上、表示だけの判断である(`graph.ts`に元々あった
// コメントと同じ立場。ここでは色の"値"だけを表示側の判断として残し、
// "どの型が同じ色を共有するか"という軸の切り方そのものは生成物に委ねる)。
//
// 軸の色相の割り当て順序(`AXIS_ORDER`)は、`schema/core.yaml`冒頭コメント
// 「6軸(誰が/何を/どこで/いつ/いくらで/何について)」の並び
// (Agent/Work/Place/Event/MonetaryItem/Concept)をそのまま使う——ここで
// 新しい順序を考案していない。
//
// **同じ軸内の型がどの順で明度を振られるか(`siblingTypesInAxis`。
// `labels.ts`)も生成物から導出する。** 「いま画面に出ている型だけを
// 数えて順番を振る」方式にすると、後から展開して新しい型が増えるたびに
// 既存ノードの色が変わってしまう——`colorForType`は型のローカル名だけから
// 決まる、状態に依存しない色を返す。

import { axisForType, siblingTypesInAxis } from "./labels";

const AXIS_ORDER: readonly string[] = ["Agent", "Work", "Place", "Event", "MonetaryItem", "Concept"];
const HUE_STEP = 360 / AXIS_ORDER.length;
// 210°(青系・Agent)から開始する。0°/360°(赤)は既存の`--signal`
// (エラー・注記表示。style.css)が使う色域なので避けた。
const HUE_START = 210;

/**
 * `UnresolvedReference`は6軸のいずれでもない(`core.yaml`の
 * `Entity`docstring: 「6軸とUnresolvedReferenceは互いに素である」)。
 * 色相のローテーションに混ぜず、常に同じ無彩色にする——「解決できて
 * いない」という状態を、軸の一員のように見せないための意図的な区別。
 */
export const UNRESOLVED_AXIS = "UnresolvedReference";

/** 型→軸が引けなかったとき(裁定B92のテストが検査する異常系)のプレースホルダ軸名。 */
export const UNKNOWN_AXIS = "unknown-axis";

/**
 * HSL(色相0-360, 彩度/明度0-100)からCSSの16進カラーコードへ変換する純粋関数。
 * 標準的な変換式(参考: W3C CSS Color 4)をそのまま実装したもので、
 * 型ごとの色を直書きしない代わりに、この式1つだけを固定する。
 */
export function hslToHex(h: number, s: number, l: number): string {
  const hh = ((h % 360) + 360) % 360;
  const ss = s / 100;
  const ll = l / 100;
  const k = (n: number): number => (n + hh / 30) % 12;
  const a = ss * Math.min(ll, 1 - ll);
  const f = (n: number): number => ll - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  const toHex = (x: number): string => Math.round(255 * x).toString(16).padStart(2, "0");
  return `#${toHex(f(0))}${toHex(f(8))}${toHex(f(4))}`;
}

/** 軸のローカル名(6軸のいずれか)→色相。6軸に無い名前(UnresolvedReference・軸不明を含む)は`undefined`。 */
export function hueForAxis(axis: string): number | undefined {
  const i = AXIS_ORDER.indexOf(axis);
  return i === -1 ? undefined : HUE_START + i * HUE_STEP;
}

const GRAY = hslToHex(0, 0, 50);
const UNKNOWN_GRAY = hslToHex(0, 0, 68);

/**
 * 軸(`axisForType`の戻り値)と、同じ軸内での並び順(`siblingIndex`。0始まり)
 * から色を決める。**濃淡で同じ軸内の型を区別する**(ブリーフ要求。
 * 「型そのもの」ではなく「軸+軸内の位置」から導出するので、型ごとの
 * 色を直書きした対応表を持たない)。
 *
 * - 軸が`undefined`(型→軸が引けない。裁定B92のテスト対象): 薄い灰色
 *   (`UnresolvedReference`の灰色とは明度を変え、見分けられるようにする)
 * - `UNRESOLVED_AXIS`: 固定の灰色(6軸のローテーションには入れない)
 * - 6軸のいずれか: 軸の色相を固定し、`siblingIndex`で明度を振る
 */
export function colorForAxis(axis: string | undefined, siblingIndex = 0): string {
  if (axis === undefined) return UNKNOWN_GRAY;
  if (axis === UNRESOLVED_AXIS) return GRAY;
  const hue = hueForAxis(axis);
  if (hue === undefined) return UNKNOWN_GRAY; // 将来Entityの子に軸が増え、AXIS_ORDERの更新を忘れた場合
  // 64%から8ずつ下げる。8段(64,56,...,8)で一巡してから繰り返す——現時点で
  // 最大の軸(Agent軸5件)より十分広く、将来型が増えても当分は衝突しない。
  // 8段目以降は明度が一巡して重なるが、それは「色だけでは区別しきれない
  // ほど型が増えた」という表示上の限界であり、値そのものが壊れるわけではない。
  const lightness = 64 - (siblingIndex % 8) * 8;
  return hslToHex(hue, 62, lightness);
}

/**
 * 型のローカル名から色を1つに決める、型→色の唯一の入口。
 * `siblingTypesInAxis`(labels.ts)が返す「同じ軸を共有する型の辞書順の
 * 一覧」の中で自分が何番目かを`colorForAxis`のsiblingIndexに渡す——
 * **この関数だけが「ノードの色」と「凡例の色」の両方から呼ばれることで、
 * 両者が常に一致することを保証する**(`groupByAxis`は自前で色を計算しない)。
 */
export function colorForType(type: string): string {
  const axis = axisForType(type);
  if (axis === undefined) return colorForAxis(undefined);
  const siblings = siblingTypesInAxis(type);
  const index = siblings.indexOf(type);
  return colorForAxis(axis, index === -1 ? 0 : index);
}

export interface LegendGroup {
  /** 軸のローカル名。`UNKNOWN_AXIS`は型→軸が引けなかった場合の受け皿。 */
  axis: string;
  items: Array<{ type: string; color: string }>;
}

/**
 * 現在表示中の型の集合(`presentTypes`)を軸ごとにまとめ、決定的な順序
 * (`AXIS_ORDER`→`UnresolvedReference`→軸不明)で返す。**呼び出し側
 * (`graph.ts`)は表示名の解決(`typeLabel`/`axisForType`)を行わず、ここには
 * ローカル名だけを渡す**——DOM文字列を組み立てない純粋関数にして、
 * vitestで件数まで検査できるようにする(D-5の方針)。
 *
 * 同じ軸内の型はローカル名の辞書順で並べる(決定的。「最初に出現した順」
 * のような、実行ごとに変わりうる順序をここに持たない)。**色は自前で
 * 計算せず、`colorOf`(通常は`colorForType`)に委ねる**——ノードの実際の色
 * (`addEntityNode`が`colorForType`を直接呼ぶ)と凡例の色が食い違わない
 * ようにするため(食い違うと「凡例がノードの色と違う」という、このプロジェクトの
 * 一次資料への信頼を損なう類の欠陥になる)。
 */
export function groupByAxis(
  presentTypes: Iterable<string>,
  axisOf: (type: string) => string | undefined,
  colorOf: (type: string) => string,
): LegendGroup[] {
  const byAxis = new Map<string, string[]>();
  for (const type of new Set(presentTypes)) {
    const axis = axisOf(type) ?? UNKNOWN_AXIS;
    const list = byAxis.get(axis);
    if (list) list.push(type);
    else byAxis.set(axis, [type]);
  }

  const order = (axis: string): number => {
    const i = AXIS_ORDER.indexOf(axis);
    if (i !== -1) return i;
    if (axis === UNRESOLVED_AXIS) return AXIS_ORDER.length;
    return AXIS_ORDER.length + 1; // UNKNOWN_AXIS
  };

  return Array.from(byAxis.entries())
    .sort(([a], [b]) => order(a) - order(b))
    .map(([axis, types]) => ({
      axis,
      items: [...types].sort().map((type) => ({ type, color: colorOf(type) })),
    }));
}
