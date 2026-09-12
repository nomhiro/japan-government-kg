// 図の代替となる本物の表(裁定B106)。スクリーンリーダー向けと、絵からは
// 読めなくなった情報(切り詰められて隠れた辺・省略された表示名)を読むため。
// レイアウトの結果(`PlacedNode`/`PlacedEdge`)ではなく、いま画面にある
// モデル(`GraphModel`)全体をそのまま表にする——レーンへの割当や省略表示に
// 引きずられない、正確な一覧であることを優先する。
import type { JSX } from "react";
import { predicateLabel, typeLabel } from "../../labels";
import { displayLabel, type GraphModel } from "./graph-model";

export interface GraphTableProps {
  readonly model: GraphModel;
}

export function GraphTable({ model }: GraphTableProps): JSX.Element {
  const nodeById = new Map(model.nodes.map((n) => [n.id, n]));

  return (
    <div className="jg-graph-table-wrap">
      <table className="jg-graph-table">
        <caption>すべての関係(表)。図で省略・非表示になっているものも含む全件。</caption>
        <thead>
          <tr>
            <th scope="col">起点</th>
            <th scope="col">型</th>
            <th scope="col">関係</th>
            <th scope="col">終点</th>
            <th scope="col">型</th>
          </tr>
        </thead>
        <tbody>
          {model.edges.map((e) => {
            const source = nodeById.get(e.source);
            const target = nodeById.get(e.target);
            return (
              <tr key={e.key}>
                <td>{source ? displayLabel(source) : e.source}</td>
                <td>{source ? typeLabel(source.type) : ""}</td>
                <td>{predicateLabel(e.predicate)}</td>
                <td>{target ? displayLabel(target) : e.target}</td>
                <td>{target ? typeLabel(target.type) : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {model.edges.length === 0 ? <p className="jg-sm jg-muted">辺がありません。</p> : null}
    </div>
  );
}
