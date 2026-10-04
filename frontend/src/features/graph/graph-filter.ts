import type { GraphParams } from "../../router";
import type { GraphModel } from "./graph-model";

/** 取得済み範囲だけを絞る。起点は文脈として保持し、辺の端点を落とさない。 */
export function filterGraph(model: GraphModel, params: GraphParams): GraphModel {
  const types = params.types ?? [];
  const predicates = params.predicates ?? [];
  if (!types.length && !predicates.length) return model;
  const nodes = model.nodes.filter((n) => n.id === model.centerId || !types.length || types.includes(n.type));
  const ids = new Set(nodes.map((n) => n.id));
  const edges = model.edges.filter((e) => ids.has(e.source) && ids.has(e.target) && (!predicates.length || predicates.includes(e.predicate)));
  const connected = new Set(edges.flatMap((e) => [e.source, e.target]));
  return { ...model, nodes: predicates.length ? nodes.filter((n) => n.id === model.centerId || connected.has(n.id)) : nodes, edges };
}
