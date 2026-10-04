// 政府の活動・制度・組織からの探索入口(裁定B116)。
// B103の予算集計は、利用者が開く一つの調べ方として保持する。
//
// **数字の規律。** 予算の数字は`/overview`(=CQの答え)を使う。
// 予算コンポーネントは別の集計をしない——`overview-format.ts`
// の関数だけを通す(裁定B103)。旧画面(`views/overview.ts`)と同じ数字の
// 出典を使う。テーマ候補の取得範囲・件数は検索APIの応答を使う(B116)。
//
// **全幅を使う。** 読み物の幅(`--content`)ではなく可視化の幅
// (`--content-wide`/`full`)を使う——旧画面は1440px幅で中央960pxしか
// 使わず、可視化が無かった(利用者評価「今の状態は全然ダメ」)。
import type { JSX } from "react";
import { useEffect } from "react";
import { apiUnavailableReason, fetchOverview } from "../../api/client";
import { useApiQuery } from "../../api/useApiQuery";
import { Band, Empty, ErrorBox, Loading, Section } from "../../components/ui";
import { ministriesForFiscalYear, latestFiscalYear, OVERVIEW_UNAVAILABLE_TEXT } from "../../lib/overview-format";
import { Entrances } from "./Entrances";
import { FlowStages } from "./FlowStages";
import { Hero } from "./Hero";
import { History } from "./History";
import { MinistryTreemap } from "./MinistryTreemap";
import "./overview.css";
import { RecipientMix } from "./RecipientMix";
import { Discovery } from "../explore/Discovery";

export function TopPage(): JSX.Element {
  const unavailable = apiUnavailableReason();
  const query = useApiQuery(unavailable ? null : "overview", fetchOverview);

  useEffect(() => {
    if (query.status === "error") {
      // 利用者には内部事情(503・起動時の集約)を出さないが、調査可能に
      // するためコンソールには実際の例外を出す(`views/overview.ts`と同じ
      // 方針)。
      console.error("トップページ(/overview)の取得に失敗した", query.error);
    }
  }, [query.status, query.error]);

  const data = query.status === "ready" ? query.data : undefined;
  const fiscalYear = latestFiscalYear(data?.ministries ?? []);
  const currentMinistries = ministriesForFiscalYear(data?.ministries ?? [], fiscalYear);

  return (
    <div className="jg-top jg-stack jg-stack--8" aria-label="政府の活動と組織・制度のつながり">
      <Band wide><Discovery data={data} primary /></Band>
      {unavailable ? <Band wide><ErrorBox>{unavailable}</ErrorBox></Band> : null}
      {query.status === "loading" ? <Band wide><Loading label="収録府省の一覧を読み込み中" /></Band> : null}
      {query.status === "error" ? <Band wide><ErrorBox>{OVERVIEW_UNAVAILABLE_TEXT}</ErrorBox></Band> : null}
      {data ? <details className="jg-budget-disclosure">
        <summary>予算・資金の流れから調べる</summary>
      <Band wide>
        <Hero
          fiscalYear={fiscalYear}
          currentMinistries={currentMinistries}
          budgetAndExecution={data.budget_and_execution}
          governmentPaid={data.government_paid}
          releaseFreshness={data.release_freshness}
          naiveSumVsEntryOnly={data.naive_sum_vs_entry_only}
          typeCounts={data.type_counts}
          sources={data.sources}
          computedAt={data.computed_at}
        />
      </Band>

      <Band full sunken ruled>
        <Section
          title="府省ごとの予算額"
          eyebrow={fiscalYear !== null ? `${fiscalYear}年度` : undefined}
        >
          {currentMinistries.length === 0 ? (
            <Empty>府省ごとの予算額のデータがありません。</Empty>
          ) : (
            <MinistryTreemap ministries={currentMinistries} fiscalYear={fiscalYear} sources={data.sources} />
          )}
        </Section>
      </Band>

      <Band wide ruled>
        <Section
          title="資金の流れ"
          eyebrow="同じお金が段を経て記録されている"
        >
          <FlowStages rows={data.money_through_stages} sources={data.sources} />
        </Section>
      </Band>

      <Band wide ruled>
        <Section title="年度の推移">
          <History
            budgetAndExecution={data.budget_and_execution}
            requestExactlyGranted={data.request_exactly_granted}
            sources={data.sources}
          />
        </Section>
      </Band>

      <Band wide ruled>
        <Section title="支払先はどこまで特定できているか">
          <RecipientMix rows={data.recipient_identification} sources={data.sources} />
        </Section>
      </Band>

      <Band wide sunken ruled>
        <Section title="つながりを辿る" eyebrow="ここから掘れます">
          <Entrances />
        </Section>
      </Band>
      </details> : null}
    </div>
  );
}
