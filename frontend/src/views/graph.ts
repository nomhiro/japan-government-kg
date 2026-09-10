// 近傍サブグラフの描画。グラフ描画にはSigma.js(WebGL)を使う(仕様§9.2:
// 「Phase 1の規模では性能問題は出ないが、Phase 2以降の拡大を見込んで最初から
// WebGL系を選ぶ」)。
//
// **グラフを画面の主役にする(裁定B92のE-1)。** ノードの色・凡例はオントロジー
// の6軸(誰が/何を/どこで/いつ/いくらで/何について)+UnresolvedReferenceから
// 導出する(`../graph-colors.ts`。型→軸の対応自体は`../labels.ts`の
// `axisForType`が生成物`generated/labels.json`の`typeAxes`——
// `frontend_labels.py`が`rdfs:subClassOf`を辿って生成——から引く。対応表を
// ここで手書きしない)。ノードをクリックしても画面を移動せず、その場に
// 概要(型・軸・属性・出典)を出す——移動は明示的なリンクとして残す。
import { MultiGraph } from "graphology";
import Sigma from "sigma";
import type { EntityDetailResponse, EntityRef, NeighborhoodResponse, Provenance } from "../api/client";
import { entityDetail, neighborhood } from "../api/client";
import { NEIGHBORHOOD_DEPTH } from "../api/limits";
import { attributeValueHtml, esc, neighborhoodStatusText, provenanceHtml } from "../format";
import { colorForType, groupByAxis, UNKNOWN_AXIS } from "../graph-colors";
import { axisForType, predicateLabel, typeLabel } from "../labels";
import { navigate } from "../router";
import { planExpansion } from "./graph-merge";

/**
 * 辺の太さ(ピクセル)。**見た目だけの値ではない。**
 *
 * 元の値(1.5)では`clickEdge`が実質的に一度も発火しなかった——Sigma.jsの
 * 辺クリック判定(`getEdgeAtPoint`)はダウンサンプリングした専用のpicking
 * バッファ(`pickingDownSizingRatio`。既定で devicePixelRatio の2倍)で
 * 色を読むため、1.5px幅の線はその解像度に対して細すぎて picking バッファ上に
 * 一切乗らない(実ブラウザで`sigma.getEdgeAtPoint(x, y)`を直接呼んで実測:
 * 1.5でもenableEdgeEvents:trueにしても常にnullで、3以上で確実にヒットする
 * ようになった)。3にしても見た目の太さはさほど変わらない。
 */
const EDGE_SIZE = 3;

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
  function addEntityNode(
    graph: MultiGraph,
    ref: EntityRef,
    opts: { isCenter?: boolean; fanoutTruncated?: boolean; x?: number; y?: number } = {},
  ): void {
    if (graph.hasNode(ref.id)) return;
    // **x/yを必ずこの1回の`addNode`呼び出しに含める。** Sigmaは既に
    // バインド済みのgraphologyグラフへの`addNode`を同期的に見ており、
    // その時点でx/yが数値でないと例外を投げる(「could not find a valid
    // position (x, y)」。実ブラウザで実際に踏んだ——展開〔`mergeRelationshipsIntoGraph`〕
    // がノード追加→辺追加→x/y設定の順で書いていたため、初回読み込みでは
    // Sigma構築前に`layout()`がx/yを上書きするので隠れていたが、展開時は
    // Sigmaが既に動いているグラフに対して行うため露見した)。位置が未定の
    // 呼び出し側(初回読み込み。後で`layout()`が上書きする)は既定の0,0で足りる。
    graph.addNode(ref.id, {
      label: `${ref.label ?? "(表示名なし)"}${opts.fanoutTruncated ? " ⋯" : ""}`,
      size: opts.isCenter ? 12 : 7,
      color: colorForType(ref.type),
      idPath: ref.id_path,
      entityType: ref.type,
      fanoutTruncated: Boolean(opts.fanoutTruncated),
      x: opts.x ?? 0,
      y: opts.y ?? 0,
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
  // ノード詳細パネルの非同期取得が、後から来た別のクリックの結果を
  // 上書きしないためのガード(`showNodeDetail`参照)。
  let detailRequestId = 0;

  function destroySigma(): void {
    sigma?.kill();
    sigma = undefined;
  }

  /**
   * 凡例を軸ごとにまとめて描く(裁定B92)。**いま実際にグラフ上にある型
   * だけ**を対象にする(オントロジー全体の6軸を無条件に列挙して埋めない
   * ——このグラフに実在しない型を凡例に出すと、以前実データで踏んだ
   * 「凡例が別画面/存在しない型を持ち越す」欠陥の逆向きの誤りになる)。
   * ノードの色は`colorForType`(グラフのノード自体と同じ関数)で決めるので、
   * 凡例の色とノードの色は常に一致する。
   */
  function renderLegend(): void {
    if (!sigma) return;
    const graph = sigma.getGraph();
    const presentTypes: string[] = [];
    graph.forEachNode((_, attrs) => presentTypes.push(attrs.entityType as string));
    const groups = groupByAxis(presentTypes, axisForType, colorForType);
    legend.innerHTML = groups
      .map((g) => {
        const axisLabel = g.axis === UNKNOWN_AXIS ? "軸不明" : typeLabel(g.axis);
        const items = g.items
          .map(
            (it) =>
              `<span class="jgkg-legend-item"><span class="jgkg-legend-dot" style="background:${it.color}"></span>${esc(typeLabel(it.type))}</span>`,
          )
          .join("");
        return `<div class="jgkg-legend-group"><span class="jgkg-legend-axis">${esc(axisLabel)}</span>${items}</div>`;
      })
      .join("");
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
    // **中心ノード自身が分岐数の上限に達していることがある**(実データで確認:
    // `org/6000012070001`=厚生労働省。予算事業50件超のハブで、深さ1でも
    // `fanout_truncated_nodes`に中心のIDが入る)。中心を無条件に
    // `fanoutTruncated: false`で追加すると、その事実(⋯マーク・展開ボタン)が
    // 中心ノードだけ黙って消える——欠陥型10(裁定B77)と同じ「打ち切りが
    // 黙って消える」の再発になるため、他のノードと同じ判定を通す。
    addEntityNode(graph, res.center, {
      isCenter: true,
      fanoutTruncated: res.fanout_truncated_nodes.includes(res.center.id),
    });
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
        size: EDGE_SIZE,
        graphKey: e.graph,
      });
    }
    layout(graph, res.center.id);

    destroySigma();
    canvas.innerHTML = "";
    sigma = new Sigma(graph, canvas, {
      renderEdgeLabels: false,
      labelRenderedSizeThreshold: 0,
      // **既定値(false)のままだと`clickEdge`が一度も発火しない**
      // (Sigma.jsのsettings.enableEdgeEventsは既定false。`sigma/settings`の
      // 生成物で実測確認済み)。実ブラウザで辺をクリックしても何も起きない
      // 欠陥として実際に踏んだ——「参照元(出典)がグラフから辿れることを
      // 確かめる」(裁定B92のE-1要求4)を満たすため明示的に有効化する。
      enableEdgeEvents: true,
    });

    sigma.on("clickNode", ({ node }) => {
      const attrs = graph.getNodeAttributes(node);
      void showNodeDetail(node, attrs.idPath as string, Boolean(attrs.fanoutTruncated));
    });
    sigma.on("clickEdge", ({ edge }) => {
      const attrs = graph.getEdgeAttributes(edge);
      const prov = graphs[attrs.graphKey as string];
      detail.innerHTML = `<p><strong>${esc(String(attrs.label ?? ""))}</strong></p><p>${provenanceHtml(prov)}</p>`;
    });

    status.textContent = neighborhoodStatusText({
      nodeCount: res.nodes.length + 1,
      edgeCount: res.edges.length,
      nodesTruncated: res.nodes_truncated,
      edgesTruncated: res.edges_truncated,
      fanoutTruncatedCount: res.fanout_truncated_nodes.length,
    });

    renderLegend();
  }

  /**
   * ノードをクリックしたときに、その場(`.jgkg-graph-detail`)へ概要を出す
   * (裁定B92のE-1要求3: 「グラフ上でノードを選ぶと、その場で概要が見える」
   * ——以前はここで別のエンティティ画面へ`navigate`していた)。
   *
   * 出すもの: 型(6軸の表示名も)・表示名・属性(値と出典リンク。`entity.ts`と
   * 同じ`attributeValueHtml`を使う)・(分岐数の上限に達しているノードだけ)
   * さらに展開するボタン・そのエンティティの画面へ移動するリンク。
   *
   * **追加のAPI経路は使わない**(`/entity/{id_path}`のみ。ブリーフの拘束条件)。
   */
  async function showNodeDetail(nodeId: string, idPath: string, fanoutTruncated: boolean): Promise<void> {
    const requestId = ++detailRequestId;
    detail.innerHTML = '<p class="jgkg-muted">読み込み中…</p>';
    let entity: EntityDetailResponse | null;
    try {
      entity = await entityDetail(idPath);
    } catch (e) {
      if (destroyed || requestId !== detailRequestId) return;
      detail.innerHTML = `<p class="jgkg-error">取得に失敗しました: ${esc(String(e))}</p>`;
      return;
    }
    if (destroyed || requestId !== detailRequestId) return; // 後続のクリックの結果で既に上書きされている
    if (!entity) {
      detail.innerHTML = '<p class="jgkg-muted">このエンティティは見つかりませんでした。</p>';
      return;
    }
    // このノードの属性が主張する出典グラフを、辺クリックが引く`graphs`
    // マップに合流させる(展開時の`mergeRelationshipsIntoGraph`と同じ扱い)。
    graphs = { ...graphs, ...entity.graphs };

    const axis = axisForType(entity.type);
    const axisBadge = axis === undefined ? "" : `<span class="jgkg-muted"> ・ ${esc(typeLabel(axis))}軸</span>`;
    const color = colorForType(entity.type);

    const attrRows = Object.entries(entity.attributes)
      .map(
        ([pred, values]) =>
          `<tr><th>${esc(predicateLabel(pred))}</th><td>${values
            .map((v) => attributeValueHtml(pred, v, entity!.graphs))
            .join("、")}</td></tr>`,
      )
      .join("");

    // 展開ボタンは「この先にまだ取得していない隣接がある」ノード
    // (fanoutTruncated)だけに出す——分岐数の上限に達していないノードは
    // 近傍取得時点で隣接を全て含んでいるので、展開しても新しい辺は増えない。
    let expandHtml = "";
    if (fanoutTruncated) {
      const groupNames = Object.keys(entity.relationships);
      if (groupNames.length > 0) {
        const buttons = groupNames
          .map(
            (g) =>
              `<button type="button" class="jgkg-expand-group" data-group="${esc(g)}">${esc(typeLabel(g))}(${entity!.relationships[g]!.length}件)を表示</button>`,
          )
          .join(" ");
        expandHtml = `<p class="jgkg-muted">この先には次の型のノードがあります。表示する型を選んでください:</p><p>${buttons}</p>`;
      }
    }

    detail.innerHTML = `
      <div class="jgkg-node-detail">
        <p>
          <span class="jgkg-type-badge" style="border-color:${color};color:${color}">${esc(typeLabel(entity.type))}</span>${axisBadge}
        </p>
        <h3>${esc(entity.label ?? "(表示名なし)")}</h3>
        ${attrRows ? `<table class="jgkg-attr-table">${attrRows}</table>` : '<p class="jgkg-muted">属性はありません。</p>'}
        ${expandHtml}
        <p class="jgkg-secondary"><a href="#" class="jgkg-node-detail-open" data-id-path="${esc(idPath)}">&rarr; このエンティティの画面を開く</a></p>
      </div>`;

    detail.querySelectorAll<HTMLButtonElement>(".jgkg-expand-group").forEach((btn) => {
      btn.addEventListener("click", () => {
        mergeRelationshipsIntoGraph(nodeId, entity!.relationships[btn.dataset.group!]!, entity!.graphs);
      });
    });
    detail.querySelector<HTMLAnchorElement>(".jgkg-node-detail-open")?.addEventListener("click", (ev) => {
      ev.preventDefault();
      navigate({ name: "entity", idPath });
    });
  }

  /**
   * 分岐数の上限で隣接が切られたノードを、述語を選んで展開する(裁定B74)。
   *
   * APIに新しい引数(述語フィルタ等)は無い——`/entity/{id_path}`が既に
   * 返す「型別にグループ化された関係一覧」を取得し、利用者が選んだ
   * グループをこのグラフへ手元でマージするだけで実現する(表示側の
   * 判断であり、API変更は不要という裁定B74の要求どおり)。
   *
   * 追加するノード・辺そのものは`planExpansion`(純粋関数)が決める——
   * ここでは決めたものをSigma/graphologyへ書き込むだけ。
   */
  function mergeRelationshipsIntoGraph(
    fromNodeId: string,
    rels: EntityDetailResponse["relationships"][string],
    provGraphs: Record<string, Provenance>,
  ): void {
    if (!sigma) return;
    const graph = sigma.getGraph() as MultiGraph;
    graphs = { ...graphs, ...provGraphs };

    const plan = planExpansion(fromNodeId, rels, new Set(graph.nodes()));
    // **位置(x/y)をノード追加と同時に決める。** 追加してから後で
    // `setNodeAttribute`する2段階にすると、Sigmaが既にバインド済みの
    // グラフでは1段目(位置未定の`addNode`)の時点で例外になる
    // (`addEntityNode`のコメント参照)。
    const base = graph.getNodeAttributes(fromNodeId);
    for (const ref of plan.newNodes) {
      const jitter = (Math.random() - 0.5) * 4;
      addEntityNode(graph, ref, { x: (base.x as number) + jitter + 4, y: (base.y as number) + jitter });
    }
    for (const e of plan.edges) {
      graph.addEdge(e.source, e.target, {
        label: predicateLabel(e.predicate),
        color: "#9ca3af",
        size: EDGE_SIZE,
        graphKey: e.graph,
      });
    }
    graph.setNodeAttribute(fromNodeId, "fanoutTruncated", false);
    graph.setNodeAttribute(
      fromNodeId,
      "label",
      String(graph.getNodeAttribute(fromNodeId, "label")).replace(/ ⋯$/, ""),
    );
    renderLegend(); // 展開で新しい型(=新しい軸の項目)が増えることがある
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
