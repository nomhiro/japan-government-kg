// 支出(`Expenditure`)の本体。金額/支払先/属する段/照合区分。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../../api/client";
import { Amount, Section, Stat } from "../../../components/ui";
import { enumValueLabel } from "../../../labels";
import { firstAttributeValue, omitRelationshipTypes, relationshipsGroupedFromTypes, relationshipsOfType } from "../entity-model";
import { Relationships } from "../Relationships";

const RECIPIENT_TYPES = ["Organization", "GovernmentOrgan", "Ministry", "AbolishedGovernmentOrgan", "Agent"] as const;

export function ExpenditureBody({ entity }: { entity: EntityDetailResponse }): JSX.Element {
  const amount = firstAttributeValue(entity, "amount_jpy");
  const matchCategory = firstAttributeValue(entity, "recipientMatchCategory");
  const payeeLabel = firstAttributeValue(entity, "payeeLabel");

  const recipientsByType = relationshipsGroupedFromTypes(entity, RECIPIENT_TYPES, {
    predicate: "recipient",
    direction: "outgoing",
  });
  const recipientCount = Object.values(recipientsByType).reduce((n, rs) => n + rs.length, 0);

  const projects = relationshipsOfType(entity, "BudgetProject", { predicate: "project", direction: "outgoing" });
  const blocks = relationshipsOfType(entity, "ExpenditureBlock", { predicate: "inBlock", direction: "outgoing" });

  const consumed = [...RECIPIENT_TYPES, "BudgetProject", "ExpenditureBlock"];
  const rest = omitRelationshipTypes(entity.relationships, consumed);

  return (
    <div className="jg-stack jg-stack--7">
      <div className="jg-grid jg-grid--3">
        <Stat label="金額" value={<Amount yen={amount ? Number(amount.value) : undefined} />} />
        <Stat
          label="支払先の照合区分"
          value={matchCategory ? enumValueLabel("recipientMatchCategory", matchCategory.value) : "—"}
        />
        <Stat label="支払先の表示名" value={payeeLabel?.value ?? "—"} />
      </div>

      <Section title="支払先" eyebrow={`${recipientCount}件`}>
        <Relationships relationships={recipientsByType} emptyLabel="支払先は記録されていません。" />
      </Section>

      <Section title="属する事業" eyebrow={`${projects.length}件`}>
        <Relationships relationships={{ BudgetProject: projects }} emptyLabel="属する事業は記録されていません。" />
      </Section>

      <Section title="属する支出先ブロック" eyebrow={`${blocks.length}件`}>
        <Relationships relationships={{ ExpenditureBlock: blocks }} emptyLabel="属する支出先ブロックは記録されていません。" />
      </Section>

      {Object.keys(rest).length > 0 ? (
        <Section title="その他の関係">
          <Relationships relationships={rest} />
        </Section>
      ) : null}
    </div>
  );
}
