// 検索結果画面(#/search?q=…)。
//
// **一覧ではなくグラフを主にする(裁定B109)。** 利用者の評価:
//   検索した後に一覧がでるのではなくて、検索で引っかかった情報をGraph表示した
//   ほうがいい。ただの一覧表示が微妙。全体を俯瞰してみたいのに、一つの情報の
//   関連性しか見れない。
//
// 一覧は「20件の名前」を返すだけで、ヒットどうしの関係を何も言わない。
// ここでは各ヒットの深さ1の近傍を並列に取り、合算して1枚のレーン流れ図にする
// (畳み方と実測値は `search-graph.ts`)。**一覧は消さずに折り畳んで残す**
// ——名前で拾いたいとき、キーボードで確実に辿りたいときに要る。
import { useEffect, useMemo, useState, type JSX } from "react";
import {
  apiUnavailableReason,
  neighborhood,
  search,
  type NeighborhoodResponse,
  type SearchHit,
  type SearchResponse,
} from "../../api/client";
import { SEARCH_LIMIT } from "../../api/limits";
import { useApiQuery, useDebounced, type QueryState } from "../../api/useApiQuery";
import { useRoute } from "../../app/useRoute";
import { Band, Caveat, ErrorBox, Loading, Section, Truncation, TypeBadge } from "../../components/ui";
import { GraphView } from "../graph/GraphView";
import { typeLabel } from "../../labels";
import { displayName } from "../../lib/display-name";
import { axisColorVarForType } from "../../lib/ontology-view";
import { navigate, parseGraphParams, replaceSearchGraphParams } from "../../router";
import { buildSearchGraph } from "./search-graph";
import "./search.css";

// 検索対象の型(`src/jgkg/api/queries.py`の`_SEARCHABLE_TYPES`と同じ6種)。
// APIはこの一覧自体を応答に含まないため、ここに固定する——表示名は必ず
// `typeLabel`で引く(手書きの日本語対応表をここに作らない)。
const SEARCHABLE_TYPE_NAMES = [
  "Ministry",
  "GovernmentOrgan",
  "AbolishedGovernmentOrgan",
  "Organization",
  "Law",
  "BudgetProject",
] as const;

const DEBOUNCE_MS = 300;

/** 合算グラフを作るために取る近傍の深さ。 */
const NEIGHBORHOOD_DEPTH = 1;

/**
 * `state`から実データだけを取り出す(`ready`かつ`data`が本物のとき)。
 *
 * **`state.status === "ready"`だけでは判定できない**: `useApiQuery`は
 * `key`が`null`(検索語が空)のときの初期値として`{status:"ready",
 * data: undefined as T}`を返す——型は`T`と嘘をついているが、実行時には
 * `undefined`である。`key`が`null`から実の検索語に変わった直後の1レンダー分
 * (`useEffect`が走ってloadingに切り替わる前)は、この古い初期値がまだ
 * 残っている。ここで実行時に`undefined`を弾くことで、その1レンダーで
 * `undefined.results`のような例外を起こさない。
 */
function readyData<T>(state: QueryState<T>): T | undefined {
  return state.status === "ready" && state.data !== undefined ? state.data : undefined;
}

/** 現在の結果に実際に現れた型を、最初に出現した順で返す(重複なし)。 */
function typesPresentIn(hits: readonly SearchHit[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const hit of hits) {
    if (!seen.has(hit.type)) {
      seen.add(hit.type);
      ordered.push(hit.type);
    }
  }
  return ordered;
}

export function SearchPage({ q }: { q: string }): JSX.Element {
  // ハッシュの変化(グラフの並べ方・軸の絞り込み・選択)を購読するために呼ぶ。
  useRoute();

  const [query, setQuery] = useState(q);
  const debounced = useDebounced(query, DEBOUNCE_MS);
  const [limit, setLimit] = useState<number>(SEARCH_LIMIT.default);
  const [activeTypes, setActiveTypes] = useState<ReadonlySet<string>>(new Set());

  const trimmed = debounced.trim();
  const graphParams = parseGraphParams(location.hash);

  // 検索語が変わったら、前の検索語に対する絞り込み・「もっと表示」状態を持ち越さない。
  useEffect(() => {
    setLimit(SEARCH_LIMIT.default);
    setActiveTypes(new Set());
  }, [trimmed]);

  const key = trimmed ? `${trimmed}::${limit}` : null;
  const state = useApiQuery(key, () => search(trimmed, limit));
  const data: SearchResponse | undefined = readyData(state);

  const presentTypes = useMemo(() => (data ? typesPresentIn(data.results) : []), [data]);

  const visibleHits: SearchHit[] = useMemo(() => {
    if (!data) return [];
    if (activeTypes.size === 0) return data.results;
    return data.results.filter((h) => activeTypes.has(h.type));
  }, [data, activeTypes]);

  // --- ヒット全件の近傍を1回だけ取る -----------------------------------------
  // **型で絞るたびに取り直さない**(絞り込みは取得済みのものから作り直すだけ)。
  // 本番実測では1件あたり0.03〜0.04秒で、20件でも体感できる待ちにならない。
  const allHits = data?.results ?? [];
  const nbhdKey = allHits.length > 0 ? allHits.map((h) => h.id_path).join("|") : null;
  const nbhdState = useApiQuery(nbhdKey, () =>
    Promise.all(allHits.map((h) => neighborhood(h.id_path, { depth: NEIGHBORHOOD_DEPTH }))),
  );
  const neighborhoods: readonly (NeighborhoodResponse | null)[] | undefined = readyData(nbhdState);

  const graph = useMemo(() => {
    if (!neighborhoods || visibleHits.length === 0) return null;
    const byIdPath = new Map(allHits.map((h, i) => [h.id_path, neighborhoods[i] ?? null]));
    return buildSearchGraph({
      hits: visibleHits,
      neighborhoods: visibleHits.map((h) => byIdPath.get(h.id_path) ?? null),
    });
    // `allHits` は `neighborhoods` と同じ取得に対応する(同じ `nbhdKey`)。
  }, [neighborhoods, visibleHits, allHits]);

  function toggleType(t: string): void {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }

  const unavailable = apiUnavailableReason();
  if (unavailable) {
    return (
      <Band full>
        <Section title="検索">
          <ErrorBox>データ検索は準備中です。{unavailable}</ErrorBox>
        </Section>
      </Band>
    );
  }

  const heading = trimmed ? `「${trimmed}」の検索結果` : "検索";
  const eyebrow = data ? `${data.results.length}件` : undefined;
  const note =
    data && data.truncated ? (
      <span>検索結果が{data.limit}件を超えています。すべては表示していません。</span>
    ) : undefined;

  const isolatedHits = graph ? visibleHits.filter((h) => graph.isolatedHitIds.has(h.id)) : [];

  return (
    <Band full>
      <Section title={heading} eyebrow={eyebrow} note={note}>
        <form className="jg-search-form" role="search" onSubmit={(e) => e.preventDefault()}>
          <input
            type="search"
            className="jg-search-input"
            aria-label="府省・事業・法人・法令を探す"
            placeholder="例: 厚生労働省、年金、令和6年度の予算事業"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
        </form>

        {!trimmed ? (
          <p className="jg-sm jg-muted">探したい語を入力してください。</p>
        ) : state.status === "error" ? (
          <ErrorBox>検索に失敗しました: {state.error.message}</ErrorBox>
        ) : !data ? (
          // `status==="loading"`と、`key`がnullから実の検索語に変わった直後の
          // 1レンダー(`status==="ready"`だが`data`が初期値の`undefined`)の
          // 両方をここでまとめて「検索中」にする(`readyData`参照)。
          <Loading label="検索中" />
        ) : data.results.length === 0 ? (
          <p className="jg-sm jg-muted">
            見つかりませんでした。検索は部分一致で行っており、検索できる型は
            {SEARCHABLE_TYPE_NAMES.map((t) => typeLabel(t)).join("・")}
            の6種類です。支出・年度ごとの予算は件数が非常に多いため、検索の対象には含めていません。
          </p>
        ) : (
          <div className="jg-stack jg-stack--4">
            {presentTypes.length > 1 ? (
              <div className="jg-row jg-row--tight" role="group" aria-label="型で絞り込む">
                {presentTypes.map((t) => {
                  const pressed = activeTypes.size === 0 || activeTypes.has(t);
                  return (
                    <button
                      key={t}
                      type="button"
                      className="jg-chip"
                      aria-pressed={pressed}
                      onClick={() => toggleType(t)}
                    >
                      <span
                        className="jg-chip__dot"
                        aria-hidden="true"
                        style={{ background: axisColorVarForType(t) }}
                      />
                      {typeLabel(t)}
                    </button>
                  );
                })}
              </div>
            ) : null}

            {nbhdState.status === "error" ? (
              <ErrorBox>つながりの取得に失敗しました: {nbhdState.error.message}</ErrorBox>
            ) : !graph ? (
              <Loading label={`${allHits.length}件のつながりを取得中`} />
            ) : (
              <>
                <GraphView
                  center={visibleHits[0]!}
                  supplied={{
                    raw: graph.raw,
                    centerId: graph.centerId,
                    fanoutTruncatedIds: graph.fanoutTruncatedIds,
                    emphasizedIds: graph.hitIds,
                    nodesTruncated: graph.nodesTruncated,
                    edgesTruncated: graph.edgesTruncated,
                  }}
                  showDepth={false}
                  params={graphParams}
                  onParamsChange={(next) => replaceSearchGraphParams(trimmed, next)}
                  onRecenter={(idPath) => navigate({ name: "entity", idPath })}
                  onUseAsPathStart={(idPath) => navigate({ name: "path", from: idPath })}
                />
                <Caveat>
                  太枠は検索でヒットした{visibleHits.length}件です。各件の深さ1のつながりを
                  合わせて描いています。
                  {graph.droppedNodeCount > 0 ? (
                    <>
                      {" "}
                      ヒットどうしを繋ぎえない記録(年度ごとの予算・支出・支出先ブロック・間接経費。
                      いずれも1つの事業にしか属さない){graph.droppedNodeCount}件は、この図から
                      外しています。各件のページを開くと出ます。
                    </>
                  ) : null}
                  {graph.missingNeighborhoodCount > 0 ? (
                    <> つながりを取得できなかった結果が{graph.missingNeighborhoodCount}件あります。</>
                  ) : null}
                </Caveat>

                {isolatedHits.length > 0 ? (
                  <div className="jg-stack jg-stack--2">
                    <span className="jg-eyebrow">つながりの記録がない結果({isolatedHits.length}件)</span>
                    <p className="jg-xs jg-muted">
                      この図の中で他とつながっていません。KGに関係の記録が無いということです
                      (表示していないだけではありません)。
                    </p>
                    <ul className="jg-search-results">
                      {isolatedHits.map((hit) => (
                        <li key={hit.id_path} className="jg-search-hit">
                          <a href={`#/entity/${hit.id_path}`} className="jg-search-hit__link">
                            <TypeBadge type={hit.type} size="sm" />
                            <span className="jg-search-hit__label">{displayName(hit)}</span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            )}

            <details className="jg-search-list">
              <summary>検索結果の一覧({visibleHits.length}件)</summary>
              <ul className="jg-search-results">
                {visibleHits.map((hit) => (
                  <li key={hit.id_path} className="jg-search-hit">
                    <a href={`#/entity/${hit.id_path}`} className="jg-search-hit__link">
                      <TypeBadge type={hit.type} size="sm" />
                      <span className="jg-search-hit__label">{displayName(hit)}</span>
                      {hit.summary ? <span className="jg-search-hit__summary">{hit.summary}</span> : null}
                    </a>
                  </li>
                ))}
              </ul>
            </details>

            <Truncation truncated={data.truncated} limit={data.limit} what="検索結果">
              {limit < SEARCH_LIMIT.max ? (
                <button type="button" className="jg-btn jg-btn--sm" onClick={() => setLimit(SEARCH_LIMIT.max)}>
                  もっと表示(最大{SEARCH_LIMIT.max}件まで)
                </button>
              ) : null}
            </Truncation>
          </div>
        )}
      </Section>
    </Band>
  );
}
