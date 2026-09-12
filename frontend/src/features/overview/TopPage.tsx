// トップページ再設計(裁定B103・第1層)。「国のお金と施策の全体像」を
// 5秒で把握し、そこから掘れる画面。
//
// **数字の規律。** 画面に出す数字はすべて`/overview`(=CQの答え)である。
// このファイル・配下のコンポーネントは別の集計をしない——`overview-format.ts`
// の関数だけを通す(裁定B103)。旧画面(`views/overview.ts`)と同じ数字の
// 出典を使い、見せ方だけを作り替える。
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

  if (unavailable) {
    return (
      <Band wide>
        <ErrorBox>{unavailable}</ErrorBox>
      </Band>
    );
  }

  if (query.status === "loading") {
    return (
      <Band wide>
        <Loading label="全体の数字を読み込み中" />
      </Band>
    );
  }

  if (query.status === "error") {
    return (
      <Band wide>
        <ErrorBox>{OVERVIEW_UNAVAILABLE_TEXT}</ErrorBox>
      </Band>
    );
  }

  const data = query.data;
  const fiscalYear = latestFiscalYear(data.ministries);
  const currentMinistries = ministriesForFiscalYear(data.ministries, fiscalYear);

  return (
    <div className="jg-top jg-stack jg-stack--8" aria-label="日本政府の予算と施策の全体像">
      <Band wide>
        <Hero
          fiscalYear={fiscalYear}
          currentMinistries={currentMinistries}
          budgetAndExecution={data.budget_and_execution}
          governmentPaid={data.government_paid}
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
    </div>
  );
}
