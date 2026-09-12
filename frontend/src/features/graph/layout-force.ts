// 「力学」配置(裁定B106のGraphViewProps外の内部部品)。レーン流れ図の代替
// 表示として、力学配置も提供する——ただし旧Sigma実装と同じ「毛玉」に
// 戻さないため、**同心円(中心からのホップ数)を初期位置にし、固定反復回数の
// 同期版ForceAtlas2で1回だけ計算する**。乱数は一切使わない
// (`Math.random()`を使わない。再発欠陥: 旧実装の展開時のジッタ)。
import { MultiUndirectedGraph } from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import type { GraphModel, ModelNode } from "./graph-model";
import { buildPlacedEdges, CARD_H, CARD_W } from "./layout-lanes";
import type { GraphLayoutResult, PlacedNode } from "./types";

export interface ForceLayoutOptions {
  /** 固定の反復回数(既定200)。多いほど安定するが、増減させても決定的であることは変わらない。 */
  readonly iterations?: number;
}

const DEFAULT_ITERATIONS = 200;
/** 初期の同心円配置(ホップ0=中心)の半径の単位。 */
const RING_RADIUS = 260;

function compareNodeIds(a: ModelNode, b: ModelNode): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/**
 * 力学配置(ForceAtlas2)の座標を計算する。**決定的**——初期位置(同心円。
 * 角度はid昇順で固定した並びから割る)・反復回数・設定のすべてに乱数を
 * 使わないので、同じ`GraphModel`を渡せば常に同じ`GraphLayoutResult`になる。
 *
 * レーン(`laneKey`)は色分け・絞り込みには使うが、位置には使わない
 * ——`lanes`は空配列を返す(レーンの列は描かない画面向けのモード)。
 */
export function layoutForce(model: GraphModel, options: ForceLayoutOptions = {}): GraphLayoutResult {
  const iterations = options.iterations ?? DEFAULT_ITERATIONS;

  const sortedNodes = [...model.nodes].sort(compareNodeIds);

  const byHop = new Map<number, ModelNode[]>();
  for (const n of sortedNodes) {
    const arr = byHop.get(n.hop);
    if (arr) arr.push(n);
    else byHop.set(n.hop, [n]);
  }

  const graph = new MultiUndirectedGraph();
  for (const [hop, arr] of [...byHop.entries()].sort((a, b) => a[0] - b[0])) {
    const r = hop * RING_RADIUS;
    arr.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / arr.length;
      graph.addNode(n.id, { x: r * Math.cos(angle), y: r * Math.sin(angle) });
    });
  }
  for (const e of model.edges) {
    if (!graph.hasNode(e.source) || !graph.hasNode(e.target)) continue;
    if (graph.hasEdge(e.key)) continue;
    graph.addEdgeWithKey(e.key, e.source, e.target);
  }

  // `forceAtlas2.inferSettings`はノード数から妥当な既定値を作る
  // (`gravity`を強くしすぎるとノード数の少ないグラフが1点に潰れて重なる
  // ——実ブラウザ確認で実際に踏んだ欠陥。手で決めた強い値を使わない)。
  // 絶対的な広さの調整は設定ではなく後段の倍率(下記)で行う。
  const settings = {
    ...forceAtlas2.inferSettings(graph),
    scalingRatio: 24,
    adjustSizes: false,
    barnesHutOptimize: false,
  };
  const rawPositions = forceAtlas2(graph, { iterations, settings });

  // ForceAtlas2の座標は物理シミュレーションの単位であり、カードの実寸(px)とは
  // 無関係——ノード数・設定によって全体の絶対的な大きさが大きく変わるため、
  // 固定の倍率では「ノードが少ないと1点に潰れる」「ノードが多いと逆に
  // 全体が広がりすぎて1枚1枚が点にしか見えない」の両方が起こる
  // (どちらも実ブラウザ確認で実際に踏んだ欠陥)。
  //
  // **最も近い2ノードの間隔がカード1枚分より少し広くなるよう、結果全体を
  // 一律の倍率で引き伸ばす。** 倍率をノード数に応じて動かすのではなく、
  // レイアウト自身の「最短距離」を基準にする——相対的な構造(誰が近いか)は
  // 変えず、絶対的な大きさだけをカードの実寸に合わせる。
  const ids = Object.keys(rawPositions);
  let minDist = Number.POSITIVE_INFINITY;
  for (let i = 0; i < ids.length; i += 1) {
    const pi = rawPositions[ids[i] as string];
    if (!pi) continue;
    for (let j = i + 1; j < ids.length; j += 1) {
      const pj = rawPositions[ids[j] as string];
      if (!pj) continue;
      const d = Math.hypot(pi.x - pj.x, pi.y - pj.y);
      if (d > 1e-9 && d < minDist) minDist = d;
    }
  }
  const TARGET_MIN_DIST = Math.max(CARD_W, CARD_H) * 1.4;
  const scale = Number.isFinite(minDist) && minDist > 0 ? TARGET_MIN_DIST / minDist : 1;

  const positions: Record<string, { x: number; y: number }> = {};
  for (const id of ids) {
    const p = rawPositions[id];
    if (!p) continue;
    positions[id] = { x: p.x * scale, y: p.y * scale };
  }

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const n of sortedNodes) {
    const p = positions[n.id];
    if (!p) continue;
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
  }
  if (!Number.isFinite(minX)) {
    minX = 0;
    maxX = 0;
    minY = 0;
    maxY = 0;
  }

  const margin = CARD_W;
  const nodes: PlacedNode[] = sortedNodes.map((n) => {
    const p = positions[n.id] ?? { x: 0, y: 0 };
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
      x: p.x - minX + margin - CARD_W / 2,
      y: p.y - minY + margin - CARD_H / 2,
      w: CARD_W,
      h: CARD_H,
    };
  });

  const edges = buildPlacedEdges(nodes, model.edges);

  return {
    nodes,
    edges,
    lanes: [],
    width: maxX - minX + margin * 2,
    height: maxY - minY + margin * 2,
  };
}
