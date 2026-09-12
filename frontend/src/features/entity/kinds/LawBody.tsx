// 法令(`Law`)の本体。法令番号・公布日・廃止状態/所管府省/根拠とする事業。
// 改正記録(LawRevision)はKG上で辺を持たないため近傍に出ないことを明示する
// (観察O10。既存の注記と同じ事実)。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../../api/client";
import { Section, Stat } from "../../../components/ui";
import { enumValueLabel } from "../../../labels";
import { firstAttributeValue, omitRelationshipTypes, relationshipsGroupedFromTypes, relationshipsOfType } from "../entity-model";
import { Relationships } from "../Relationships";

const JURISDICTION_TYPES = ["Ministry", "GovernmentOrgan", "AbolishedGovernmentOrgan", "Organization"] as const;

export function LawBody({ entity }: { entity: EntityDetailResponse }): JSX.Element {
  const lawNum = firstAttributeValue(entity, "lawNum");
  const promulgationDate = firstAttributeValue(entity, "promulgationDate");
  const repealStatus = firstAttributeValue(entity, "repealStatus");

  const jurisdictionByType = relationshipsGroupedFromTypes(entity, JURISDICTION_TYPES, {
    predicate: "jurisdiction",
    direction: "outgoing",
  });
  const jurisdictionCount = Object.values(jurisdictionByType).reduce((n, rs) => n + rs.length, 0);

  const basisFor = relationshipsOfType(entity, "BudgetProject", { predicate: "basisLaw", direction: "incoming" });

  const consumed = [...JURISDICTION_TYPES, "BudgetProject"];
  const rest = omitRelationshipTypes(entity.relationships, consumed);

  return (
    <div className="jg-stack jg-stack--7">
      <div className="jg-grid jg-grid--3">
        <Stat label="法令番号" value={lawNum?.value ?? "—"} />
        <Stat label="公布日" value={<span className="jg-num">{promulgationDate?.value ?? "—"}</span>} />
        <Stat label="廃止状態" value={repealStatus ? enumValueLabel("repealStatus", repealStatus.value) : "—"} />
      </div>

      <Section title="所管府省" eyebrow={`${jurisdictionCount}件`}>
        <Relationships relationships={jurisdictionByType} emptyLabel="所管府省は記録されていません。" />
      </Section>

      <Section
        title="根拠とする事業"
        eyebrow={`${basisFor.length}件`}
        note="法令の改正記録(LawRevision)はナレッジグラフ上で辺を持たないため、この一覧やグラフには現れません。"
      >
        <Relationships relationships={{ BudgetProject: basisFor }} emptyLabel="この法令を根拠とする予算事業は記録されていません。" />
      </Section>

      {Object.keys(rest).length > 0 ? (
        <Section title="その他の関係">
          <Relationships relationships={rest} />
        </Section>
      ) : null}
    </div>
  );
}
