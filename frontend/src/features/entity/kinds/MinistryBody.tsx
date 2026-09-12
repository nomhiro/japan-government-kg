// 府省(`Ministry` / `GovernmentOrgan` / `AbolishedGovernmentOrgan`)の本体。
// 所管する予算事業の一覧を表で。廃止機関なら後継機関を目立たせる。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../../api/client";
import { Section } from "../../../components/ui";
import { navigate, routeToHash } from "../../../router";
import { displayLabel, omitRelationshipTypes, relationshipsOfType } from "../entity-model";
import { Relationships } from "../Relationships";

export function MinistryBody({ entity }: { entity: EntityDetailResponse }): JSX.Element {
  const budgetProjects = relationshipsOfType(entity, "BudgetProject", {
    predicate: "ministry",
    direction: "incoming",
  });
  const isAbolished = entity.type === "AbolishedGovernmentOrgan";
  const successors = isAbolished
    ? relationshipsOfType(entity, "GovernmentOrgan", { predicate: "succeededBy", direction: "outgoing" })
    : [];

  const consumed = ["BudgetProject", ...(successors.length > 0 ? ["GovernmentOrgan"] : [])];
  const rest = omitRelationshipTypes(entity.relationships, consumed);

  return (
    <div className="jg-stack jg-stack--7">
      {isAbolished ? (
        <Section title="後継機関" eyebrow="この機関は廃止されています">
          {successors.length > 0 ? (
            <ul className="jg-stack jg-stack--2">
              {successors.map((r) => (
                <li key={r.related.id_path}>
                  <a
                    href={routeToHash({ name: "entity", idPath: r.related.id_path })}
                    onClick={(e) => {
                      e.preventDefault();
                      navigate({ name: "entity", idPath: r.related.id_path });
                    }}
                  >
                    {displayLabel(r.related)}
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="jg-sm jg-muted">後継機関は記録されていません。</p>
          )}
        </Section>
      ) : null}

      <Section title="所管する予算事業" eyebrow={`${budgetProjects.length}件`}>
        <Relationships
          relationships={{ BudgetProject: budgetProjects }}
          emptyLabel="所管する予算事業は記録されていません。"
        />
      </Section>

      {Object.keys(rest).length > 0 ? (
        <Section title="その他の関係">
          <Relationships relationships={rest} />
        </Section>
      ) : null}
    </div>
  );
}
