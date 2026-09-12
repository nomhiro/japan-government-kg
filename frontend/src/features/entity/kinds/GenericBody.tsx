// それ以外の型の本体。属性はサイドの`FactsPanel`が既に見せているので、
// ここでは関係を相手型ごとにグループ化した表だけを見せる。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../../api/client";
import { Relationships } from "../Relationships";

export function GenericBody({ entity }: { entity: EntityDetailResponse }): JSX.Element {
  return (
    <div className="jg-stack jg-stack--7">
      <Relationships relationships={entity.relationships} emptyLabel="関係は記録されていません。" />
    </div>
  );
}
