// 予算事業(`BudgetProject`)の本体。予算額を大きく/年度/所管府省へのリンク/
// 根拠法令/未解決の根拠/支出/年度予算/支出先ブロック。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../../api/client";
import { Amount, Section, Stat } from "../../../components/ui";
import { navigate, routeToHash } from "../../../router";
import { displayLabel, firstAttributeValue, omitRelationshipTypes, relationshipsOfType } from "../entity-model";
import { Relationships } from "../Relationships";

const MINISTRY_LIKE_TYPES = ["Ministry", "GovernmentOrgan", "AbolishedGovernmentOrgan"] as const;

export function ProjectBody({ entity }: { entity: EntityDetailResponse }): JSX.Element {
  const budgetAmount = firstAttributeValue(entity, "budgetAmount");
  const fiscalYear = firstAttributeValue(entity, "fiscalYear");

  const ministryRel = MINISTRY_LIKE_TYPES.map(
    (t) => relationshipsOfType(entity, t, { predicate: "ministry", direction: "outgoing" })[0],
  ).find((r) => r !== undefined);

  const basisLaws = relationshipsOfType(entity, "Law", { predicate: "basisLaw", direction: "outgoing" });
  const unresolvedBasis = relationshipsOfType(entity, "UnresolvedReference", {
    predicate: "unresolvedFor",
    direction: "incoming",
  });
  const expenditures = relationshipsOfType(entity, "Expenditure", { predicate: "project", direction: "incoming" });
  const annualBudgets = relationshipsOfType(entity, "AnnualBudget", { predicate: "project", direction: "incoming" });
  const blocks = relationshipsOfType(entity, "ExpenditureBlock", { predicate: "project", direction: "incoming" });

  const consumed = [...MINISTRY_LIKE_TYPES, "Law", "UnresolvedReference", "Expenditure", "AnnualBudget", "ExpenditureBlock"];
  const rest = omitRelationshipTypes(entity.relationships, consumed);

  return (
    <div className="jg-stack jg-stack--7">
      <div className="jg-grid jg-grid--3">
        <Stat label="予算額" value={<Amount yen={budgetAmount ? Number(budgetAmount.value) : undefined} />} />
        <Stat label="予算年度" value={fiscalYear?.value ?? "—"} unit="年度" />
        <Stat
          label="所管府省庁"
          value={
            ministryRel ? (
              <a
                href={routeToHash({ name: "entity", idPath: ministryRel.related.id_path })}
                onClick={(e) => {
                  e.preventDefault();
                  navigate({ name: "entity", idPath: ministryRel.related.id_path });
                }}
              >
                {displayLabel(ministryRel.related)}
              </a>
            ) : (
              "—"
            )
          }
        />
      </div>

      <Section title="根拠法令" eyebrow={`${basisLaws.length}件`}>
        <Relationships relationships={{ Law: basisLaws }} emptyLabel="根拠法令は記録されていません。" />
      </Section>

      {unresolvedBasis.length > 0 ? (
        <Section
          title="未解決の根拠"
          note="元データに根拠法令らしい記述はありましたが、正準の法令IDに対応付けできませんでした。"
        >
          <Relationships relationships={{ UnresolvedReference: unresolvedBasis }} />
        </Section>
      ) : null}

      <Section title="支出" eyebrow={`${expenditures.length}件`}>
        <Relationships relationships={{ Expenditure: expenditures }} emptyLabel="支出の記録はありません。" />
      </Section>

      <Section title="年度予算" eyebrow={`${annualBudgets.length}件`}>
        <Relationships
          relationships={{ AnnualBudget: annualBudgets }}
          emptyLabel="年度ごとの予算の記録はありません。"
        />
      </Section>

      <Section title="支出先ブロック" eyebrow={`${blocks.length}件`}>
        <Relationships relationships={{ ExpenditureBlock: blocks }} emptyLabel="支出先ブロックの記録はありません。" />
      </Section>

      {Object.keys(rest).length > 0 ? (
        <Section title="その他の関係">
          <Relationships relationships={rest} />
        </Section>
      ) : null}
    </div>
  );
}
