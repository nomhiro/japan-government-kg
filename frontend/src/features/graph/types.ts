// グラフ部品の契約(裁定B106)。この形だけがエンティティ画面との境界であり、
// グラフの内部(レイアウトの計算・描画)は外から見えない。
import type { DescribingValue, EntityRef } from "../../api/client";
import type { GraphParams } from "../../router";
import type { RawGraph } from "./graph-model";

/**
 * **外から与えるグラフ**(裁定B109)。
 *
 * これを渡すと `GraphView` は `/neighborhood` を取りに行かず、この内容を
 * そのまま描く。検索結果のように**中心が1つに決まらないグラフ**を、
 * エンティティ画面と同じ描画・同じ操作で見せるための口である。
 *
 * **打ち切りのフラグを呼び出し側が持って渡す。** 合算して作ったグラフでは
 * 「どれかの取得が打ち切られた」ことを呼び出し側しか知らない——
 * 既定でfalseにすると、打ち切りを黙って隠すことになる(裁定B82)。
 */
export interface SuppliedGraph {
  readonly raw: RawGraph;
  /**
   * ホップ数の起点。力学配置の初期位置にしか効かない(見た目の中心は
   * `emphasizedIds` が決める)。合算グラフでは先頭のヒットを渡す。
   */
  readonly centerId: string;
  readonly fanoutTruncatedIds: ReadonlySet<string>;
  /** 中心と同じ強調で描くノード(検索のヒットそのもの)。 */
  readonly emphasizedIds?: ReadonlySet<string>;
  readonly nodesTruncated: boolean;
  readonly edgesTruncated: boolean;
}

export interface GraphViewProps {
  /** 中心のエンティティ。`/entity` の応答から作って渡す。 */
  readonly center: EntityRef;
  /**
   * 与えると `/neighborhood` を取りに行かず、この内容を描く
   * (`SuppliedGraph` 参照)。`center` は「経路の始点にする」等の操作の
   * ためにそのまま要る。
   */
  readonly supplied?: SuppliedGraph;
  /** 深さの切り替えを出すか(既定true)。合算グラフでは深さに意味が無い。 */
  readonly showDepth?: boolean;
  /** URLから読んだ表示状態(深さ・並べ方・軸の絞り込み・選択)。 */
  readonly params: GraphParams;
  /**
   * 利用者の操作で状態が変わったときに呼ぶ。
   * 呼び出し側が `replaceGraphParams` でURLに書き戻す(履歴を積まない)。
   */
  readonly onParamsChange: (next: GraphParams) => void;
  /** 中心を移す(別のエンティティ画面へ遷移する)。 */
  readonly onRecenter: (idPath: string) => void;
  /** 経路探索の始点にする。 */
  readonly onUseAsPathStart?: (idPath: string) => void;
}

/** レイアウトが計算した1ノードの位置と見た目。描画側はこれだけを見る。 */
export interface PlacedNode {
  readonly id: string;
  readonly idPath: string;
  readonly type: string;
  readonly label: string | null;
  /** 表示名が無い型を見分けるための属性(裁定B108)。 */
  readonly describedBy: DescribingValue | null;
  readonly axis: string | undefined;
  readonly laneKey: string;
  /** 中心からのホップ数(0 = 中心)。 */
  readonly hop: number;
  /** このノードに接続している辺の本数。 */
  readonly degree: number;
  /** この先にまだ辺があるノード(APIの `fanout_truncated_nodes`)。 */
  readonly hasMore: boolean;
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export interface PlacedEdge {
  readonly key: string;
  readonly source: string;
  readonly target: string;
  readonly predicate: string;
  readonly graph: string;
  /** 描画する経路(SVGのd属性)。 */
  readonly d: string;
  /** 矢印を描く向き。レーンの並び(流れ)に合わせて正規化した後の向き。 */
  readonly flip: boolean;
}

export interface LaneBand {
  readonly key: string;
  readonly title: string;
  readonly x: number;
  readonly w: number;
  readonly count: number;
}

export interface GraphLayoutResult {
  readonly nodes: readonly PlacedNode[];
  readonly edges: readonly PlacedEdge[];
  readonly lanes: readonly LaneBand[];
  readonly width: number;
  readonly height: number;
}
