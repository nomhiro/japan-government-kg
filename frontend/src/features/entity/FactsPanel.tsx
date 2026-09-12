// サイドの「事実」(属性)と出典(裁定B86)。
//
// **旧画面の問題**: 属性1行ごとに出典が繰り返され、出典の文字数が値より
// 長くなっていた(厚労省の画面で4行の属性に対し出典リンク21個)。
//
// **直し方**: 出典はこの節の下に1行(または、節内に複数の出典が混在する
// ときだけ複数行)へまとめる。値の側には、その値が節全体の出典と違う場合
// だけ小さな印(丸数字)を付け、まとめ行の同じ数字と対応させる。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../api/client";
import { Amount } from "../../components/ui";
import { licenseSummary } from "../../components/provenance";
import { enumValueLabel, predicateLabel } from "../../labels";
import {
  isAmountPredicate,
  markerGlyph,
  sectionSourceLines,
  valueSourceMarkers,
} from "./entity-model";

export function FactsPanel({ entity }: { entity: EntityDetailResponse }): JSX.Element {
  const rows = Object.entries(entity.attributes);
  const allValues = rows.flatMap(([, values]) => values);
  const lines = sectionSourceLines(entity.graphs, allValues);
  const showMarkers = lines.length > 1;
  const license = licenseSummary(lines);

  return (
    <aside className="jg-card entity-facts jg-stack jg-stack--4" aria-label="事実">
      <h2 className="jg-h2">事実</h2>

      {rows.length === 0 ? (
        <p className="jg-sm jg-muted">属性は記録されていません。</p>
      ) : (
        <table className="jg-table entity-facts__table">
          <tbody>
            {rows.map(([predicate, values]) => (
              <tr key={predicate}>
                <th scope="row">{predicateLabel(predicate)}</th>
                <td>
                  {values.map((v, i) => {
                    const marks = showMarkers ? valueSourceMarkers(entity.graphs, lines, v) : [];
                    return (
                      <span key={i} className="entity-facts__value">
                        {i > 0 ? "、" : ""}
                        {isAmountPredicate(predicate) ? (
                          <Amount yen={Number(v.value)} />
                        ) : (
                          enumValueLabel(predicate, v.value)
                        )}
                        {marks.length > 0 ? (
                          <sup className="entity-facts__marker">{marks.map(markerGlyph).join("")}</sup>
                        ) : null}
                      </span>
                    );
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {lines.length > 0 ? (
        <div className="jg-xs jg-muted entity-facts__sources jg-source">
          <span className="jg-eyebrow">出典</span>{" "}
          {lines.map((l, i) => (
            <span key={l.graph}>
              {i > 0 ? " ・ " : ""}
              {showMarkers ? <strong>{markerGlyph(i + 1)}</strong> : null}{" "}
              {l.available && l.url ? (
                <a href={l.url} target="_blank" rel="noopener noreferrer">
                  {l.host ?? "一次資料"}
                </a>
              ) : (
                <span className="jg-source__missing">出典が取れていない</span>
              )}
              {l.fetchedOn ? `(${l.fetchedOn} 取得)` : ""}
            </span>
          ))}
          {license ? <span className="jg-source__license"> — {license}</span> : null}
        </div>
      ) : null}
    </aside>
  );
}
