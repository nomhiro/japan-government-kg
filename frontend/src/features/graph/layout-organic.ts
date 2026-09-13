// 「点と線」配置(裁定B114)。**密度を取る。**
//
// **なぜ要るか(利用者が示した画面)**: ナレッジグラフの探索ツールは、
// ノードを小さな円で描いて力学的に散らす。44ノードが1画面に入り、ハブと
// 衛星が一目で分かる。いまのカード(208×36)は1件ずつ読めるが、44件で
// 縦1,470pxになり**全体が一度に見えない** ——「俯瞰したい」という要求
// (裁定B104のD1)に対して、密度が足りていなかった。
//
// **d3-force を使う理由**: 乱数が `Math.random()` ではなく**種を固定した
// LCG**(`d3-force/src/lcg.js`)なので、**同じグラフから常に同じ座標が出る**。
// 実測で確認した(同じ入力で2回走らせて全座標が一致・NaN無し)。
// 89KBで、`forceCollide` による重なり回避と切断された成分の寄せ集めも持つ。
//
// **旧ForceAtlas2の失敗を繰り返さない**: あれは初期位置を「中心からの
// ホップ数×半径」で置いていたため、到達できないノードのホップが `Infinity`
// になって全座標が `NaN` になった(裁定B112で本番実測)。ここでは
// **ホップを使わない** ——初期位置はid順の螺旋で、切断された成分は
// 弱い中心力で寄る。
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationNodeDatum,
} from "d3-force";
import type { GraphModel, ModelEdge } from "./graph-model";
import type { GraphLayoutResult, PlacedEdge, PlacedNode } from "./types";

/** 円の最小半径。これより小さくすると押せる的が44pxを大きく下回る。 */
const MIN_R = 13;
/** 次数で増える半径の上限。大きすぎると1つのハブが画面を占める。 */
const MAX_EXTRA_R = 11;
/** 円のあいだに空ける余白(重なり回避)。 */
const COLLIDE_PAD = 6;
/** 反復回数。固定にすることで決定的になる(乱数の種も固定されている)。 */
const DEFAULT_TICKS = 400;
const MARGIN = 32;
/** 初期位置の螺旋の間隔。 */
const SPIRAL_STEP = 26;

export interface OrganicLayoutOptions {
  readonly ticks?: number;
}

/** 次数から円の半径を決める。ハブが大きく見える。 */
export function radiusForDegree(degree: number): number {
  return MIN_R + Math.min(MAX_EXTRA_R, Math.sqrt(Math.max(0, degree)) * 3);
}

interface SimNode extends SimulationNodeDatum {
  readonly id: string;
  readonly r: number;
}

function compareById(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function compareEdges(a: ModelEdge, b: ModelEdge): number {
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

function round(n: number): number {
  return Math.round(n * 10) / 10;
}

/**
 * 力学配置の座標を計算する。**決定的**——ノードと辺をid順に入れ、
 * 初期位置を螺旋で固定し、反復回数も固定する。`d3-force` の乱数は
 * 種固定のLCGなので、この3つを固定すれば出力は毎回同じになる。
 */
export function layoutOrganic(
  model: GraphModel,
  options: OrganicLayoutOptions = {},
): GraphLayoutResult {
  const ticks = options.ticks ?? DEFAULT_TICKS;
  const nodes = [...model.nodes].sort(compareById);
  if (nodes.length === 0) {
    return { nodes: [], edges: [], lanes: [], width: 1, height: 1 };
  }

  // **初期位置は決定的な螺旋。** ホップ数を使わない(旧ForceAtlas2が
  // `Infinity` を掴んで全座標をNaNにした原因。裁定B112)。
  const sim: SimNode[] = nodes.map((n, i) => {
    const angle = i * 2.399963; // 黄金角。重なりの少ない螺旋になる
    const radius = SPIRAL_STEP * Math.sqrt(i + 1);
    return {
      id: n.id,
      r: radiusForDegree(n.degree),
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
    };
  });
  const simById = new Map(sim.map((s) => [s.id, s]));

  const edges = [...model.edges].sort(compareEdges);
  const links = edges
    .filter((e) => e.source !== e.target && simById.has(e.source) && simById.has(e.target))
    .map((e) => ({ source: e.source, target: e.target }));

  forceSimulation(sim)
    .force(
      "link",
      forceLink<SimNode, { source: string; target: string }>(links)
        .id((d) => d.id)
        .distance(72)
        .strength(0.7),
    )
    .force("charge", forceManyBody<SimNode>().strength(-170))
    .force(
      "collide",
      forceCollide<SimNode>().radius((d) => d.r + COLLIDE_PAD),
    )
    // **切断された成分を寄せる弱い中心力。** これが無いと成分が無限に
    // 離れていき、全体を1画面に収められない(「俯瞰」の用を成さない)。
    .force("x", forceX(0).strength(0.075))
    .force("y", forceY(0).strength(0.075))
    .stop()
    .tick(ticks);

  const minX = Math.min(...sim.map((s) => (s.x ?? 0) - s.r));
  const minY = Math.min(...sim.map((s) => (s.y ?? 0) - s.r));
  const dx = MARGIN - minX;
  const dy = MARGIN - minY;

  const placedById = new Map<string, PlacedNode>();
  const placedNodes: PlacedNode[] = nodes.map((n) => {
    const s = simById.get(n.id)!;
    const cx = (s.x ?? 0) + dx;
    const cy = (s.y ?? 0) + dy;
    const placed: PlacedNode = {
      id: n.id,
      idPath: n.idPath,
      type: n.type,
      label: n.label,
      describedBy: n.describedBy,
      axis: n.axis,
      laneKey: n.laneKey,
      hop: n.hop,
      degree: n.degree,
      hasMore: n.hasMore,
      shape: "dot",
      // 円の外接矩形の左上。描画側は `translate(x,y)` してから
      // 中心 (r, r) に円を描く(カードと同じ約束で位置を持つ)。
      x: round(cx - s.r),
      y: round(cy - s.r),
      w: round(s.r * 2),
      h: round(s.r * 2),
    };
    placedById.set(n.id, placed);
    return placed;
  });

  // 同じ2点を結ぶ辺が複数あるとき、順番で膨らみを変えて重ならないようにする。
  const parallelIndex = new Map<string, number>();
  const placedEdges: PlacedEdge[] = [];
  for (const e of edges) {
    const s = placedById.get(e.source);
    const t = placedById.get(e.target);
    if (!s || !t || e.source === e.target) continue;
    const pairKey = [e.source, e.target].sort().join(" ");
    const index = parallelIndex.get(pairKey) ?? 0;
    parallelIndex.set(pairKey, index + 1);
    placedEdges.push({
      key: e.key,
      source: e.source,
      target: e.target,
      predicate: e.predicate,
      graph: e.graph,
      d: arcBetween(s, t, index),
      flip: false,
    });
  }

  const width = Math.max(1, Math.round(Math.max(...placedNodes.map((n) => n.x + n.w)) + MARGIN));
  const height = Math.max(1, Math.round(Math.max(...placedNodes.map((n) => n.y + n.h)) + MARGIN));
  return { nodes: placedNodes, edges: placedEdges, lanes: [], width, height };
}

/**
 * 円の縁から縁へ弧を引く。矢印が円の内側に隠れないよう、**両端を半径分
 * 縮める**(カードのときは辺と辺で接するので不要だった)。
 */
export function arcBetween(s: PlacedNode, t: PlacedNode, parallelIndex = 0): string {
  const sr = s.w / 2;
  const tr = t.w / 2;
  const sx = s.x + sr;
  const sy = s.y + sr;
  const tx = t.x + tr;
  const ty = t.y + tr;
  const dx = tx - sx;
  const dy = ty - sy;
  const dist = Math.hypot(dx, dy) || 1;
  const ux = dx / dist;
  const uy = dy / dist;
  const x1 = sx + ux * sr;
  const y1 = sy + uy * sr;
  const x2 = tx - ux * tr;
  const y2 = ty - uy * tr;
  if (parallelIndex === 0) {
    return `M ${round(x1)} ${round(y1)} L ${round(x2)} ${round(y2)}`;
  }
  // 2本目以降は垂直方向に膨らませる(向きは交互)。
  const bulge = (Math.ceil(parallelIndex / 2) * 18 * (parallelIndex % 2 === 1 ? 1 : -1)) / 1;
  const mx = (x1 + x2) / 2 - uy * bulge;
  const my = (y1 + y2) / 2 + ux * bulge;
  return `M ${round(x1)} ${round(y1)} Q ${round(mx)} ${round(my)}, ${round(x2)} ${round(y2)}`;
}

/** ラベルの1行の高さ(重なり判定に使う)。 */
const LABEL_LINE_H = 13;

/**
 * 円のラベルが**互いに重ならないように縦へ逃がす量**を決める(裁定B114)。
 *
 * 力学配置は位置を構造から決めるので、ラベルの衝突までは面倒を見ない。
 * 実測(「AI」44ノード)で29個のラベルが出て、そのうち数組が重なって
 * 読めなかった。**y順に見て、直前のラベルと重なるなら下へ押す**という
 * 貪欲な方法で大半が解ける ——完全な解(ラベル配置問題)は要らない。
 *
 * 返すのは id → 縦のずれ(px)。ずれを持たないノードは0。
 */
export function labelOffsets(
  nodes: readonly PlacedNode[],
  labelled: ReadonlySet<string>,
): Map<string, number> {
  const rows = nodes
    .filter((n) => labelled.has(n.id))
    .map((n) => ({ id: n.id, x: n.x + n.w, y: n.y + n.h / 2 }))
    .sort((a, b) => (a.y !== b.y ? a.y - b.y : a.id < b.id ? -1 : 1));

  const offsets = new Map<string, number>();
  const placed: { x: number; y: number }[] = [];
  for (const row of rows) {
    let y = row.y;
    // 横が十分離れていれば重ならない(ラベルの幅は概算で120px)。
    for (const prev of placed) {
      if (Math.abs(prev.x - row.x) > 120) continue;
      if (Math.abs(prev.y - y) < LABEL_LINE_H) {
        y = prev.y + LABEL_LINE_H;
      }
    }
    offsets.set(row.id, Math.round((y - row.y) * 10) / 10);
    placed.push({ x: row.x, y });
  }
  return offsets;
}
