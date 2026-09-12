// 法人・組織(`Organization`)の本体。法人番号/所在地/受けた支出の表。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../../api/client";
import { Section, Stat } from "../../../components/ui";
import { firstAttributeValue, omitRelationshipTypes, relationshipsOfType } from "../entity-model";
import { Relationships } from "../Relationships";

export function OrganizationBody({ entity }: { entity: EntityDetailResponse }): JSX.Element {
  const houjinBangou = firstAttributeValue(entity, "houjinBangou");
  const prefecture = firstAttributeValue(entity, "prefectureName");
  const city = firstAttributeValue(entity, "cityName");
  const location = [prefecture?.value, city?.value].filter((s) => !!s).join("");

  const receipts = relationshipsOfType(entity, "Expenditure", { predicate: "recipient", direction: "incoming" });
  const rest = omitRelationshipTypes(entity.relationships, ["Expenditure"]);

  return (
    <div className="jg-stack jg-stack--7">
      <div className="jg-grid jg-grid--3">
        <Stat label="法人番号" value={<span className="jg-num">{houjinBangou?.value ?? "—"}</span>} />
        <Stat label="所在地" value={location || "—"} />
      </div>

      <Section title="受けた支出" eyebrow={`${receipts.length}件`}>
        <Relationships relationships={{ Expenditure: receipts }} emptyLabel="支出を受けた記録はありません。" />
      </Section>

      {Object.keys(rest).length > 0 ? (
        <Section title="その他の関係">
          <Relationships relationships={rest} />
        </Section>
      ) : null}
    </div>
  );
}
