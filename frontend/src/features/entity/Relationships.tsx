// 関係の一覧(裁定: `<details>`に畳まない。相手型ごとの表として見せる)。
//
// **打ち切りの告知(relationships_truncated / もっと見る)はここでは描かない。**
// このコンポーネントは同じ画面の中で複数回使われる(型別の節ごとに1回、
// 残りの関係にもう1回)ため、告知をここに持たせると同じ文言が何度も
// 繰り返される。告知は`EntityPage`が画面全体で1回だけ出す。
//
// **件数が多い型は先頭N件+「すべて見る」。** これは`relationships_limit`
// (APIの上限)とは別の軸——既に取得済みの行を折りたたむだけのクライアント側の
// 表示制御なので、追加のリクエストを発生させない。
import { useState, type JSX } from "react";
import type { EntityDetailResponse } from "../../api/client";
import { TypeBadge } from "../../components/ui";
import { predicateLabel, typeLabel } from "../../labels";
import { navigate, routeToHash } from "../../router";
import { directionArrow, displayLabel, sortedRelationshipGroups } from "./entity-model";

const DEFAULT_MAX_ROWS_PER_GROUP = 15;

export function Relationships({
  relationships,
  maxRowsPerGroup = DEFAULT_MAX_ROWS_PER_GROUP,
  emptyLabel = "関係は記録されていません。",
}: {
  relationships: EntityDetailResponse["relationships"];
  maxRowsPerGroup?: number;
  emptyLabel?: string;
}): JSX.Element {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  // 呼び出し側(型別の本体)は「この型で絞ったら0件だった」をそのまま
  // `{ Law: [] }`のように渡してくることがある——0件の型は見出しだけの
  // 空の表にせず、他に何も無ければ`emptyLabel`を出す(捏造しない・隠さない
  // の両方を満たす: 0件の型の存在自体は本体側の判断に委ね、ここでは
  // 「表として見せる価値がある行」だけを数える)。
  const groups = sortedRelationshipGroups(relationships).filter(([, rels]) => rels.length > 0);

  if (groups.length === 0) {
    return <p className="jg-sm jg-muted">{emptyLabel}</p>;
  }

  return (
    <div className="jg-stack jg-stack--5">
      {groups.map(([typeName, rels]) => {
        const isExpanded = expanded.has(typeName);
        const shown = isExpanded ? rels : rels.slice(0, maxRowsPerGroup);
        return (
          <div key={typeName} className="jg-stack jg-stack--2 entity-rel-group">
            <h3 className="jg-row jg-row--tight jg-h3">
              <TypeBadge type={typeName} size="sm" />
              <span>
                {typeLabel(typeName)}({rels.length}件)
              </span>
            </h3>
            <div className="jg-scroll-x">
              <table className="jg-table">
                <thead>
                  <tr>
                    <th>関係</th>
                    <th>相手</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r, i) => (
                    <tr key={`${r.predicate}-${r.direction}-${r.related.id_path}-${i}`}>
                      <td>
                        {directionArrow(r.direction)} {predicateLabel(r.predicate)}
                      </td>
                      <td>
                        <a
                          href={routeToHash({ name: "entity", idPath: r.related.id_path })}
                          onClick={(e) => {
                            e.preventDefault();
                            navigate({ name: "entity", idPath: r.related.id_path });
                          }}
                        >
                          {displayLabel(r.related)}
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rels.length > maxRowsPerGroup ? (
              <button
                type="button"
                className="jg-btn jg-btn--quiet jg-btn--sm"
                onClick={() =>
                  setExpanded((prev) => {
                    const next = new Set(prev);
                    if (isExpanded) next.delete(typeName);
                    else next.add(typeName);
                    return next;
                  })
                }
              >
                {isExpanded ? "折りたたむ" : `すべて見る(${rels.length}件)`}
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
