// 実ブラウザでの確認専用(裁定に基づく一時的なハーネス)。App.tsxはまだ
// GraphViewに繋がっていない(team-leadが繋ぐ)ため、確認のあいだだけ
// main.tsxをこれに向ける。確認が終わったら`git checkout src/main.tsx`で戻す。
import { useState, type JSX } from "react";
import type { EntityRef } from "../../../api/client";
import { DEFAULT_GRAPH_PARAMS, type GraphParams } from "../../../router";
import { GraphView } from "../GraphView";

const PRESETS: readonly EntityRef[] = [
  {
    id: "https://jgkg.norr-tech.com/id/org/6000012070001",
    id_path: "org/6000012070001",
    type: "Ministry",
    label: "厚生労働省(深さ1)",
  },
  {
    id: "https://jgkg.norr-tech.com/id/budget/2025/2841",
    id_path: "budget/2025/2841",
    type: "BudgetProject",
    label: "国民年金基金等給付費負担金(深さ2)",
  },
];

export function DevGraphPage(): JSX.Element {
  const [center, setCenter] = useState<EntityRef>(PRESETS[0] as EntityRef);
  const [params, setParams] = useState<GraphParams>(DEFAULT_GRAPH_PARAMS);

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: "0 auto" }}>
      <p style={{ fontSize: 12, color: "#888" }}>
        DevGraphPage(確認用の一時ページ。frontend/src/features/graph/__dev__/DevGraphPage.tsx)
      </p>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        {PRESETS.map((p) => (
          <button
            key={p.id_path}
            type="button"
            onClick={() => {
              setCenter(p);
              setParams(DEFAULT_GRAPH_PARAMS);
            }}
          >
            {p.label}
          </button>
        ))}
      </div>
      <GraphView
        center={center}
        params={params}
        onParamsChange={setParams}
        onRecenter={(idPath) => setCenter((c) => ({ ...c, id_path: idPath }))}
        onUseAsPathStart={(idPath) => window.alert(`経路の始点にする: ${idPath}`)}
      />
    </div>
  );
}
