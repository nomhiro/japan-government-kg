// 検索結果を「1枚のグラフ」に畳む(裁定B109)。
//
// **なぜ一覧をやめるか**(利用者の言葉):
//   検索した後に一覧がでるのではなくて、検索で引っかかった情報をGraph表示した
//   ほうがいい。ただの一覧表示が微妙。全体を俯瞰してみたいのに、一つの情報の
//   関連性しか見れない。
//
// 一覧は「20件の名前」を返すだけで、**ヒットどうしの関係**を何も言わない。
// 「年金」で引いた20件が同じ府省の所管なのか、同じ法令を根拠にしているのか、
// 同じ法人に払っているのかは、一覧からは分からない。
//
// **やり方**: 各ヒットの深さ1の近傍(既存の `/neighborhood`)を並列に取り、
// 合算してから**連結に寄与しうるノードだけ**を残す。
//
// **なぜ絞るのか(実測)**: 生の合算は各事業の内部記録に埋もれる。
// 本番で測った合算後のノード数と、絞り込み後の数:
//
// | 検索語 | ヒット | 合算 | 絞り込み後 | 辺 | 最大連結成分 |
// |---|---|---|---|---|---|
// | 年金 | 20 | 85 | 34 | 26 | 21ノードにヒット11件 |
// | こども | 20 | 191 | 34 | 29 | 24ノードにヒット13件 |
// | デジタル | 20 | 207 | 32 | 20 | 8ノードにヒット4件 |
// | 防衛 | 20 | 115 | 22 | 15 | 11ノードにヒット9件 |
//
// **落としているのは「2つのヒットを繋ぎえないノード」だけである。**
// `AnnualBudget`・`Expenditure`・`ExpenditureBlock`・`IndirectCost` は
// いずれも**ちょうど1つの事業に属する**(オントロジー上そう定義されている)。
// だから2件のヒットを繋ぐ経路には原理的に現れない ——
// 俯瞰の情報を捨てているのではなく、俯瞰に寄与しえないものを外している。
// それでも**落とした件数は画面に出す**(黙って減らさない。裁定B82)。
import type { GraphEdge, NeighborhoodResponse, SearchHit } from "../../api/client";
import { mergeRawGraphs, rawGraphFromNeighborhood, type RawGraph } from "../graph/graph-model";

/**
 * **ヒットどうしを繋ぎうる型。** ここに挙げた型は複数の事業・法令から
 * 参照されうるので、合算グラフの連結に寄与する。
 *
 * 逆に挙げていない型(年度予算・支出・支出先ブロック・間接経費)は
 * 1つの事業に属するので、2件のヒットの間に立つことがない。
 */
export const CONNECTING_TYPES: ReadonlySet<string> = new Set([
  "Ministry",
  "GovernmentOrgan",
  "AbolishedGovernmentOrgan",
  "Organization",
  "Law",
  "LawRevision",
  "BudgetProject",
  // 未解決参照は「特定できなかった根拠」であり、同じ文字列が複数の事業から
  // 参照される(実データで確認済み)。繋ぎうるので残す。
  "UnresolvedReference",
]);

/** 2件以上のヒットに隣接していれば、型に関わらず残す閾値。 */
const CONNECTOR_MIN_HITS = 2;

export interface SearchGraph {
  readonly raw: RawGraph;
  /** 検索でヒットしたノードのid(強調して描く)。 */
  readonly hitIds: ReadonlySet<string>;
  /** 辺を1本以上持つヒットのid。 */
  readonly connectedHitIds: ReadonlySet<string>;
  /** 辺を1本も持たないヒットのid(KGに関係の記録が無いもの)。 */
  readonly isolatedHitIds: ReadonlySet<string>;
  /** 絞り込みで外したノードの数(画面に出す)。 */
  readonly droppedNodeCount: number;
  readonly fanoutTruncatedIds: ReadonlySet<string>;
  /** どれかの近傍取得が打ち切られたか。 */
  readonly nodesTruncated: boolean;
  readonly edgesTruncated: boolean;
  /** 近傍を取れなかったヒットの数(404・通信失敗)。 */
  readonly missingNeighborhoodCount: number;
  /** ホップ数の起点(力学配置の初期位置にしか効かない)。 */
  readonly centerId: string;
}

/**
 * ヒットと、その近傍応答から合算グラフを作る。
 *
 * `neighborhoods` は `hits` と**同じ順・同じ長さ**で渡す(取れなかったものは
 * `null`)。順序で対応させるのは、呼び出し側が `Promise.all` の結果を
 * そのまま渡せるようにするため。
 */
export function buildSearchGraph(params: {
  readonly hits: readonly SearchHit[];
  readonly neighborhoods: readonly (NeighborhoodResponse | null)[];
}): SearchGraph | null {
  const { hits, neighborhoods } = params;
  if (hits.length === 0) return null;

  const hitIds = new Set(hits.map((h) => h.id));
  const parts: RawGraph[] = [];
  const fanoutTruncatedIds = new Set<string>();
  let nodesTruncated = false;
  let edgesTruncated = false;
  let missingNeighborhoodCount = 0;

  // ヒット自身は必ずノードとして入れる(近傍が取れなくても結果から消さない)。
  parts.push({ nodes: hits, edges: [] });

  for (const nbhd of neighborhoods) {
    if (!nbhd) {
      missingNeighborhoodCount += 1;
      continue;
    }
    parts.push(rawGraphFromNeighborhood(nbhd));
    for (const id of nbhd.fanout_truncated_nodes) fanoutTruncatedIds.add(id);
    nodesTruncated = nodesTruncated || nbhd.nodes_truncated;
    edgesTruncated = edgesTruncated || nbhd.edges_truncated;
  }

  const merged = mergeRawGraphs(parts);

  // どのヒットに隣接しているかを数える(型で残す判定より先に要る)。
  const adjacentHits = new Map<string, Set<string>>();
  for (const e of merged.edges) {
    if (hitIds.has(e.source)) addTo(adjacentHits, e.target, e.source);
    if (hitIds.has(e.target)) addTo(adjacentHits, e.source, e.target);
  }

  const keep = new Set<string>(hitIds);
  for (const n of merged.nodes) {
    if (CONNECTING_TYPES.has(n.type)) keep.add(n.id);
    else if ((adjacentHits.get(n.id)?.size ?? 0) >= CONNECTOR_MIN_HITS) keep.add(n.id);
  }

  const nodes = merged.nodes.filter((n) => keep.has(n.id));
  const edges: GraphEdge[] = merged.edges.filter((e) => keep.has(e.source) && keep.has(e.target));

  const withEdges = new Set<string>();
  for (const e of edges) {
    withEdges.add(e.source);
    withEdges.add(e.target);
  }
  const connectedHitIds = new Set<string>();
  const isolatedHitIds = new Set<string>();
  for (const id of hitIds) {
    if (withEdges.has(id)) connectedHitIds.add(id);
    else isolatedHitIds.add(id);
  }

  return {
    raw: { nodes, edges },
    hitIds,
    connectedHitIds,
    isolatedHitIds,
    droppedNodeCount: merged.nodes.length - nodes.length,
    // 残したノードに対する打ち切り印だけを渡す(外したノードの印は意味を持たない)。
    fanoutTruncatedIds: new Set([...fanoutTruncatedIds].filter((id) => keep.has(id))),
    nodesTruncated,
    edgesTruncated,
    missingNeighborhoodCount,
    centerId: hits[0]!.id,
  };
}

function addTo(map: Map<string, Set<string>>, key: string, value: string): void {
  const cur = map.get(key);
  if (cur) cur.add(value);
  else map.set(key, new Set([value]));
}
