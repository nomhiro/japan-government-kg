import { apiUnavailableReason, entityDetail, fetchOverview, type EntityRef } from "../../api/client";
import { useApiQuery } from "../../api/useApiQuery";
import { useRoute } from "../../app/useRoute";
import { Band, Caveat, Empty, ErrorBox, Loading } from "../../components/ui";
import { displayName } from "../../lib/display-name";
import { latestFiscalYear, ministriesForFiscalYear } from "../../lib/overview-format";
import { EXPLORE_DEFAULT_LAYOUT, exploreHash, navigate, parseGraphParams, replaceExploreParams, routeToHash } from "../../router";
import { GraphView } from "../graph/GraphView";
import { Discovery } from "./Discovery";
import "./explore.css";

export function ExplorePage({ center }: { center?: string }) {
  useRoute();
  const unavailable = apiUnavailableReason();
  const overview = useApiQuery(unavailable ? null : "explore-overview", fetchOverview);
  const data = overview.status === "ready" ? overview.data : undefined;
  const year = latestFiscalYear(data?.ministries ?? []);
  const ministries = ministriesForFiscalYear(data?.ministries ?? [], year)
    .sort((a, b) => displayName(a).localeCompare(displayName(b), "ja"));
  const initialMinistry = [...ministries].sort((a, b) => b.project_count - a.project_count || a.id_path.localeCompare(b.id_path))[0];
  const idPath = center ?? initialMinistry?.id_path;
  const detail = useApiQuery(!unavailable && idPath ? idPath : null, () => entityDetail(idPath!));
  const entity: EntityRef | undefined = detail.status === "ready" && detail.data ? detail.data : undefined;
  const params = parseGraphParams(location.hash, { defaultLayout: EXPLORE_DEFAULT_LAYOUT });

  return (
    <>
      <Band full wide>
        <div className="jg-explore-page jg-stack jg-stack--4">
          <div className="jg-row jg-row--between">
            <div><p className="jg-eyebrow">活動・制度・組織の関係を辿る</p><h1 className="jg-h1">つながりを探索する</h1></div>
            <a className="jg-btn" href={routeToHash({ name: "search", q: "" })}>名前・キーワードで検索</a>
          </div>
          <p className="jg-sm jg-muted">気になる点を選び、その先の関係を開いて調べられます。</p>
          {unavailable ? <ErrorBox>{unavailable}</ErrorBox> : null}
          {!unavailable && overview.status === "error" ? <ErrorBox>府省の一覧をいま取得できません。対象のURLがあれば、そのグラフは表示できます。</ErrorBox> : null}
          {ministries.length ? (
            <div className="jg-explore-scope">
              <label>入口の府省
                <select value={ministries.some((m) => m.id_path === idPath) ? idPath : ""}
                  onChange={(e) => navigate({ name: "explore", center: e.target.value })}>
                  <option value="" disabled>グラフ上の対象を探索中</option>
                  {ministries.map((m) => <option key={m.id_path} value={m.id_path}>{displayName(m)}</option>)}
                </select>
              </label>
              <p className="jg-sm jg-muted">{year}年度の予算集計に現れる府省から選べます。{!center ? "最初は記録された事業が最も多い府省を表示します。" : ""}</p>
            </div>
          ) : null}
          {!unavailable && !idPath && overview.status === "loading" ? <Loading label="探索の入口を読み込み中" /> : null}
          {!unavailable && !idPath && data ? <Empty>入口となる府省が記録されていません。</Empty> : null}
          {!unavailable && idPath && detail.status === "loading" ? <Loading label="対象を読み込み中" /> : null}
          {detail.status === "error" ? <ErrorBox>対象をいま取得できません。ページを再読み込みするか、別の府省を選んでください。</ErrorBox> : null}
          {idPath && detail.status === "ready" && detail.data === null ? <Empty>この対象は見つかりませんでした。別の府省を選んでください。</Empty> : null}
          {entity && idPath ? (
            <>
              <div className="jg-row jg-row--between">
                <h2 className="jg-h2">{displayName(entity)}のつながり</h2>
                <a className="jg-btn" href={routeToHash({ name: "entity", idPath })}>属性・一次資料を詳しく見る →</a>
              </div>
              <GraphView key={idPath} center={entity} params={params}
                onParamsChange={(next) => replaceExploreParams(idPath, next)}
                onRecenter={(next) => { location.hash = exploreHash(next, { ...params, selected: undefined, types: [], predicates: [] }); }}
                onUseAsPathStart={(from) => navigate({ name: "path", from })} />
              <Caveat>この対象から深さ{params.depth}の範囲を表示しています。KG全体ではありません。{params.layout === "organic" ? "点の大きさは取得した関係の本数です。名前を読むには「構造」または表を使えます。" : ""}記録がないことは、現実に関係がないことを意味しません。</Caveat>
            </>
          ) : null}
        </div>
      </Band>
      <Band wide sunken ruled><Discovery data={data} /></Band>
    </>
  );
}
