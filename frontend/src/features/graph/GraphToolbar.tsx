// グラフの操作(裁定B106)。軸チップ・深さ・並べ方・ズーム・表トグル・状態行。
// **押せるものだけを置く**(押しても何も起きない飾りのUIを作らない)——
// すべて`onXxx`で親(`GraphView`)に伝え、実際の状態はそちら側が持つ。
import type { JSX } from "react";
import { neighborhoodStatusText, type NeighborhoodStatus } from "../../format";
import { typeLabel } from "../../labels";
import { AXIS_ORDER, axisBgVarForType, axisColorVarForType } from "../../lib/ontology-view";
import type { GraphLayout } from "../../router";

export interface GraphToolbarProps {
  readonly depth: number;
  readonly depthMin: number;
  readonly depthMax: number;
  readonly onDepthChange: (depth: number) => void;

  readonly layout: GraphLayout;
  readonly onLayoutChange: (layout: GraphLayout) => void;

  readonly axes: readonly string[];
  readonly onAxesChange: (axes: readonly string[]) => void;

  readonly onZoomIn: () => void;
  readonly onZoomOut: () => void;
  readonly onFit: () => void;

  readonly showTable: boolean;
  readonly onToggleTable: () => void;

  readonly status: NeighborhoodStatus;
}

export function GraphToolbar(props: GraphToolbarProps): JSX.Element {
  const {
    depth,
    depthMin,
    depthMax,
    onDepthChange,
    layout,
    onLayoutChange,
    axes,
    onAxesChange,
    onZoomIn,
    onZoomOut,
    onFit,
    showTable,
    onToggleTable,
    status,
  } = props;

  const depthOptions = Array.from({ length: depthMax - depthMin + 1 }, (_, i) => depthMin + i);

  function toggleAxis(axis: string): void {
    if (axes.includes(axis)) {
      onAxesChange(axes.filter((a) => a !== axis));
    } else {
      onAxesChange([...axes, axis]);
    }
  }

  return (
    <div className="jg-graph-toolbar">
      <div className="jg-graph-toolbar__row">
        <fieldset className="jg-graph-toolbar__group" aria-label="深さ">
          <legend>深さ</legend>
          {depthOptions.map((d) => (
            <button
              key={d}
              type="button"
              className="jg-graph-toolbar__btn"
              aria-pressed={d === depth}
              onClick={() => onDepthChange(d)}
            >
              深さ{d}
            </button>
          ))}
        </fieldset>

        <fieldset className="jg-graph-toolbar__group" aria-label="並べ方">
          <legend>並べ方</legend>
          <button
            type="button"
            className="jg-graph-toolbar__btn"
            aria-pressed={layout === "lanes"}
            onClick={() => onLayoutChange("lanes")}
          >
            流れ(レーン)
          </button>
          <button
            type="button"
            className="jg-graph-toolbar__btn"
            aria-pressed={layout === "force"}
            onClick={() => onLayoutChange("force")}
          >
            力学
          </button>
        </fieldset>

        <div className="jg-graph-toolbar__group" role="group" aria-label="ズーム">
          <button type="button" className="jg-graph-toolbar__btn" onClick={onZoomOut} aria-label="縮小">
            −
          </button>
          <button type="button" className="jg-graph-toolbar__btn" onClick={onFit} aria-label="全体をフィット">
            フィット
          </button>
          <button type="button" className="jg-graph-toolbar__btn" onClick={onZoomIn} aria-label="拡大">
            ＋
          </button>
        </div>

        <button
          type="button"
          className="jg-graph-toolbar__btn"
          aria-pressed={showTable}
          onClick={onToggleTable}
        >
          すべての関係を表で
        </button>
      </div>

      <div className="jg-graph-toolbar__row jg-graph-toolbar__axes" role="group" aria-label="軸で絞り込み">
        {AXIS_ORDER.map((axis) => {
          const active = axes.includes(axis);
          return (
            <button
              key={axis}
              type="button"
              className="jg-graph-chip"
              aria-pressed={active}
              style={{
                color: axisColorVarForType(axis),
                background: active ? axisBgVarForType(axis) : "transparent",
                borderColor: axisColorVarForType(axis),
              }}
              onClick={() => toggleAxis(axis)}
            >
              {typeLabel(axis)}
            </button>
          );
        })}
        {axes.length > 0 ? (
          <button type="button" className="jg-graph-chip jg-graph-chip--clear" onClick={() => onAxesChange([])}>
            絞り込みを解除
          </button>
        ) : null}
      </div>

      <p className="jg-sm jg-graph-toolbar__status" role="status">
        {neighborhoodStatusText(status)}
      </p>
    </div>
  );
}
