// レーン流れ図(裁定B106)。公開部品——`GraphViewProps`だけが外との境界で、
// レイアウトの計算(`layout-lanes.ts`/`layout-force.ts`)・モデルの合成
// (`graph-model.ts`)は内部に隠す。
//
// **SVGで描く(Sigma.jsを使わない)。** ノード数はAPIの上限で最大500と
// 小さく、SVGなら実テキストなので選択・検索・読み上げができ、hover/click が
// 通常のDOMイベントになる——canvasのpickingバッファに乗らずクリックが
// 発火しない欠陥の型が構造的に消える(裁定B93)。
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { entityDetail, neighborhood, type EntityDetailResponse } from "../../api/client";
import { ENTITY_RELATIONSHIPS_LIMIT, NEIGHBORHOOD_DEPTH } from "../../api/limits";
import { useApiQuery } from "../../api/useApiQuery";
import { Empty, ErrorBox, Loading } from "../../components/ui";
import type { NeighborhoodStatus } from "../../format";
import { predicateLabel, typeLabel } from "../../labels";
import { ASIDE_LANE, axisColorVar } from "../../lib/ontology-view";
import { navigate, type GraphLayout } from "../../router";
import { GraphTable } from "./GraphTable";
import { GraphToolbar } from "./GraphToolbar";
import {
  buildGraphModel,
  displayLabel,
  mergeRawGraphs,
  rawGraphFromNeighborhood,
  relationshipGroupToRawGraph,
  truncateForWidth,
  type GraphModel,
  type RawGraph,
} from "./graph-model";
import "./graph.css";
import { Inspector } from "./Inspector";
import { CARD_H, CARD_W, GAP_Y, HEADER_H, MARGIN_TOP } from "./layout-lanes";
import { layoutForce } from "./layout-force";
import { layoutLanes } from "./layout-lanes";
import type { GraphLayoutResult, GraphViewProps, PlacedNode } from "./types";

const LABEL_MAX_CHARS = 12;
const EMPTY_LAYOUT: GraphLayoutResult = { nodes: [], edges: [], lanes: [], width: 0, height: 0 };
const EMPTY_IDS: ReadonlySet<string> = new Set<string>();
const VIEWBOX_PAD = 24;
const MIN_VIEWBOX = 80;

interface ViewBox {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export function GraphView(props: GraphViewProps): JSX.Element {
  const { center, params, onParamsChange, onRecenter, onUseAsPathStart, supplied, showDepth = true } = props;

  // --- 展開・折り畳みの状態(このコンポーネントだけが持つ。URLには載せない) ---
  const [expandedLanes, setExpandedLanes] = useState<ReadonlySet<string>>(new Set());
  const [expandedTypes, setExpandedTypes] = useState<Readonly<Record<string, ReadonlySet<string>>>>({});
  const [detailsCache, setDetailsCache] = useState<Readonly<Record<string, EntityDetailResponse>>>({});
  const [showTable, setShowTable] = useState(false);
  const [manualViewBox, setManualViewBox] = useState<ViewBox | null>(null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [hoveredEdgeKey, setHoveredEdgeKey] = useState<string | null>(null);

  useEffect(() => {
    setExpandedLanes(new Set());
    setExpandedTypes({});
    setDetailsCache({});
    setShowTable(false);
    setManualViewBox(null);
    setHoveredId(null);
    setHoveredEdgeKey(null);
  }, [center.id_path, supplied?.raw]);

  // --- データ取得 -----------------------------------------------------------
  // **外からグラフを与えられたら取りに行かない**(裁定B109)。
  // `key` が null のとき `useApiQuery` は `{status:"ready", data: undefined}`
  // を返す——読み込み中・エラー・「近傍が見つからない」のどの分岐にも
  // 入らないので、下の描画はそのまま供給されたモデルを使う。
  const nbhdKey = supplied ? null : `${center.id_path}|${params.depth}`;
  const nbhdQuery = useApiQuery(nbhdKey, () => neighborhood(center.id_path, { depth: params.depth }));

  const selectedIdPath = params.selected ?? null;
  const detailQuery = useApiQuery(selectedIdPath, () => {
    const idPath = selectedIdPath;
    if (idPath === null) throw new Error("unreachable: key===nullのときfetcherは呼ばれない");
    return entityDetail(idPath, ENTITY_RELATIONSHIPS_LIMIT.max);
  });

  useEffect(() => {
    if (detailQuery.status === "ready" && detailQuery.data) {
      const d = detailQuery.data;
      setDetailsCache((prev) => (prev[d.id] === d ? prev : { ...prev, [d.id]: d }));
    }
  }, [detailQuery.status, detailQuery.data]);

  // --- モデルの合成(近傍応答 + 展開で足した分) -------------------------------
  const hasMoreOverrides = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const d of Object.values(detailsCache)) m.set(d.id, d.relationships_truncated);
    return m;
  }, [detailsCache]);

  const additions: RawGraph[] = useMemo(() => {
    const out: RawGraph[] = [];
    for (const [id, types] of Object.entries(expandedTypes)) {
      const d = detailsCache[id];
      if (!d) continue;
      for (const t of types) {
        const group = d.relationships[t];
        if (group) out.push(relationshipGroupToRawGraph(id, group));
      }
    }
    return out;
  }, [expandedTypes, detailsCache]);

  const model: GraphModel | null = useMemo(() => {
    if (supplied) {
      return buildGraphModel({
        raw: mergeRawGraphs([supplied.raw, ...additions]),
        centerId: supplied.centerId,
        fanoutTruncatedIds: supplied.fanoutTruncatedIds,
        hasMoreOverrides,
      });
    }
    const nbhd = nbhdQuery.data;
    if (!nbhd) return null;
    const merged = mergeRawGraphs([rawGraphFromNeighborhood(nbhd), ...additions]);
    return buildGraphModel({
      raw: merged,
      centerId: nbhd.center.id,
      fanoutTruncatedIds: new Set(nbhd.fanout_truncated_nodes),
      hasMoreOverrides,
    });
  }, [supplied, nbhdQuery.data, additions, hasMoreOverrides]);

  const adjacency = useMemo(() => {
    const m = new Map<string, Set<string>>();
    if (!model) return m;
    for (const e of model.edges) {
      if (!m.has(e.source)) m.set(e.source, new Set());
      if (!m.has(e.target)) m.set(e.target, new Set());
      m.get(e.source)?.add(e.target);
      m.get(e.target)?.add(e.source);
    }
    return m;
  }, [model]);

  // --- レイアウト -------------------------------------------------------------
  // 強調するノード。与えられていなければ空(中心だけが強調される)。
  const emphasizedIds: ReadonlySet<string> = supplied?.emphasizedIds ?? EMPTY_IDS;
  // **強調の意味は呼び出し方で違う。** 単一中心の近傍では「中心」だが、
  // 合算グラフ(検索結果)では19件が全部「中心」になってしまい嘘になる。
  const emphasisTag = supplied?.emphasizedIds ? "一致" : "中心";

  const layoutResult: GraphLayoutResult = useMemo(() => {
    if (!model) return EMPTY_LAYOUT;
    return params.layout === "force"
      ? layoutForce(model)
      // 強調するノード(検索のヒット)を折り畳みで隠さない(裁定B109)。
      : layoutLanes(model, { expandedLanes, priorityIds: emphasizedIds });
  }, [model, params.layout, expandedLanes, emphasizedIds]);

  const nodeById = useMemo(() => new Map(layoutResult.nodes.map((n) => [n.id, n])), [layoutResult.nodes]);


  // --- 状態行(グラフ自身から数える。裁定B93) ---------------------------------
  const status: NeighborhoodStatus = useMemo(
    () => ({
      nodeCount: model?.nodes.length ?? 0,
      edgeCount: model?.edges.length ?? 0,
      // 打ち切りは**取得元が言ったことをそのまま運ぶ**。合算グラフでは
      // 呼び出し側が集約して渡す(`SuppliedGraph` のdocstring参照)。
      nodesTruncated: supplied ? supplied.nodesTruncated : nbhdQuery.data?.nodes_truncated ?? false,
      edgesTruncated: supplied ? supplied.edgesTruncated : nbhdQuery.data?.edges_truncated ?? false,
      fanoutTruncatedCount: model?.nodes.filter((n) => n.hasMore).length ?? 0,
    }),
    [model, nbhdQuery.data, supplied],
  );

  // --- 選択 --------------------------------------------------------------------
  const selectedNode: PlacedNode | null = useMemo(() => {
    if (!params.selected) return null;
    return layoutResult.nodes.find((n) => n.idPath === params.selected) ?? null;
  }, [layoutResult.nodes, params.selected]);
  const isCenterSelected = !!selectedNode && !!model && selectedNode.id === model.centerId;
  const selectedExpandedTypes = selectedNode ? expandedTypes[selectedNode.id] ?? new Set<string>() : new Set<string>();

  const setSelected = useCallback(
    (idPath: string | undefined) => {
      onParamsChange({ ...params, selected: idPath });
    },
    [onParamsChange, params],
  );

  const handleNodeClick = useCallback(
    (n: PlacedNode) => {
      setSelected(n.idPath === params.selected ? undefined : n.idPath);
    },
    [setSelected, params.selected],
  );

  const handleExpandType = useCallback(
    (typeKey: string) => {
      if (!selectedNode) return;
      const id = selectedNode.id;
      setExpandedTypes((prev) => {
        const cur = prev[id] ?? new Set<string>();
        if (cur.has(typeKey)) return prev;
        const next = new Set(cur);
        next.add(typeKey);
        return { ...prev, [id]: next };
      });
    },
    [selectedNode],
  );

  const handleExpandLane = useCallback((laneKey: string) => {
    setExpandedLanes((prev) => {
      const next = new Set(prev);
      next.add(laneKey);
      return next;
    });
  }, []);

  const handleOpenDetail = useCallback((idPath: string) => {
    navigate({ name: "entity", idPath });
  }, []);

  // --- ツールバーの操作 ---------------------------------------------------------
  const handleDepthChange = useCallback(
    (depth: number) => onParamsChange({ ...params, depth }),
    [onParamsChange, params],
  );
  const handleLayoutChange = useCallback(
    (layout: GraphLayout) => onParamsChange({ ...params, layout }),
    [onParamsChange, params],
  );
  const handleAxesChange = useCallback(
    (axes: readonly string[]) => onParamsChange({ ...params, axes }),
    [onParamsChange, params],
  );

  // --- ズーム・パン(SVGのviewBoxを直接操作) -------------------------------------
  //
  // **既定は「幅に合わせる。ただし縮小だけ」。全体を収めない。**
  // 全体を収める(高さにも合わせる)と、1レーンに25枚のカードが縦に並ぶ実データで
  // 0.5倍程度まで縮み、**カードの文字が読めなくなる**(実ブラウザで確認した)。
  // 読めることを収まることより優先し、縦はスクロール/パンで辿る。
  // 利用者が「フィット」を押したときだけ全体を収める(下の fitAllViewBox)。
  const [svgSize, setSvgSize] = useState({ w: 1000, h: 600 });
  useEffect(() => {
    const el = svgRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = (w: number, h: number) => {
      if (w > 0 && h > 0) setSvgSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    };
    // 初回は自分で測る。ResizeObserver は最初の1回も呼ぶが、
    // 呼ばれる前の1フレームを既定値(1000x600)で描くと器と縦横比が食い違い、
    // preserveAspectRatio="xMidYMid meet" が内容を上下中央に寄せてしまう
    // (実ブラウザで、グラフが器の下寄りに描かれる形で現れた)。
    const rect = el.getBoundingClientRect();
    measure(rect.width, rect.height);
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) measure(r.width, r.height);
    });
    ro.observe(el);
    return () => ro.disconnect();
    // **model を依存に入れる。** SVGは model が来てから初めてマウントされるので、
    // 依存を空にすると svgRef.current が null のまま一度も観測されない
    // (これで実際に上の症状が出た)。
  }, [model]);

  const contentW = layoutResult.width + VIEWBOX_PAD * 2;
  const contentH = layoutResult.height + VIEWBOX_PAD * 2;

  /** 既定の見え方。viewBoxの縦横比は器に揃えるので、余白(letterbox)は出ない。 */
  const defaultViewBox: ViewBox = useMemo(() => {
    const scale = Math.min(svgSize.w / Math.max(contentW, 1), 1);
    return {
      x: -VIEWBOX_PAD,
      y: -VIEWBOX_PAD,
      w: Math.max(svgSize.w / scale, MIN_VIEWBOX),
      h: Math.max(svgSize.h / scale, MIN_VIEWBOX),
    };
  }, [contentW, svgSize.w, svgSize.h]);

  /** 「フィット」ボタン用。全体を1画面に収める(縮小を許す)。 */
  const fitAllViewBox: ViewBox = useMemo(
    () => ({
      x: -VIEWBOX_PAD,
      y: -VIEWBOX_PAD,
      w: Math.max(contentW, MIN_VIEWBOX),
      h: Math.max(contentH, MIN_VIEWBOX),
    }),
    [contentW, contentH],
  );

  const fitViewBox = defaultViewBox;
  const viewBox = manualViewBox ?? defaultViewBox;

  const zoomBy = useCallback(
    (factor: number) => {
      setManualViewBox((prev) => {
        const base = prev ?? fitViewBox;
        const cx = base.x + base.w / 2;
        const cy = base.y + base.h / 2;
        const w = Math.max(base.w * factor, MIN_VIEWBOX);
        const h = Math.max(base.h * factor, MIN_VIEWBOX);
        return { x: cx - w / 2, y: cy - h / 2, w, h };
      });
    },
    [fitViewBox],
  );

  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<{ startX: number; startY: number; base: ViewBox } | null>(null);

  const handlePointerDown = useCallback(
    (e: ReactPointerEvent<SVGSVGElement>) => {
      if (e.target !== e.currentTarget && !(e.target as Element).classList?.contains("jg-graph-svg-bg")) return;
      dragRef.current = { startX: e.clientX, startY: e.clientY, base: manualViewBox ?? fitViewBox };
    },
    [manualViewBox, fitViewBox],
  );
  const handlePointerMove = useCallback((e: ReactPointerEvent<SVGSVGElement>) => {
    const d = dragRef.current;
    if (!d || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const dx = ((e.clientX - d.startX) * d.base.w) / rect.width;
    const dy = ((e.clientY - d.startY) * d.base.h) / rect.height;
    setManualViewBox({ x: d.base.x - dx, y: d.base.y - dy, w: d.base.w, h: d.base.h });
  }, []);
  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);
  const handleWheel = useCallback(
    (e: ReactWheelEvent<SVGSVGElement>) => {
      e.preventDefault();
      zoomBy(e.deltaY > 0 ? 1.1 : 0.9);
    },
    [zoomBy],
  );

  const handleSvgClick = useCallback(
    (e: { target: EventTarget | null; currentTarget: EventTarget | null }) => {
      if (e.target === e.currentTarget) setSelected(undefined);
    },
    [setSelected],
  );

  const handleNodeKeyDown = useCallback(
    (e: ReactKeyboardEvent<SVGGElement>, n: PlacedNode) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handleNodeClick(n);
      }
    },
    [handleNodeClick],
  );

  const axisFilterActive = params.axes.length > 0;

  return (
    <div className="jg-graph-view">
      <GraphToolbar
        depth={params.depth}
        depthMin={NEIGHBORHOOD_DEPTH.min}
        depthMax={NEIGHBORHOOD_DEPTH.max}
        onDepthChange={handleDepthChange}
        showDepth={showDepth}
        layout={params.layout}
        onLayoutChange={handleLayoutChange}
        axes={params.axes}
        onAxesChange={handleAxesChange}
        onZoomIn={() => zoomBy(0.8)}
        onZoomOut={() => zoomBy(1.25)}
        onFit={() => setManualViewBox(fitAllViewBox)}
        showTable={showTable}
        onToggleTable={() => setShowTable((s) => !s)}
        status={status}
      />

      {nbhdQuery.status === "loading" ? <Loading label="近傍を取得中" /> : null}
      {nbhdQuery.status === "error" ? <ErrorBox>{nbhdQuery.error.message}</ErrorBox> : null}
      {nbhdQuery.status === "ready" && nbhdQuery.data === null ? <Empty>近傍が見つかりませんでした。</Empty> : null}

      {model ? (
        <div className="jg-graph-view__body">
          <svg
            ref={svgRef}
            viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
            className="jg-graph-svg"
            role="img"
            aria-label="関係図(レーン流れ図または力学配置)"
            onWheel={handleWheel}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
            onClick={handleSvgClick}
          >
            <defs>
              <marker id="jg-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" className="jg-graph-arrow" />
              </marker>
            </defs>
            <rect
              className="jg-graph-svg-bg"
              x={viewBox.x - 1000}
              y={viewBox.y - 1000}
              width={viewBox.w + 2000}
              height={viewBox.h + 2000}
              fill="transparent"
            />

            {params.layout === "lanes"
              ? layoutResult.lanes.map((band) => (
                  <text key={band.key} className="jg-graph-lane-title" x={band.x + band.w / 2} y={16} textAnchor="middle">
                    {band.title}({band.count}件)
                  </text>
                ))
              : null}

            {params.layout === "lanes"
              ? layoutResult.lanes.map((band) => {
                  const shownCount = layoutResult.nodes.filter((n) => n.laneKey === band.key).length;
                  if (shownCount >= band.count) return null;
                  const y = MARGIN_TOP + HEADER_H + shownCount * (CARD_H + GAP_Y);
                  const remaining = band.count - shownCount;
                  return (
                    <g
                      key={`${band.key}-more`}
                      transform={`translate(${band.x},${y})`}
                      className="jg-graph-node jg-graph-node--more"
                      role="button"
                      tabIndex={0}
                      aria-label={`${band.title}の残り${remaining}件を表示する`}
                      onClick={() => handleExpandLane(band.key)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          handleExpandLane(band.key);
                        }
                      }}
                    >
                      <rect width={CARD_W} height={CARD_H} rx={6} />
                      <text x={CARD_W / 2} y={22} textAnchor="middle">
                        +{remaining}件
                      </text>
                    </g>
                  );
                })
              : null}

            {(() => {
              if (params.layout !== "lanes") return null;
              const asideNodes = layoutResult.nodes.filter((n) => n.laneKey === ASIDE_LANE.key);
              if (asideNodes.length === 0) return null;
              const top = Math.min(...asideNodes.map((n) => n.y));
              return (
                <g>
                  <line
                    className="jg-graph-aside-divider"
                    x1={0}
                    y1={top - 20}
                    x2={layoutResult.width}
                    y2={top - 20}
                  />
                  <text className="jg-graph-lane-title" x={12} y={top - 6}>
                    その他
                  </text>
                </g>
              );
            })()}

            <g className="jg-graph-edges">
              {layoutResult.edges.map((e) => {
                const isHovered = e.key === hoveredEdgeKey;
                const touchesHoveredNode = hoveredId ? e.source === hoveredId || e.target === hoveredId : false;
                const dim = hoveredId ? !touchesHoveredNode : false;
                const s = nodeById.get(e.source);
                const t = nodeById.get(e.target);
                const showLabel = isHovered || touchesHoveredNode;
                const midX = s && t ? (s.x + s.w / 2 + t.x + t.w / 2) / 2 : 0;
                const midY = s && t ? (s.y + s.h / 2 + t.y + t.h / 2) / 2 : 0;
                return (
                  <g key={e.key} className={`jg-graph-edge${dim ? " is-dim" : ""}`}>
                    <path
                      d={e.d}
                      className="jg-graph-edge__path"
                      markerEnd="url(#jg-arrow)"
                      onMouseEnter={() => setHoveredEdgeKey(e.key)}
                      onMouseLeave={() => setHoveredEdgeKey((k) => (k === e.key ? null : k))}
                      onClick={() => setHoveredEdgeKey((k) => (k === e.key ? null : e.key))}
                    >
                      <title>{predicateLabel(e.predicate)}</title>
                    </path>
                    {showLabel ? (
                      <text className="jg-graph-edge__label" x={midX} y={midY}>
                        {predicateLabel(e.predicate)}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </g>

            <g className="jg-graph-nodes">
              {layoutResult.nodes.map((n) => {
                const isCenterNode = n.id === model.centerId || emphasizedIds.has(n.id);
                const isSelected = n.idPath === params.selected;
                const isHovered = n.id === hoveredId;
                const isNeighborOfHover = hoveredId ? adjacency.get(hoveredId)?.has(n.id) ?? false : false;
                const passesAxisFilter = !axisFilterActive || (n.axis !== undefined && params.axes.includes(n.axis));
                const dim = hoveredId ? !(isHovered || isNeighborOfHover) : !passesAxisFilter;
                const { text, full } = truncateForWidth(displayLabel(n), LABEL_MAX_CHARS);
                return (
                  <g
                    key={n.id}
                    transform={`translate(${n.x},${n.y})`}
                    className={[
                      "jg-graph-node",
                      isCenterNode ? "is-center" : "",
                      isSelected ? "is-selected" : "",
                      dim ? "is-dim" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    role="button"
                    tabIndex={0}
                    aria-pressed={isSelected}
                    aria-label={`${typeLabel(n.type)}: ${displayLabel(n)}`}
                    onClick={() => handleNodeClick(n)}
                    onKeyDown={(e) => handleNodeKeyDown(e, n)}
                    onMouseEnter={() => setHoveredId(n.id)}
                    onMouseLeave={() => setHoveredId((h) => (h === n.id ? null : h))}
                  >
                    <title>{full}</title>
                    <rect className="jg-graph-node__card" width={n.w} height={n.h} rx={6} />
                    <rect className="jg-graph-node__stripe" width={4} height={n.h} style={{ fill: axisColorVar(n.axis) }} />
                    <text className="jg-graph-node__label" x={12} y={15}>
                      {text}
                    </text>
                    <text className="jg-graph-node__type" x={12} y={28}>
                      {typeLabel(n.type)}
                    </text>
                    {n.hasMore ? (
                      <text className="jg-graph-node__more" x={n.w - 10} y={15} textAnchor="end">
                        ⋯
                      </text>
                    ) : null}
                    {isCenterNode ? (
                      <text className="jg-graph-node__center-tag" x={n.w} y={-6} textAnchor="end">
                        {emphasisTag}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </g>
          </svg>

          <Inspector
            node={selectedNode}
            isCenter={isCenterSelected}
            detail={detailQuery}
            expandedTypes={selectedExpandedTypes}
            onExpandType={handleExpandType}
            onRecenter={onRecenter}
            onOpenDetail={handleOpenDetail}
            onUseAsPathStart={onUseAsPathStart}
          />
        </div>
      ) : null}

      {showTable && model ? <GraphTable model={model} /> : null}
    </div>
  );
}
