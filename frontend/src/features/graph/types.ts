// グラフ部品の契約(裁定B106)。この形だけがエンティティ画面との境界であり、
// グラフの内部(レイアウトの計算・描画)は外から見えない。
import type { EntityRef } from "../../api/client";
import type { GraphParams } from "../../router";

export interface GraphViewProps {
  /** 中心のエンティティ。`/entity` の応答から作って渡す。 */
  readonly center: EntityRef;
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
