// 応答(近傍サブグラフ + 展開で足した関係)を、レイアウトが使う内部モデルに写す
// 純関数群(裁定B106)。ここでは位置(x/y)を計算しない —— それは
// `layout-lanes.ts`/`layout-force.ts` の仕事で、この段は「次数・ホップ数・
// レーン割当・重複排除」という、どちらのレイアウトも必要とする土台だけを作る。
//
// **表示名はここで合成しない(裁定B78/B88)。** `label`は応答の値
// (`null`もそのまま)を運ぶだけで、「(表示名なし)」という文言は描画側
// (`GraphView.tsx`)の仕事にする —— この段は「データが無い」という事実と
// 「無いときにどう見せるか」という表示判断を分けておく。
import type { DescribingValue, EntityRef, GraphEdge, Relationship } from "../../api/client";
import { axisForType } from "../../labels";
import { NO_LABEL, displayName } from "../../lib/display-name";
import { ASIDE_LANE, laneKeyForType } from "../../lib/ontology-view";

// ---------------------------------------------------------------------------
// 生データの合成(重複排除)
// ---------------------------------------------------------------------------

export interface RawGraph {
  readonly nodes: readonly EntityRef[];
  readonly edges: readonly GraphEdge[];
}

function edgeKey(e: Pick<GraphEdge, "source" | "target" | "predicate" | "graph">): string {
  // 区切りは半角スペース1文字。source/target(完全なIRI)にもpredicate(述語の
  // ローカル名)にも現れないので衝突しない。
  return `${e.source} ${e.predicate} ${e.target} ${e.graph}`;
}

/**
 * 複数の生データ(近傍応答 + 展開で足した分)をノード・辺ともに重複なく1つに
 * 合わせる。ノードは`id`で先着優先(同じノードが複数回出てきても最初の値を
 * 使う——近傍応答とエンティティ詳細で同じノードの`label`が食い違うことは
 * 無いはずだが、食い違わせない側の規約として先着を固定する)。辺は
 * `source+predicate+target+graph`で重複排除する(同じ辺が近傍応答と展開の
 * 両方に出てくることがある)。
 */
export function mergeRawGraphs(parts: readonly RawGraph[]): RawGraph {
  const nodes = new Map<string, EntityRef>();
  const edges = new Map<string, GraphEdge>();
  for (const part of parts) {
    for (const n of part.nodes) {
      if (!nodes.has(n.id)) nodes.set(n.id, n);
    }
    for (const e of part.edges) {
      edges.set(edgeKey(e), e);
    }
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

/**
 * エンティティ詳細の関係1件(`direction`付き)を、向きを持たない辺
 * (`GraphEdge`と同じ形)に変換する。`direction === "outgoing"`は
 * 「このエンティティが主語」——`subjectId`が`source`になる。
 */
export function relationshipToEdge(subjectId: string, rel: Relationship): GraphEdge {
  return rel.direction === "outgoing"
    ? { source: subjectId, target: rel.related.id, predicate: rel.predicate, graph: rel.graph }
    : { source: rel.related.id, target: subjectId, predicate: rel.predicate, graph: rel.graph };
}

/**
 * エンティティ詳細の関係のうち、型別に束ねられた1グループ
 * (`EntityDetailResponse.relationships`の1キー分)を`RawGraph`に変換する。
 * Inspectorの「この型の先を展開」ボタンが押したグループをグラフに足すときに使う。
 */
export function relationshipGroupToRawGraph(
  subjectId: string,
  group: readonly Relationship[],
): RawGraph {
  return {
    nodes: group.map((r) => r.related),
    edges: group.map((r) => relationshipToEdge(subjectId, r)),
  };
}

/** `neighborhood()`の応答から`RawGraph`を取り出す(そのままだが、境界を明示するため関数にする)。 */
export function rawGraphFromNeighborhood(n: {
  readonly nodes: readonly EntityRef[];
  readonly edges: readonly GraphEdge[];
}): RawGraph {
  return { nodes: n.nodes, edges: n.edges };
}

// ---------------------------------------------------------------------------
// レーン割当(型で決まらない分を辺の向きで補う)
// ---------------------------------------------------------------------------

/**
 * ノードのレーンを決める。型だけで決まるもの(`laneKeyForType`)と
 * 脇のストリップの型(`ASIDE_LANE.types`)はそのまま使う。
 *
 * **`Organization`は型ではレーンが決まらない(`laneKeyForType`が`undefined`を
 * 返す)。** 辺で決める —— `recipient`述語の目的語(支払先)になっている
 * ノードは「支払先」レーン、そうでなければ「所管」レーン(実データでは
 * `GovernmentOrgan`が支払先になる行が1,839件あるが、`Organization`は
 * 型そのものが「所管」と「支払先」の両方に現れるため、型だけでは
 * 決められない——`ontology-view.ts`の`laneKeyForType`のdocstring参照)。
 *
 * 上記のどれでもない型(将来オントロジーに増える未知の型)は、
 * 新しい意味を捏造せず脇のストリップに落とす。
 */
export function assignLanes(
  nodes: readonly Pick<EntityRef, "id" | "type">[],
  edges: readonly Pick<GraphEdge, "source" | "target" | "predicate">[],
): ReadonlyMap<string, string> {
  const recipientTargets = new Set<string>();
  for (const e of edges) {
    if (e.predicate === "recipient") recipientTargets.add(e.target);
  }
  const asideTypes: readonly string[] = ASIDE_LANE.types;
  const lane = new Map<string, string>();
  for (const n of nodes) {
    const byType = laneKeyForType(n.type);
    if (byType !== undefined) {
      lane.set(n.id, byType);
      continue;
    }
    if (asideTypes.includes(n.type)) {
      lane.set(n.id, ASIDE_LANE.key);
      continue;
    }
    if (n.type === "Organization") {
      lane.set(n.id, recipientTargets.has(n.id) ? "recipient" : "who");
      continue;
    }
    lane.set(n.id, ASIDE_LANE.key);
  }
  return lane;
}

// ---------------------------------------------------------------------------
// ホップ数(中心からの距離。無向で辿る——資金の流れの向きと、
// グラフ上の「近さ」は別の概念)
// ---------------------------------------------------------------------------

function bfsHops(
  centerId: string,
  nodeIds: readonly string[],
  edges: readonly Pick<GraphEdge, "source" | "target">[],
): ReadonlyMap<string, number> {
  const adj = new Map<string, string[]>();
  for (const id of nodeIds) adj.set(id, []);
  for (const e of edges) {
    adj.get(e.source)?.push(e.target);
    adj.get(e.target)?.push(e.source);
  }
  const hop = new Map<string, number>();
  if (!adj.has(centerId)) return hop;
  hop.set(centerId, 0);
  const queue: string[] = [centerId];
  let i = 0;
  while (i < queue.length) {
    const cur = queue[i];
    i += 1;
    if (cur === undefined) continue;
    const curHop = hop.get(cur) ?? 0;
    for (const next of adj.get(cur) ?? []) {
      if (!hop.has(next)) {
        hop.set(next, curHop + 1);
        queue.push(next);
      }
    }
  }
  return hop;
}

// ---------------------------------------------------------------------------
// モデル本体
// ---------------------------------------------------------------------------

export interface ModelNode {
  readonly id: string;
  readonly idPath: string;
  readonly type: string;
  readonly label: string | null;
  /** 表示名が無い型を見分けるための属性(裁定B108)。APIが `label === null`
   *  のときだけ入れる。`lib/display-name.ts` が描き方を決める。 */
  readonly describedBy: DescribingValue | null;
  readonly axis: string | undefined;
  readonly laneKey: string;
  /** 中心からのホップ数(無向)。中心自身は0。到達できない場合は`Infinity`。 */
  readonly hop: number;
  readonly degree: number;
  readonly hasMore: boolean;
}

export interface ModelEdge {
  readonly key: string;
  readonly source: string;
  readonly target: string;
  readonly predicate: string;
  readonly graph: string;
}

export interface GraphModel {
  readonly centerId: string;
  readonly nodes: readonly ModelNode[];
  readonly edges: readonly ModelEdge[];
}

export interface BuildGraphModelParams {
  readonly raw: RawGraph;
  readonly centerId: string;
  /** APIの`fanout_truncated_nodes`(完全なIRI)。展開前の既定の`hasMore`。 */
  readonly fanoutTruncatedIds: ReadonlySet<string>;
  /**
   * 展開済みノードの`hasMore`を上書きする(id→まだ切り詰められているか)。
   * `entity/{id_path}`を`limit=200`で呼んだ後の`relationships_truncated`を渡す
   * ——`fanoutTruncatedIds`より新しい情報を優先する。
   */
  readonly hasMoreOverrides?: ReadonlyMap<string, boolean>;
}

/**
 * `RawGraph`から表示用モデルを作る。**状態を持たない純関数**——同じ入力なら
 * 同じ出力(次数もホップもレーンも、そのつど全体から計算し直す。差分更新は
 * しない)。展開でノードが増えるたびにこれを呼び直す前提。
 */
export function buildGraphModel(params: BuildGraphModelParams): GraphModel {
  const { raw, centerId, fanoutTruncatedIds, hasMoreOverrides } = params;

  const degree = new Map<string, number>();
  for (const e of raw.edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }

  const nodeIds = raw.nodes.map((n) => n.id);
  const hops = bfsHops(centerId, nodeIds, raw.edges);
  const lanes = assignLanes(raw.nodes, raw.edges);

  const nodes: ModelNode[] = raw.nodes.map((n) => ({
    id: n.id,
    idPath: n.id_path,
    type: n.type,
    label: n.label,
    describedBy: n.described_by ?? null,
    axis: axisForType(n.type),
    laneKey: lanes.get(n.id) ?? ASIDE_LANE.key,
    hop: hops.get(n.id) ?? Number.POSITIVE_INFINITY,
    degree: degree.get(n.id) ?? 0,
    hasMore: hasMoreOverrides?.get(n.id) ?? fanoutTruncatedIds.has(n.id),
  }));

  const edges: ModelEdge[] = raw.edges.map((e) => ({
    key: edgeKey(e),
    source: e.source,
    target: e.target,
    predicate: e.predicate,
    graph: e.graph,
  }));

  return { centerId, nodes, edges };
}

// ---------------------------------------------------------------------------
// 表示名(合成しない。無いときの文言だけをここに1箇所で決める)
// ---------------------------------------------------------------------------

/**
 * 表示名が無いノードの文言(裁定B78/B88: 名前を合成しない)。
 *
 * **規則の本体は `lib/display-name.ts` に1本化した(裁定B108)。** ここと
 * `features/entity/entity-model.ts` が同じ文言を別々に持っていたので、
 * 「表示名が無いときどう出すか」を2箇所で決めていた。
 */
export const NO_LABEL_TEXT = NO_LABEL;

/**
 * ノードの1行を返す。表示名が無ければ見分けのための属性を、それも無ければ
 * 「(表示名なし)」を返す。
 *
 * `label`だけを渡す旧シグネチャも受け付ける(呼び出し側の都合で文字列しか
 * 持っていない箇所が残っている)。
 */
export function displayLabel(
  node: string | null | { readonly label: string | null; readonly describedBy: DescribingValue | null },
): string {
  if (node === null || typeof node === "string") return displayName({ label: node });
  // グラフのモデルはcamelCase、APIはsnake_case。**境界でだけ変換する**
  // (どちらかに寄せて全部書き換えるより、対応表が1行で済む)。
  return displayName({ label: node.label, described_by: node.describedBy });
}

export interface TruncatedText {
  readonly text: string;
  readonly truncated: boolean;
  /** 省略していない全文(`<title>`に使う)。 */
  readonly full: string;
}

/**
 * 表示文字列を、幅に収まる文字数(`maxChars`)で省略する。全角前提の
 * おおまかな見積り(SVGはCSSの`text-overflow`が効かないため、自分で切る)。
 * `maxChars`が文字数以下ならそのまま。1文字だけ入る余地が無いほど狭い場合
 * (`maxChars <= 1`)は"…"だけを返す——負のインデックスで壊れないためのガード。
 */
export function truncateForWidth(full: string, maxChars: number): TruncatedText {
  if (full.length <= maxChars) {
    return { text: full, truncated: false, full };
  }
  const keep = Math.max(0, maxChars - 1);
  return { text: `${full.slice(0, keep)}…`, truncated: true, full };
}
