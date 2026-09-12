// 右カラム: 選択したノードの詳細(裁定B106)。
// `/entity/{id_path}`の取得はここでは行わない —— 同じ応答を`GraphView`が
// 「この型の先を展開」の材料としても使うため、取得は`GraphView`に1本化し、
// 結果(`QueryState`)だけをここに渡す(重複フェッチを避ける)。
import type { JSX } from "react";
import type { EntityDetailResponse } from "../../api/client";
import type { QueryState } from "../../api/useApiQuery";
import { predicateLabel, typeLabel } from "../../labels";
import { axisBgVarForType, axisColorVarForType } from "../../lib/ontology-view";
import { Amount, SourceNote } from "../../components/ui";
import type { PlacedNode } from "./types";
import { displayLabel } from "./graph-model";

/** 金額の述語は丸めて出し、正確な値を title と読み上げに添える(`Amount`)。 */
const AMOUNT_PREDICATES = new Set([
  "amount_jpy",
  "budgetAmount",
  "initialBudget",
  "supplementaryBudget",
  "carriedOverFromPreviousYear",
  "reserveFund",
  "totalBudgetAvailable",
  "executedAmount",
  "carriedOverToNextYear",
  "nextYearRequest",
]);

function AttributeValueText({ predicate, value }: { predicate: string; value: string }): JSX.Element {
  if (AMOUNT_PREDICATES.has(predicate)) {
    const n = Number(value);
    if (Number.isFinite(n)) return <Amount yen={n} />;
  }
  return <>{value}</>;
}

export interface InspectorProps {
  readonly node: PlacedNode | null;
  readonly isCenter: boolean;
  readonly detail: QueryState<EntityDetailResponse | null>;
  /** すでにグラフに足した関係の型キー(このノードについて)。 */
  readonly expandedTypes: ReadonlySet<string>;
  readonly onExpandType: (typeKey: string) => void;
  readonly onRecenter: (idPath: string) => void;
  readonly onOpenDetail: (idPath: string) => void;
  readonly onUseAsPathStart?: (idPath: string) => void;
}

export function Inspector(props: InspectorProps): JSX.Element {
  const { node, isCenter, detail, expandedTypes, onExpandType, onRecenter, onOpenDetail, onUseAsPathStart } = props;

  if (!node) {
    return (
      <aside className="jg-graph-inspector" aria-label="ノードの詳細">
        <p className="jg-sm jg-muted">ノードをクリックすると詳細が出ます。</p>
      </aside>
    );
  }

  return (
    <aside className="jg-graph-inspector" aria-label="ノードの詳細">
      <div className="jg-graph-inspector__head">
        <span
          className="jg-badge"
          style={{ color: axisColorVarForType(node.type), background: axisBgVarForType(node.type) }}
        >
          {typeLabel(node.type)}
        </span>
        {isCenter ? <span className="jg-graph-inspector__center-tag">中心</span> : null}
      </div>
      <h3 className="jg-h3">{displayLabel(node.label)}</h3>
      <p className="jg-sm jg-muted">
        接続{node.degree}件・中心から{Number.isFinite(node.hop) ? `${node.hop}ホップ` : "到達不明"}
        {node.hasMore ? "・この先にまだ関係があります" : ""}
      </p>

      <div className="jg-graph-inspector__actions">
        <button type="button" disabled={isCenter} onClick={() => onRecenter(node.idPath)}>
          このノードを中心にする
        </button>
        <button type="button" onClick={() => onOpenDetail(node.idPath)}>
          詳細ページを開く
        </button>
        {onUseAsPathStart ? (
          <button type="button" onClick={() => onUseAsPathStart(node.idPath)}>
            経路の始点にする
          </button>
        ) : null}
      </div>

      {detail.status === "loading" ? <p className="jg-sm jg-muted" role="status">読み込み中…</p> : null}
      {detail.status === "error" ? (
        <p className="jg-sm jg-error" role="alert">
          属性・関係を取得できませんでした({detail.error.message})
        </p>
      ) : null}
      {detail.status === "ready" && detail.data === null ? (
        <p className="jg-sm jg-muted">詳細が見つかりませんでした。</p>
      ) : null}

      {detail.status === "ready" && detail.data ? (
        <InspectorDetail detail={detail.data} expandedTypes={expandedTypes} onExpandType={onExpandType} />
      ) : null}
    </aside>
  );
}

function InspectorDetail({
  detail,
  expandedTypes,
  onExpandType,
}: {
  detail: EntityDetailResponse;
  expandedTypes: ReadonlySet<string>;
  onExpandType: (typeKey: string) => void;
}): JSX.Element {
  const attributeKeys = Object.keys(detail.attributes).sort();
  const relationshipTypeKeys = Object.keys(detail.relationships).sort();

  return (
    <>
      {attributeKeys.length > 0 ? (
        <section className="jg-graph-inspector__section">
          <h4 className="jg-h4">属性</h4>
          <dl className="jg-graph-inspector__attrs">
            {attributeKeys.map((pred) => (
              <div key={pred} className="jg-graph-inspector__attr">
                <dt>{predicateLabel(pred)}</dt>
                <dd>
                  {/* **出典を値ごとに繰り返さない。** 節の下に1行でまとめる
                      (`SourceNote`)。旧実装は1つの値のうしろに
                      「(一次資料 (取得: … / 公共データ利用規約…))」を毎回付け、
                      出典が値より長くなっていた。 */}
                  {detail.attributes[pred]?.map((av, i) => (
                    <span key={i} className="jg-graph-inspector__val">
                      {i > 0 ? "、" : ""}
                      <AttributeValueText predicate={pred} value={av.value} />
                    </span>
                  )) ?? null}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {relationshipTypeKeys.length > 0 ? (
        <section className="jg-graph-inspector__section">
          <h4 className="jg-h4">関係(型別)</h4>
          <ul className="jg-graph-inspector__rel-list">
            {relationshipTypeKeys.map((typeKey) => {
              const group = detail.relationships[typeKey] ?? [];
              const added = expandedTypes.has(typeKey);
              return (
                <li key={typeKey}>
                  <button type="button" disabled={added} onClick={() => onExpandType(typeKey)}>
                    {added ? "追加済み" : "この型の先を展開"}: {typeLabel(typeKey)}({group.length}件)
                  </button>
                </li>
              );
            })}
          </ul>
          {detail.relationships_truncated ? (
            <p className="jg-sm jg-muted">
              関係が{detail.relationships_limit}件を超えています。先頭{detail.relationships_limit}件までです。
            </p>
          ) : null}
        </section>
      ) : null}

      <SourceNote graphs={detail.graphs} />
    </>
  );
}
