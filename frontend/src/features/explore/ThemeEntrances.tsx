import { useState } from "react";
import { apiUnavailableReason, search, type SearchHit } from "../../api/client";
import { SEARCH_LIMIT } from "../../api/limits";
import { useApiQuery } from "../../api/useApiQuery";
import { ErrorBox, Loading } from "../../components/ui";
import { displayName } from "../../lib/display-name";
import { routeToHash } from "../../router";

// 編集上の入口。テーマの意味や関与をKGの事実として追加しない。
const THEMES = ["防災", "教育", "医療", "環境", "科学", "デジタル"];
const GROUPS = [
  { title: "活動・事業", types: ["BudgetProject"], description: "行政事業レビューに収録された事業から、所管や根拠へ。" },
  { title: "制度・法令", types: ["Law"], description: "法令から、所管機関や根拠としている事業へ。" },
  { title: "組織・行政機関", types: ["Organization", "Ministry", "GovernmentOrgan", "AbolishedGovernmentOrgan"], description: "組織から、記録された活動との関係や組織の情報へ。" },
];

export function ThemeEntrances() {
  const [theme, setTheme] = useState(THEMES[0]!);
  const [retry, setRetry] = useState(0);
  const unavailable = apiUnavailableReason();
  const state = useApiQuery(unavailable ? null : `theme:${theme}:${retry}`, () => search(theme, SEARCH_LIMIT.max));
  const data = state.status === "ready" ? state.data : undefined;
  return (
    <section className="jg-stack jg-stack--3" aria-label="テーマから探索">
      <div className="jg-row jg-row--between">
        <h3 className="jg-h3">テーマを選んで、活動・制度・組織を見渡す</h3>
        <a href={routeToHash({ name: "search", q: theme })}>「{theme}」の検索結果を開く →</a>
      </div>
      <div className="jg-row jg-row--tight" role="group" aria-label="探索するテーマ">
        {THEMES.map((t) => <button className="jg-btn" type="button" key={t} aria-pressed={t === theme} onClick={() => setTheme(t)}>{t}</button>)}
      </div>
      <p className="jg-xs jg-muted">名前に「{theme}」を含む収録情報を表示します。テーマとの関与を示すものではありません。選んだ先で、出典付きの関係を確かめられます。</p>
      {state.status === "loading" ? <Loading label={`「${theme}」の入口を読み込み中`} /> : null}
      {unavailable || state.status === "error" ? <ErrorBox>テーマの一覧をいま取得できません。検索や、下の府省一覧からも始められます。{!unavailable ? <button className="jg-btn jg-btn--sm" type="button" onClick={() => setRetry((n) => n + 1)}>一覧を再取得</button> : null}</ErrorBox> : null}
      <div className="jg-theme-groups">
        {GROUPS.map((group) => {
          const hits: SearchHit[] = data?.results.filter((hit) => group.types.includes(hit.type)) ?? [];
          return <section key={group.title} className="jg-card jg-stack jg-stack--2" aria-label={group.title}>
            <h4 className="jg-h3">{group.title}</h4>
            <p className="jg-sm jg-muted">{group.description}</p>
            {data ? <>
              <ul>{hits.slice(0, 4).map((hit) => <li key={hit.id_path}><a href={routeToHash({ name: "explore", center: hit.id_path })}>{displayName(hit)} →</a>{hit.summary ? <small>{hit.summary}</small> : null}</li>)}</ul>
              <p className="jg-xs jg-muted">{hits.length ? `取得した一覧に${hits.length}件。ここでは先頭${Math.min(4, hits.length)}件を表示。` : "取得した一覧に一致する記録がありません。"}</p>
            </> : null}
          </section>;
        })}
      </div>
      {data?.truncated ? <p className="jg-xs jg-muted">名前に一致する先頭{data.limit}件から入口を選んでいます。収録された全件・全活動の一覧ではありません。</p> : null}
      <p className="jg-sm jg-muted">人物・役職・会議・発言の関係は、現在のKGには未収録です。</p>
    </section>
  );
}
