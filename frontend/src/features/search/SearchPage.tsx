// 検索結果画面(#/search?q=…)。旧画面(views/search.ts)の置き換え。
//
// **旧画面の欠陥(裁定なし。利用者評価「今の状態は全然ダメ」からの直接の
// やり直し)**: 結果が`<li>`+clickで、キーボードで選べなかった。型で絞れず、
// 「もっと見る」も無かった(APIは`limit`最大100を受け付けるのに既定20しか
// 使っていなかった)。この3つをここで直す。
import { useEffect, useMemo, useState, type JSX } from "react";
import { apiUnavailableReason, search, type SearchHit, type SearchResponse } from "../../api/client";
import { SEARCH_LIMIT } from "../../api/limits";
import { useApiQuery, useDebounced, type QueryState } from "../../api/useApiQuery";
import { Band, ErrorBox, Loading, Section, Truncation, TypeBadge } from "../../components/ui";
import { typeLabel } from "../../labels";
import { axisColorVarForType } from "../../lib/ontology-view";
import "./search.css";
import { displayName } from "../../lib/display-name";

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
function readyData(state: QueryState<SearchResponse>): SearchResponse | undefined {
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
  const [query, setQuery] = useState(q);
  const debounced = useDebounced(query, DEBOUNCE_MS);
  const [limit, setLimit] = useState<number>(SEARCH_LIMIT.default);
  const [activeTypes, setActiveTypes] = useState<ReadonlySet<string>>(new Set());

  const trimmed = debounced.trim();

  // 検索語が変わったら、前の検索語に対する絞り込み・「もっと表示」状態を持ち越さない。
  useEffect(() => {
    setLimit(SEARCH_LIMIT.default);
    setActiveTypes(new Set());
  }, [trimmed]);

  const key = trimmed ? `${trimmed}::${limit}` : null;
  const state = useApiQuery(key, () => search(trimmed, limit));
  const data = readyData(state);

  const presentTypes = useMemo(() => (data ? typesPresentIn(data.results) : []), [data]);

  function toggleType(t: string): void {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }

  const visibleHits: SearchHit[] = data
    ? activeTypes.size === 0
      ? data.results
      : data.results.filter((h) => activeTypes.has(h.type))
    : [];

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
