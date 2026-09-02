// 近傍サブグラフの描画。グラフ描画にはSigma.js(WebGL)を使う(仕様§9.2:
// 「Phase 1の規模では性能問題は出ないが、Phase 2以降の拡大を見込んで最初から
// WebGL系を選ぶ」)。
import { MultiGraph } from "graphology";
import Sigma from "sigma";
import type { EntityDetailResponse, EntityRef, NeighborhoodResponse, Provenance } from "../api/client";
import { entityDetail, neighborhood } from "../api/client";
import { NEIGHBORHOOD_DEPTH } from "../api/limits";
import { esc, provenanceHtml } from "../format";
import { predicateLabel, typeLabel } from "../labels";
import { navigate } from "../router";

// 型ごとの色。**オントロジーに「色」という概念は無い**ので、これは表示だけの
// 判断であり導出できない——出現順に固定パレットから割り当てる(型が増えても
// 色の割り当てルール自体は変えなくていい。ハブ以外は型の種類が少ないので
// 衝突は実用上問題にならない)。
const PALETTE = [
  "#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed",
  "#0891b2", "#db2777", "#65a30d", "#4b5563", "#ea580c",
];

/**
 * ノードの座標を決める。**厳密なフォースレイアウトは入れない**
 * (依存を増やさない・Phase 1の規模〔多くて数百ノード〕では見やすさの差が
 * 小さい)——中心からのホップ数で同心円に配置する簡単な方式で足りる。
 */
function layout(graph: MultiGraph, centerId: string): void {
  const byHop = new Map<string, number>([[centerId, 0]]);
  const queue: string[] = [centerId];
  while (queue.length > 0) {
    const cur = queue.shift()!;
    const hop = byHop.get(cur)!;
    graph.forEachNeighbor(cur, (n) => {
      if (!byHop.has(n)) {
        byHop.set(n, hop + 1);
        queue.push(n);
      }
    });
  }

  const groups = new Map<number, string[]>();
  for (const [id, hop] of byHop) {
    (groups.get(hop) ?? groups.set(hop, []).get(hop)!).push(id);
  }
  for (const [hop, ids] of groups) {
    if (hop === 0) {
      graph.setNodeAttribute(ids[0]!, "x", 0);
      graph.setNodeAttribute(ids[0]!, "y", 0);
      continue;
    }
    const radius = hop * 6;
    ids.forEach((id, i) => {
      const angle = (2 * Math.PI * i) / ids.length;
      graph.setNodeAttribute(id, "x", radius * Math.cos(angle));
      graph.setNodeAttribute(id, "y", radius * Math.sin(angle));
    });
  }
}

export interface GraphController {
  destroy(): void;
}

export function renderNeighborhoodGraph(container: HTMLElement, center: EntityRef): GraphController {
  // **このビュー(1エンティティの表示)専用のスコープにする。** 以前は
  // モジュールスコープ(全画面で共有)に置いていたため、別のエンティティへ
  // 遷移した後も前の画面で見た型の色が凡例に残る欠陥があった(実データで
  // 発見: 厚生労働省の近傍を見た後に厚生省を見ると、凡例に厚生省の近傍には
  // 実在しない「予算事業」が残った)。エンティティごとに`renderNeighborhoodGraph`
  // が呼ばれるたびにこのMapを作り直すことで、凡例が常に「いま表示している
  // グラフに実在する型」だけを反映する(深さ1→2の再読み込みや、分岐の
  // 展開では同じMapを使い続けるので、その範囲では色は変わらない)。
  const typeColorCache = new Map<string, string>();
  function colorForType(type: string): string {
    let c = typeColorCache.get(type);
    if (!c) {
      c = PALETTE[typeColorCache.size % PALETTE.length]!;
      typeColorCache.set(type, c);
    }
    return c;
  }
  function addEntityNode(
    graph: MultiGraph,
    ref: EntityRef,
    opts: { isCenter?: boolean; fanoutTruncated?: boolean } = {},
  ): void {
    if (graph.hasNode(ref.id)) return;
    graph.addNode(ref.id, {
      label: `${ref.label ?? "(表示名なし)"}${opts.fanoutTruncated ? " ⋯" : ""}`,
      size: opts.isCenter ? 12 : 7,
      color: colorForType(ref.type),
      idPath: ref.id_path,
      entityType: ref.type,
      fanoutTruncated: Boolean(opts.fanoutTruncated),
    });
  }

  container.innerHTML = `
    <div class="jgkg-graph-toolbar">
      <label>深さ
        <select class="jgkg-depth-select"></select>
      </label>
      <span class="jgkg-muted jgkg-graph-status"></span>
    </div>
    <p class="jgkg-notice">
      改正記録(法令の改正版)はナレッジグラフ上で辺を1本も持たないため、
      近傍にはここには表示されません(法令IDという文字列だけで結びついています)。
    </p>
    <div class="jgkg-graph-canvas"></div>
    <div class="jgkg-graph-legend"></div>
    <div class="jgkg-graph-detail"></div>
  `;

  const depthSelect = container.querySelector<HTMLSelectElement>(".jgkg-depth-select")!;
  const status = container.querySelector<HTMLElement>(".jgkg-graph-status")!;
  const canvas = container.querySelector<HTMLElement>(".jgkg-graph-canvas")!;
  const legend = container.querySelector<HTMLElement>(".jgkg-graph-legend")!;
  const detail = container.querySelector<HTMLElement>(".jgkg-graph-detail")!;

  for (let d = NEIGHBORHOOD_DEPTH.min; d <= NEIGHBORHOOD_DEPTH.max; d++) {
    const opt = document.createElement("option");
    opt.value = String(d);
    opt.textContent = d === 1 ? "1(既定・速い)" : `${d}(逐次クエリが増え、数秒かかることがあります)`;
    depthSelect.appendChild(opt);
  }
  // **UIの既定は深さ1に固定する(APIの既定値とは独立な、表示側の判断)。**
  // D-5ブリーフの実測: 深さ2は逐次クエリ18本で約1.1秒かかり、「展開」直後に
  // 何も出ない時間がある。範囲の下限(常に1。仕様§9.1「深さ1-2」)を使うことで、
  // 将来APIの許容範囲が変わっても選択肢の外に出ない。
  depthSelect.value = String(NEIGHBORHOOD_DEPTH.min);

  let sigma: Sigma | undefined;
  let destroyed = false;
  let graphs: Record<string, Provenance> = {};

  function destroySigma(): void {
    sigma?.kill();
    sigma = undefined;
  }

  async function load(depth: number): Promise<void> {
    status.textContent = depth >= 2 ? "読み込み中…(深さ2は数秒かかることがあります)" : "読み込み中…";
    detail.innerHTML = "";
    let res: NeighborhoodResponse | null;
    try {
      res = await neighborhood(center.id_path, { depth });
    } catch (e) {
      if (destroyed) return;
      status.textContent = `読み込みに失敗しました: ${String(e)}`;
      return;
    }
    if (destroyed) return;
    if (!res) {
      status.textContent = "このエンティティは見つかりませんでした。";
      return;
    }
    graphs = res.graphs;
    buildAndRender(res);
  }

  function buildAndRender(res: NeighborhoodResponse): void {
    const graph = new MultiGraph();
    addEntityNode(graph, res.center, { isCenter: true });
    for (const n of res.nodes) {
      addEntityNode(graph, n, { fanoutTruncated: res.fanout_truncated_nodes.includes(n.id) });
    }
    // **B77の不変条件に依拠する。** 近傍サブグラフのすべての辺のsource/target
    // はnodesに存在することがAPI側で検査済み(裁定B77)——ダングリングエッジの
    // 防御コード(存在確認してから追加、等)は意図的に書かない。もし壊れて
    // いれば、それはAPI側の欠陥なのでここは素直に例外で落ちてよい。
    for (const e of res.edges) {
      graph.addEdge(e.source, e.target, {
        label: predicateLabel(e.predicate),
        color: "#9ca3af",
        size: 1.5,
        graphKey: e.graph,
      });
    }
    layout(graph, res.center.id);

    destroySigma();
    canvas.innerHTML = "";
    sigma = new Sigma(graph, canvas, {
      renderEdgeLabels: false,
      labelRenderedSizeThreshold: 0,
    });

    sigma.on("clickNode", ({ node }) => {
      const attrs = graph.getNodeAttributes(node);
      if (attrs.fanoutTruncated) {
        void showExpandPanel(node, attrs.idPath as string, attrs.entityType as string);
        return;
      }
      navigate({ name: "entity", idPath: attrs.idPath as string });
    });
    sigma.on("clickEdge", ({ edge }) => {
      const attrs = graph.getEdgeAttributes(edge);
      const prov = graphs[attrs.graphKey as string];
      detail.innerHTML = `<p>${provenanceHtml(prov)}</p>`;
    });

    const fanoutCount = res.fanout_truncated_nodes.length;
    status.textContent =
      `ノード${res.nodes.length + 1}件・辺${res.edges.length}件` +
      (res.nodes_truncated ? "(ノード数の上限で一部を省略)" : "") +
      (res.edges_truncated ? "(エッジ数の上限で一部を省略)" : "") +
      (fanoutCount > 0 ? `。${fanoutCount}件のノードで分岐数の上限に達しています(⋯マーク。クリックで続きを見られます)` : "");

    legend.innerHTML = Array.from(typeColorCache.entries())
      .map(([type, color]) => `<span class="jgkg-legend-item"><span class="jgkg-legend-dot" style="background:${color}"></span>${esc(typeLabel(type))}</span>`)
      .join("");
  }

  /**
   * 分岐数の上限で隣接が切られたノードを、述語を選んで展開する(裁定B74)。
   *
   * APIに新しい引数(述語フィルタ等)は無い——`/entity/{id_path}`が既に
   * 返す「型別にグループ化された関係一覧」を取得し、利用者が選んだ
   * グループをこのグラフへ手元でマージするだけで実現する(表示側の
   * 判断であり、API変更は不要という裁定B74の要求どおり)。
   */
  async function showExpandPanel(nodeId: string, idPath: string, _type: string): Promise<void> {
    detail.innerHTML = '<p class="jgkg-muted">この先を確認しています…</p>';
    let entity: EntityDetailResponse | null;
    try {
      entity = await entityDetail(idPath);
    } catch (e) {
      detail.innerHTML = `<p class="jgkg-error">取得に失敗しました: ${String(e)}</p>`;
      return;
    }
    if (!entity) {
      detail.innerHTML = '<p class="jgkg-muted">このエンティティは見つかりませんでした。</p>';
      return;
    }
    const groupNames = Object.keys(entity.relationships);
    if (groupNames.length === 0) {
      detail.innerHTML = '<p class="jgkg-muted">展開できる関係がありませんでした。</p>';
      return;
    }
    const buttons = groupNames
      .map(
        (g) =>
          `<button type="button" class="jgkg-expand-group" data-group="${esc(g)}">${esc(typeLabel(g))}(${entity!.relationships[g]!.length}件)を表示</button>`,
      )
      .join(" ");
    detail.innerHTML = `<p>この先には次の型のノードがあります。表示する型を選んでください:</p><p>${buttons}</p>`;
    detail.querySelectorAll<HTMLButtonElement>(".jgkg-expand-group").forEach((btn) => {
      btn.addEventListener("click", () => {
        mergeRelationshipsIntoGraph(nodeId, entity!.relationships[btn.dataset.group!]!, entity!.graphs);
      });
    });
  }

  function mergeRelationshipsIntoGraph(
    fromNodeId: string,
    rels: EntityDetailResponse["relationships"][string],
    provGraphs: Record<string, Provenance>,
  ): void {
    if (!sigma) return;
    const graph = sigma.getGraph() as MultiGraph;
    graphs = { ...graphs, ...provGraphs };
    for (const rel of rels) {
      addEntityNode(graph, rel.related);
      const [source, target] = rel.direction === "outgoing" ? [fromNodeId, rel.related.id] : [rel.related.id, fromNodeId];
      graph.addEdge(source, target, {
        label: predicateLabel(rel.predicate),
        color: "#9ca3af",
        size: 1.5,
        graphKey: rel.graph,
      });
      if (!graph.hasNodeAttribute(rel.related.id, "x")) {
        const base = graph.getNodeAttributes(fromNodeId);
        const jitter = (Math.random() - 0.5) * 4;
        graph.setNodeAttribute(rel.related.id, "x", (base.x as number) + jitter + 4);
        graph.setNodeAttribute(rel.related.id, "y", (base.y as number) + jitter);
      }
    }
    graph.setNodeAttribute(fromNodeId, "fanoutTruncated", false);
    graph.setNodeAttribute(
      fromNodeId,
      "label",
      String(graph.getNodeAttribute(fromNodeId, "label")).replace(/ ⋯$/, ""),
    );
    detail.innerHTML = "";
  }

  depthSelect.addEventListener("change", () => {
    void load(Number(depthSelect.value));
  });
  void load(Number(depthSelect.value));

  return {
    destroy(): void {
      destroyed = true;
      destroySigma();
    },
  };
}
