// レーン流れ図の座標を計算する純関数(裁定B106)。同心円や力学配置ではなく、
// `ontology-view.ts`のレーン(根拠→所管→事業→段・年度→支出→支払先)を
// 左から右へ列にする —— 資金と権限の流れをそのまま画面の左右に写す
// ことで、力学配置の「毛玉」を避ける(team-leadの指示の核)。
//
// **決定的であること。** `Math.random()`を使わない。並び順は次数→表示名
// (フォールバック込み)→idで確定させ、同じ入力からは常に同じ出力になる
// (再発欠陥: 旧実装が展開時にジッタで乱数を使っていた)。
import { ASIDE_LANE, LANES, type Lane } from "../../lib/ontology-view";
import { displayLabel, type GraphModel, type ModelEdge, type ModelNode } from "./graph-model";
import type { GraphLayoutResult, LaneBand, PlacedEdge, PlacedNode } from "./types";

export const CARD_W = 208;
export const CARD_H = 36;
export const GAP_Y = 8;
export const GAP_X = 56;
export const MARGIN_X = 24;
export const MARGIN_TOP = 16;
export const HEADER_H = 40;
export const ASIDE_GAP_Y = 40;
export const DEFAULT_MAX_PER_LANE = 18;

export interface LaneLayoutOptions {
  /** レーン1本あたり、これを超えたら「+N件」に折る(既定18)。 */
  readonly maxPerLane?: number;
  /** 「+N件」を押して全件展開したレーンのキー集合。 */
  readonly expandedLanes?: ReadonlySet<string>;
}

function sortKey(n: ModelNode): [number, string, string] {
  return [-n.degree, displayLabel(n.label), n.id];
}

function compareNodes(a: ModelNode, b: ModelNode): number {
  const [da, la, ia] = sortKey(a);
  const [db, lb, ib] = sortKey(b);
  if (da !== db) return da - db;
  if (la !== lb) return la < lb ? -1 : 1;
  if (ia !== ib) return ia < ib ? -1 : 1;
  return 0;
}

function bezierPath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = x2 - x1;
  const bulge = Math.max(Math.abs(dx) * 0.4, 40);
  const c1x = x1 + bulge;
  const c2x = x2 - bulge;
  return `M ${x1} ${y1} C ${c1x} ${y1}, ${c2x} ${y2}, ${x2} ${y2}`;
}

/**
 * 配置済みノードの位置(x/y、カード中心の左端・縦中心を想定)から辺を作る。
 * どちらのレイアウト(レーン/力学)からも呼べる共有部品 ——
 * **視覚上は常に左(x小)→右(x大)に流れる**ように`d`を作り、RDFの実際の
 * `source`/`target`と描画の向きが逆になったときだけ`flip: true`にする
 * (Inspector・hoverの述語表示は`flip`を見て正しい向きを言えるようにする)。
 * 両端がどちらも配置されていない辺(レーンの折り畳みで隠れたノードへの辺)は
 * 結果に含めない——存在しない位置へ描かないため。
 */
export function buildPlacedEdges(
  nodes: readonly PlacedNode[],
  edges: readonly ModelEdge[],
): PlacedEdge[] {
  const posById = new Map<string, PlacedNode>();
  for (const n of nodes) posById.set(n.id, n);

  const placed: PlacedEdge[] = [];
  for (const e of edges) {
    const s = posById.get(e.source);
    const t = posById.get(e.target);
    if (!s || !t) continue;

    const sameColumn = s.x === t.x;
    const flip = !sameColumn && s.x > t.x;

    let d: string;
    if (sameColumn) {
      // 同じレーン内の辺: 右側に張り出す弧で上下のカードを結ぶ。左右の流れが
      // 無いので「左→右」の正規化は意味を持たず、`flip`は常にfalseにする
      // (このレーン内の辺は視覚上の向きの問題が起きない)。
      const top = s.y <= t.y ? s : t;
      const bottom = s.y <= t.y ? t : s;
      const xEdge = top.x + top.w;
      const y1 = top.y + top.h / 2;
      const y2 = bottom.y + bottom.h / 2;
      const bulge = 36;
      d = `M ${xEdge} ${y1} C ${xEdge + bulge} ${y1}, ${xEdge + bulge} ${y2}, ${xEdge} ${y2}`;
    } else {
      const from = flip ? t : s;
      const to = flip ? s : t;
      const x1 = from.x + from.w;
      const y1 = from.y + from.h / 2;
      const x2 = to.x;
      const y2 = to.y + to.h / 2;
      d = bezierPath(x1, y1, x2, y2);
    }

    placed.push({
      key: e.key,
      source: e.source,
      target: e.target,
      predicate: e.predicate,
      graph: e.graph,
      d,
      flip,
    });
  }
  return placed;
}

interface AsidePlacement {
  readonly nodes: PlacedNode[];
  readonly height: number;
}

function placeAside(
  nodes: readonly ModelNode[],
  top: number,
  totalWidth: number,
): AsidePlacement {
  if (nodes.length === 0) return { nodes: [], height: 0 };
  const sorted = [...nodes].sort(compareNodes);
  const perRow = Math.max(1, Math.floor((totalWidth - MARGIN_X) / (CARD_W + GAP_X)));
  const placed: PlacedNode[] = sorted.map((n, i) => {
    const row = Math.floor(i / perRow);
    const col = i % perRow;
    return toPlacedNode(n, MARGIN_X + col * (CARD_W + GAP_X), top + HEADER_H + row * (CARD_H + GAP_Y));
  });
  const rows = Math.ceil(sorted.length / perRow);
  return { nodes: placed, height: HEADER_H + rows * (CARD_H + GAP_Y) };
}

function toPlacedNode(n: ModelNode, x: number, y: number): PlacedNode {
  return {
    id: n.id,
    idPath: n.idPath,
    type: n.type,
    label: n.label,
    axis: n.axis,
    laneKey: n.laneKey,
    hop: n.hop,
    degree: n.degree,
    hasMore: n.hasMore,
    x,
    y,
    w: CARD_W,
    h: CARD_H,
  };
}

/**
 * レーン流れ図の配置を計算する。**占有されているレーンだけ**列を作る
 * (`LANES`の並び順を保つ)。レーンに属さないノード(`assignLanes`が
 * `aside`を割った分)は最下部の脇のストリップに横に流し込む。
 */
export function layoutLanes(model: GraphModel, options: LaneLayoutOptions = {}): GraphLayoutResult {
  const maxPerLane = options.maxPerLane ?? DEFAULT_MAX_PER_LANE;
  const expandedLanes = options.expandedLanes ?? new Set<string>();

  const groups = new Map<string, ModelNode[]>();
  for (const n of model.nodes) {
    const arr = groups.get(n.laneKey);
    if (arr) arr.push(n);
    else groups.set(n.laneKey, [n]);
  }
  const asideNodes = groups.get(ASIDE_LANE.key) ?? [];

  const occupied: Lane[] = LANES.filter((l) => (groups.get(l.key)?.length ?? 0) > 0);

  const laneCount = Math.max(occupied.length, 1);
  const totalWidth = MARGIN_X * 2 + laneCount * CARD_W + (laneCount - 1) * GAP_X;

  const placedMain: PlacedNode[] = [];
  const bands: LaneBand[] = [];
  let maxStack = 1;

  occupied.forEach((lane, i) => {
    const all = groups.get(lane.key) ?? [];
    const sorted = [...all].sort(compareNodes);
    const showAll = expandedLanes.has(lane.key);
    const shown = showAll ? sorted : sorted.slice(0, maxPerLane);
    const x = MARGIN_X + i * (CARD_W + GAP_X);
    shown.forEach((n, j) => {
      placedMain.push(toPlacedNode(n, x, MARGIN_TOP + HEADER_H + j * (CARD_H + GAP_Y)));
    });
    maxStack = Math.max(maxStack, shown.length);
    bands.push({ key: lane.key, title: lane.title, x, w: CARD_W, count: all.length });
  });

  const mainHeight = MARGIN_TOP + HEADER_H + maxStack * (CARD_H + GAP_Y);
  const asidePlacement = placeAside(asideNodes, mainHeight + (asideNodes.length > 0 ? ASIDE_GAP_Y : 0), totalWidth);

  const allPlaced = [...placedMain, ...asidePlacement.nodes];
  const edges = buildPlacedEdges(allPlaced, model.edges);

  const height =
    asideNodes.length > 0
      ? mainHeight + ASIDE_GAP_Y + asidePlacement.height
      : mainHeight;

  return {
    nodes: allPlaced,
    edges,
    lanes: bands,
    width: totalWidth,
    height,
  };
}
