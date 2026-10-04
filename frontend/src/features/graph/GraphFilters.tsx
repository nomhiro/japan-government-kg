import { useState } from "react";
import { predicateLabel, typeLabel } from "../../labels";
import type { GraphParams } from "../../router";
import { displayLabel, type GraphModel } from "./graph-model";

export function GraphFilters({ model, params, onChange }: {
  model: GraphModel;
  params: GraphParams;
  onChange: (next: GraphParams) => void;
}) {
  const [find, setFind] = useState("");
  const types = [...new Set(model.nodes.map((n) => n.type))].sort();
  const predicates = [...new Set(model.edges.map((e) => e.predicate))].sort();
  const matches = find.trim() ? model.nodes.filter((n) => displayLabel(n).toLocaleLowerCase().includes(find.trim().toLocaleLowerCase())) : [];
  const toggle = (key: "types" | "predicates", value: string) => {
    const active = params[key] ?? [];
    onChange({ ...params, [key]: active.includes(value) ? active.filter((s) => s !== value) : [...active, value] });
  };
  return (
    <div className="jg-graph-filters">
      <details>
        <summary>型・関係で表示を絞る{params.types?.length || params.predicates?.length ? "（適用中）" : ""}</summary>
        <p className="jg-xs jg-muted">選んだ型・関係だけを表示します。起点は残します。軸のチップは一致する点を強調します。対象は取得済みの範囲です。</p>
        <div className="jg-graph-filters__groups">
          <fieldset><legend>型</legend>{types.map((t) => (
            <label key={t}><input type="checkbox" checked={params.types?.includes(t) ?? false} onChange={() => toggle("types", t)} />{typeLabel(t)}（{model.nodes.filter((n) => n.type === t).length}）</label>
          ))}</fieldset>
          <fieldset><legend>関係</legend>{predicates.map((p) => (
            <label key={p}><input type="checkbox" checked={params.predicates?.includes(p) ?? false} onChange={() => toggle("predicates", p)} />{predicateLabel(p)}（{model.edges.filter((e) => e.predicate === p).length}）</label>
          ))}</fieldset>
        </div>
        <button className="jg-btn jg-btn--sm" type="button" onClick={() => onChange({ ...params, types: [], predicates: [] })}>型・関係の絞り込みを解除</button>
      </details>
      <div className="jg-graph-find">
        <label>図の中から探す<input type="search" value={find} onChange={(e) => setFind(e.target.value)} placeholder="取得済みの名前・年度" /></label>
        {find.trim() ? (
          <div className="jg-graph-find__results">
            <p className="jg-xs jg-muted">{matches.length}件一致。選ぶと絞り込みを解除し、図の中で選択します。</p>
            {matches.map((n) => <button type="button" key={n.id} onClick={() => onChange({ ...params, selected: n.idPath, types: [], predicates: [] })}>{displayLabel(n)}<small>{typeLabel(n.type)}</small></button>)}
          </div>
        ) : null}
      </div>
    </div>
  );
}
