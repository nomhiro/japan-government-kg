// 展開(ノードを起点に隣接を追加取得する)が実際に追加するノード・辺を決める
// 純粋関数。**`graph.ts`から分離してある理由**: `graph.ts`は`sigma`を
// importするが、`sigma`はモジュール読み込み時に`WebGL2RenderingContext`
// (ブラウザのグローバル)を参照するため、vitest(Node環境。jsdom未導入。
// D-5の方針)から`graph.ts`をimportすると即座に例外になる。この不変条件
// (欠陥型10・裁定B77のダングリングエッジ防止)はDOM/Sigmaに依存しない
// 純粋な計算なので、依存を持たないこのファイルに置くことでテスト可能にする。
import type { EntityDetailResponse, EntityRef } from "../api/client";

export interface ExpansionPlan {
  newNodes: EntityRef[];
  edges: Array<{ source: string; target: string; predicate: string; graph: string }>;
}

/**
 * **返す`edges`のsource/targetは必ず`existingNodeIds`∪`newNodes`のいずれかに
 * 含まれる**(欠陥型10・裁定B77のダングリングエッジと同じ不変条件を、
 * 表示側の「展開」でも守る)。
 *
 * `fromNodeId`は呼び出し前提として既にグラフに存在する(展開はクリック済みの
 * ノードを起点にしか起こらない)——`existingNodeIds`に含まれていることを
 * 呼び出し側が保証する。
 */
export function planExpansion(
  fromNodeId: string,
  rels: EntityDetailResponse["relationships"][string],
  existingNodeIds: ReadonlySet<string>,
): ExpansionPlan {
  const seen = new Set(existingNodeIds);
  const newNodes: EntityRef[] = [];
  const edges: ExpansionPlan["edges"] = [];
  for (const rel of rels) {
    if (!seen.has(rel.related.id)) {
      newNodes.push(rel.related);
      seen.add(rel.related.id);
    }
    const [source, target] =
      rel.direction === "outgoing" ? [fromNodeId, rel.related.id] : [rel.related.id, fromNodeId];
    edges.push({ source, target, predicate: rel.predicate, graph: rel.graph });
  }
  return { newNodes, edges };
}

/**
 * **状態行に出す件数を、いま画面にあるグラフから数える(裁定B93)。**
 *
 * 展開の直後に状態行を更新し忘れると、
 * **表示が現在のグラフについて偽を主張する** ——
 * controllerが実ブラウザで踏んだ:
 * 厚生労働省の予算事業50件を展開した後も
 * 「ノード27件・辺25件。1件のノードで分岐数の上限に達しています」と
 * 出たままだった(グラフは実際には77件になり、その上限ももう当てはまらない)。
 * このプロジェクトの再発欠陥6(表示が偽を主張する)である。
 *
 * `nodesTruncated`/`edgesTruncated` は**最初の取得**についての事実なので
 * そのまま持ち回る(展開してもその取得が打ち切られた事実は変わらない)。
 * **件数と分岐上限の残件だけがグラフから導出される。**
 */
export function liveGraphCounts(
  nodeFanoutFlags: readonly boolean[],
  edgeCount: number,
): { nodeCount: number; edgeCount: number; fanoutTruncatedCount: number } {
  return {
    nodeCount: nodeFanoutFlags.length,
    edgeCount,
    fanoutTruncatedCount: nodeFanoutFlags.filter((f) => f).length,
  };
}
