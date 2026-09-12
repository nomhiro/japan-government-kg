// エンティティ画面全体(型で分岐)。裁定: 全ての型を同じ属性表で見せない。
//
// **主内容は `.jg-grid--sidebar`**: 本体(グラフ+型別の節)+サイド(事実+出典)。
// グラフは折りたたまず、説明文で下に押し出さない——グラフの見出しの直後に
// 描き、注記(`Caveat`)はグラフの**下**に置く。
//
// **`GraphView`(`features/graph/`)は別のエージェントが同時に実装している。**
// ここでは契約(`GraphViewProps`)だけを前提に呼び出す。まだ存在しない間は
// ビルドが通らないので、このファイルのテストは呼び出し側のロジックだけを
// `GraphView`をモックして検査する(`EntityPage.test.tsx`)。
import { useState, type JSX } from "react";
import { entityDetail, type EntityRef } from "../../api/client";
import { ENTITY_RELATIONSHIPS_LIMIT } from "../../api/limits";
import { useApiQuery } from "../../api/useApiQuery";
import { pageTitle, useDocumentTitle } from "../../app/document-title";
import { useRoute } from "../../app/useRoute";
import { Band, Caveat, ErrorBox, Loading, Truncation } from "../../components/ui";
import { GraphView } from "../graph/GraphView";
import { navigate, parseGraphParams, replaceGraphParams, routeToHash, type GraphParams } from "../../router";
import { EntityHeader } from "./EntityHeader";
import { FactsPanel } from "./FactsPanel";
import { NO_LABEL, breadcrumbMinistryRef, graphCaveatText, kindOf } from "./entity-model";
import { ExpenditureBody } from "./kinds/ExpenditureBody";
import { GenericBody } from "./kinds/GenericBody";
import { LawBody } from "./kinds/LawBody";
import { MinistryBody } from "./kinds/MinistryBody";
import { OrganizationBody } from "./kinds/OrganizationBody";
import { ProjectBody } from "./kinds/ProjectBody";
import "./entity.css";

export function EntityPage({ idPath }: { idPath: string }): JSX.Element {
  // ハッシュの変化(グラフの状態。深さ・並べ方・軸の絞り込み・選択)を
  // 購読するためだけに呼ぶ——戻り値の`Route`は使わない(`parseGraphParams`を
  // 毎回のレンダーで直接読む)。
  useRoute();

  const [limit, setLimit] = useState<number | undefined>(undefined);
  const queryKey = `${idPath}::${limit ?? "default"}`;
  const state = useApiQuery(queryKey, () => entityDetail(idPath, limit));

  // タブの名前をこのエンティティの表示名にする(`AppShell` は entity の題を
  // 書かない。document-title.ts 参照)。**表示名はAPIの `label` だけを使う**
  // ——無ければ `(表示名なし)` と言う(裁定B78/B88)。
  useDocumentTitle(
    pageTitle(
      state.status === "loading"
        ? "読み込み中"
        : state.status === "error"
          ? "読み込みに失敗しました"
          : state.data === null
            ? "見つかりませんでした"
            : (state.data.label ?? NO_LABEL),
    ),
  );

  if (state.status === "loading") {
    return (
      <Band>
        <Loading label="エンティティを読み込み中" />
      </Band>
    );
  }

  if (state.status === "error") {
    return (
      <Band>
        <ErrorBox>読み込みに失敗しました: {state.error.message}</ErrorBox>
      </Band>
    );
  }

  const entity = state.data;
  if (entity === null) {
    return (
      <Band>
        <ErrorBox>このエンティティは見つかりませんでした。</ErrorBox>
        <p className="jg-sm">
          <a
            href={routeToHash({ name: "top" })}
            onClick={(e) => {
              e.preventDefault();
              navigate({ name: "top" });
            }}
          >
            &larr; 全体を見るに戻る
          </a>
        </p>
      </Band>
    );
  }

  const kind = kindOf(entity.type);
  const ministryRef = breadcrumbMinistryRef(entity);
  const centerRef: EntityRef = { id: entity.id, id_path: entity.id_path, label: entity.label, type: entity.type };
  const graphParams: GraphParams = parseGraphParams(location.hash);
  const canLoadMore = entity.relationships_truncated && (limit === undefined || limit < ENTITY_RELATIONSHIPS_LIMIT.max);

  let body: JSX.Element;
  switch (kind) {
    case "ministry":
      body = <MinistryBody entity={entity} />;
      break;
    case "project":
      body = <ProjectBody entity={entity} />;
      break;
    case "organization":
      body = <OrganizationBody entity={entity} />;
      break;
    case "law":
      body = <LawBody entity={entity} />;
      break;
    case "expenditure":
      body = <ExpenditureBody entity={entity} />;
      break;
    default:
      body = <GenericBody entity={entity} />;
      break;
  }

  return (
    <>
      <EntityHeader entity={entity} idPath={idPath} kind={kind} ministryRef={ministryRef} />

      {/* **グラフは独立した全幅の帯に置く。** サイドの「事実」とグラフ自身の
          インスペクタに挟むと、5レーンの流れ図が幅641pxまで圧され、カードの
          文字が読めなくなる(実ブラウザで確認した)。流れ図は左右方向に読む図なので
          横幅が命であり、この画面で最も広い場所を与える。 */}
      <Band full wide>
        <div id="graph" className="jg-stack jg-stack--4 entity-graph-band">
          <h2 className="jg-h2">つながりで見る</h2>
          <GraphView
            center={centerRef}
            params={graphParams}
            onParamsChange={(next) => replaceGraphParams(idPath, next)}
            onRecenter={(nextIdPath) => navigate({ name: "entity", idPath: nextIdPath })}
            onUseAsPathStart={(nextIdPath) => navigate({ name: "path", from: nextIdPath })}
          />
          <Caveat>{graphCaveatText(kind)}</Caveat>
        </div>
      </Band>

      <Band full>
        <div className="jg-grid jg-grid--sidebar entity-layout">
          <div className="jg-stack jg-stack--7 entity-main">
            <Truncation truncated={entity.relationships_truncated} limit={entity.relationships_limit} what="関係">
              {canLoadMore ? (
                <button
                  type="button"
                  className="jg-btn jg-btn--sm"
                  onClick={() => setLimit(ENTITY_RELATIONSHIPS_LIMIT.max)}
                >
                  もっと見る(上限{ENTITY_RELATIONSHIPS_LIMIT.max}件まで取得)
                </button>
              ) : null}
            </Truncation>

            {body}
          </div>
          <FactsPanel entity={entity} />
        </div>
      </Band>
    </>
  );
}
