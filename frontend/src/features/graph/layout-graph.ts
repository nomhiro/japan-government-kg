// 「構造」配置(裁定B112)。**位置をグラフの構造そのものから決める。**
//
// **なぜ要るか(利用者の言葉)**:
//   今のこういう列が決まった描画ではなく、もっとグラフ構造をそのまま表現した
//   ほうがいいのでは? Graph構造をレンダリングできるモジュール?ライブラリ?
//   あるでしょ。
//
// レーン配置(`layout-lanes.ts`)は**型で列を決める**(根拠→所管→事業→…)。
// 1つの事業の資金の流れを見るときはそれが意味そのものなので正しい。だが
// 検索結果のような集合では、列の中の並び順が辺と無関係(次数と名前順)なので
// **辺が最大限に交差する** —— 「AI」の検索では所管12件と事業20件のあいだが
// 交差する曲線の束になっていた(利用者が送ってきた画面)。
//
// ここでは層も並び順も**辺から**決める。使うのは dagre
// (`@dagrejs/dagre`)で、Sugiyama法の実装 ——
//   1. 層を辺の向きから決める(network simplex)
//   2. 層の中の並びを**交差が減るように**入れ替える
//   3. 辺の経路点を返す(ノードを避けて通る)
// **描画は自前のSVGのまま**である。必要なのは座標であって描画ではない
// ——カードのラベル常時表示・キーボード操作・「すべての関係を表で」・
// ダーク対応は既にあるものを使う(裁定B106でSigma.jsを外した理由)。
//
// **決定的であること**: ノードと辺を**id順に挿入する**。dagreの既定の
// ランカー(network-simplex)と交差削減は乱数を使わないので、挿入順を
// 固定すれば同じ`GraphModel`から常に同じ座標が出る
// (`scripts/check-frontend-build.py` が2回ビルドのsha256一致を要求する
// のと同じ規律を、実行時の描画にも当てる)。
import dagre from "@dagrejs/dagre";
import type { GraphModel, ModelEdge } from "./graph-model";
import { CARD_H, CARD_W } from "./layout-lanes";
import type { GraphLayoutResult, PlacedEdge, PlacedNode } from "./types";

/** 層の間隔(横)。カード幅より広く取らないと辺のラベルが読めない。 */
const RANK_SEP = 120;
/** 同じ層の中のカードの間隔(縦)。 */
const NODE_SEP = 16;
/** 層の中で辺が通る隙間。dagreが仮ノードを置くのに使う。 */
const EDGE_SEP = 10;
const MARGIN = 24;

export interface GraphLayoutOptions {
  /** 流れの向き。既定は左から右(日本語の読み方向に合わせる)。 */
  readonly rankdir?: "LR" | "TB";
}

function compareById(a: { id: string }, b: { id: string }): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function compareEdges(a: ModelEdge, b: ModelEdge): number {
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

/**
 * 経路点(dagreが返す折れ線)を滑らかなパスにする。
 *
 * **折れ線のままにしない**: 角が立つと辺が折り返して見え、どこから
 * どこへ向かっているのか読みにくい。中間点を通る二次ベジェで丸める
 * (点が2つ以下なら直線)。
 */
export function pathThroughPoints(points: readonly { x: number; y: number }[]): string {
  if (points.length === 0) return "";
  const [first, ...rest] = points;
  if (rest.length === 0) return `M ${round(first!.x)} ${round(first!.y)}`;
  if (rest.length === 1) {
    return `M ${round(first!.x)} ${round(first!.y)} L ${round(rest[0]!.x)} ${round(rest[0]!.y)}`;
  }
  let d = `M ${round(first!.x)} ${round(first!.y)}`;
  for (let i = 0; i < rest.length - 1; i += 1) {
    const p = rest[i]!;
    const next = rest[i + 1]!;
    const midX = (p.x + next.x) / 2;
    const midY = (p.y + next.y) / 2;
    d += ` Q ${round(p.x)} ${round(p.y)}, ${round(midX)} ${round(midY)}`;
  }
  const last = rest[rest.length - 1]!;
  d += ` L ${round(last.x)} ${round(last.y)}`;
  return d;
}

/** 座標は小数第1位までにする(SVGの`d`が無駄に長くなるのを防ぐ)。 */
function round(n: number): number {
  return Math.round(n * 10) / 10;
}

/**
 * 構造から座標を決める。`lanes`は空 —— 型で決めた列を**出さない**のが
 * この配置の主旨である。
 */
export function layoutGraph(model: GraphModel, options: GraphLayoutOptions = {}): GraphLayoutResult {
  const g = new dagre.graphlib.Graph({ directed: true, multigraph: true, compound: false });
  g.setGraph({
    rankdir: options.rankdir ?? "LR",
    nodesep: NODE_SEP,
    edgesep: EDGE_SEP,
    ranksep: RANK_SEP,
    marginx: MARGIN,
    marginy: MARGIN,
  });
  g.setDefaultEdgeLabel(() => ({}));

  // **id順に挿入する**(決定性。上のdocstring参照)。
  const nodes = [...model.nodes].sort(compareById);
  for (const n of nodes) {
    g.setNode(n.id, { width: CARD_W, height: CARD_H });
  }
  const edges = [...model.edges].sort(compareEdges);
  for (const e of edges) {
    if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
    // **自己ループは層の計算に入れない。** dagreは扱えるが、ランクを1つ
    // 消費して図が横に伸びるだけで、読み手に何も足さない。
    if (e.source === e.target) continue;
    // `name`に辺の鍵を渡して**多重辺を保つ**(同じ2点を結ぶ別の述語がある)。
    g.setEdge(e.source, e.target, {}, e.key);
  }

  dagre.layout(g);

  const placedById = new Map<string, PlacedNode>();
  const placedNodes: PlacedNode[] = [];
  for (const n of nodes) {
    const laid = g.node(n.id) as { x: number; y: number } | undefined;
    // dagreは**中心**座標を返す。`PlacedNode`は左上(描画側が
    // `translate(x,y)`してから0,0にrectを描く)。
    const x = laid ? round(laid.x - CARD_W / 2) : MARGIN;
    const y = laid ? round(laid.y - CARD_H / 2) : MARGIN;
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
      x,
      y,
      w: CARD_W,
      h: CARD_H,
    };
    placedNodes.push(placed);
    placedById.set(n.id, placed);
  }

  const placedEdges: PlacedEdge[] = [];
  for (const e of edges) {
    const s = placedById.get(e.source);
    const t = placedById.get(e.target);
    if (!s || !t) continue;
    if (e.source === e.target) continue;
    const laid = g.edge(e.source, e.target, e.key) as
      | { points?: { x: number; y: number }[] }
      | undefined;
    const points = laid?.points ?? [];
    const d =
      points.length >= 2
        ? pathThroughPoints(points)
        : // 経路点が無い(dagreが辺を落とした)ときは、素直に中心を結ぶ。
          // **黙って辺を消さない**——辺が無いように見えるのは嘘である。
          `M ${round(s.x + s.w)} ${round(s.y + s.h / 2)} L ${round(t.x)} ${round(t.y + t.h / 2)}`;
    placedEdges.push({
      key: e.key,
      source: e.source,
      target: e.target,
      predicate: e.predicate,
      graph: e.graph,
      d,
      // 経路は常に source から target へ引くので、矢印の反転は要らない。
      flip: false,
    });
  }

  const graphSize = g.graph() as { width?: number; height?: number };
  return {
    nodes: placedNodes,
    edges: placedEdges,
    lanes: [],
    width: Math.max(1, Math.round(graphSize.width ?? 1)),
    height: Math.max(1, Math.round(graphSize.height ?? 1)),
  };
}
