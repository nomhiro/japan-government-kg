// 経路画面(#/path?from=&to=)。旧画面(views/path.ts)の置き換え。
//
// **旧画面の欠陥**: 事業ページのボタンからしか到達できず、結果が素のテキスト
// だった。URL共有で開いたときも`id_path`をそのまま「選択中: …」に出していて
// 読めなかった。ここでは`EntityPicker`(型バッジ+名前のカード)を使い、
// URLの`from`/`to`は`/entity`から表示名を引いて出す。
import { useEffect, useState, type JSX } from "react";
import type { PathResponse } from "../../api/client";
import { apiUnavailableReason, entityDetail, findPath } from "../../api/client";
import { PATH_FANOUT_LIMIT, PATH_MAX_DEPTH, PATH_VISIT_BUDGET } from "../../api/limits";
import { orNullOn404, useApiQuery, type QueryState } from "../../api/useApiQuery";
import { Band, ErrorBox, Loading, Section, SourceNote, TypeBadge } from "../../components/ui";
import { describePathResult } from "../../format";
import { predicateLabel } from "../../labels";
import { navigate } from "../../router";
import { EntityPicker, type EntityPickerValue } from "../search/EntityPicker";
import "./path.css";
import { displayName } from "../../lib/display-name";

/** `id_path`を`/entity`から解決して`EntityPickerValue`に写す(URL共有で開いたときの表示名解決)。 */
function useResolvedEntity(idPath: string | undefined): QueryState<EntityPickerValue | null> {
  return useApiQuery(idPath ?? null, async (): Promise<EntityPickerValue | null> => {
    if (!idPath) return null;
    const detail = await orNullOn404(entityDetail(idPath));
    if (!detail) return null;
    return { idPath: detail.id_path, type: detail.type, label: detail.label };
  });
}

export function PathPage({ from, to }: { from?: string; to?: string }): JSX.Element {
  const fromResolved = useResolvedEntity(from);
  const toResolved = useResolvedEntity(to);

  // 利用者がピッカーで選び直した値(URLの値を上書きする)。`from`/`to`が
  // (別の場所からのリンク等で)変わったら、古い上書きを持ち越さない。
  const [start, setStart] = useState<EntityPickerValue | null>(null);
  const [goal, setGoal] = useState<EntityPickerValue | null>(null);
  useEffect(() => setStart(null), [from]);
  useEffect(() => setGoal(null), [to]);

  // **`.data !== undefined`も確かめる**(`SearchPage.tsx`の`readyData`と同じ
  // 理由): `useApiQuery`は`key`が`null`のときの初期値として型を偽って
  // `{status:"ready", data: undefined}`を返す。ここを見落とすと、404
  // (本当の`null`)と「まだ解決していない」(初期値の`undefined`)を
  // 取り違える。
  //
  // **`from`/`to`が今も真であることも確かめる(実ブラウザ確認で見つけた
  // 欠陥)。** `useApiQuery`は`key`が非nullから`null`に変わっても、
  // 直前に取れていた`data`をクリアしない(`useEffect`は`key===null`だと
  // 何もしないまま戻るだけ)。そのため`to`が一度解決された後にURLから
  // 消えても、`toResolved.data`は古い解決結果を持ち続ける——`to &&`の
  // ガードを外すと、終点を外したはずなのに古い終点のカードが残る。
  const effectiveStart =
    start ??
    (from && fromResolved.status === "ready" && fromResolved.data !== undefined ? fromResolved.data : null);
  const effectiveGoal =
    goal ?? (to && toResolved.status === "ready" && toResolved.data !== undefined ? toResolved.data : null);

  const [submitted, setSubmitted] = useState<{ from: string; to: string } | null>(
    from && to ? { from, to } : null,
  );
  useEffect(() => {
    setSubmitted(from && to ? { from, to } : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [from, to]);

  const pathKey = submitted ? `${submitted.from}::${submitted.to}` : null;
  const pathState = useApiQuery(pathKey, () =>
    findPath(submitted!.from, submitted!.to, {
      max_depth: PATH_MAX_DEPTH.default,
      visit_budget: PATH_VISIT_BUDGET.default,
      fanout_limit: PATH_FANOUT_LIMIT.default,
    }),
  );

  const unavailable = apiUnavailableReason();
  if (unavailable) {
    return (
      <Band full>
        <Section title="経路">
          <ErrorBox>経路探索は準備中です。{unavailable}</ErrorBox>
        </Section>
      </Band>
    );
  }

  function handleSubmit(): void {
    if (!effectiveStart || !effectiveGoal) return;
    navigate({ name: "path", from: effectiveStart.idPath, to: effectiveGoal.idPath });
    setSubmitted({ from: effectiveStart.idPath, to: effectiveGoal.idPath });
  }

  return (
    <Band full>
      <Section
        title="経路を探す"
        note={
          <span>
            2つのエンティティ間のつながりを探します(例: 法令↔法人)。深さ{PATH_MAX_DEPTH.default}
            ・訪問予算{PATH_VISIT_BUDGET.default}件・分岐上限{PATH_FANOUT_LIMIT.default}件までで探索します。
          </span>
        }
      >
        <div className="jg-path-form">
          {from && fromResolved.status === "loading" && !start ? (
            <Loading label="始点を解決中" />
          ) : (
            <EntityPicker
              label="始点"
              placeholder="法令・府省・法人・予算事業などを検索"
              selected={effectiveStart}
              onChange={setStart}
              notFoundHint={
                from && fromResolved.status === "ready" && !fromResolved.data && !start
                  ? "URLで指定された始点が見つかりませんでした。検索してください。"
                  : undefined
              }
            />
          )}
          {to && toResolved.status === "loading" && !goal ? (
            <Loading label="終点を解決中" />
          ) : (
            <EntityPicker
              label="終点"
              placeholder="法令・府省・法人・予算事業などを検索"
              selected={effectiveGoal}
              onChange={setGoal}
              notFoundHint={
                to && toResolved.status === "ready" && !toResolved.data && !goal
                  ? "URLで指定された終点が見つかりませんでした。検索してください。"
                  : undefined
              }
            />
          )}
        </div>

        <p>
          <button
            type="button"
            className="jg-btn jg-btn--primary"
            disabled={!effectiveStart || !effectiveGoal}
            onClick={handleSubmit}
          >
            探す
          </button>
        </p>

        <div className="jg-path-result">
          {!submitted ? null : pathState.status === "error" ? (
            <ErrorBox>探索に失敗しました: {pathState.error.message}</ErrorBox>
          ) : pathState.status !== "ready" || pathState.data === undefined ? (
            // `status==="loading"`だけでなく、`key`が`null`から実の値に変わった
            // 直後の1レンダー(`status==="ready"`だが`data`がまだ初期値の
            // `undefined`)もここに含める——本当の404(`data===null`)と混同しない。
            <Loading label="探索中" />
          ) : pathState.data === null ? (
            <ErrorBox>始点または終点のエンティティが見つかりませんでした。</ErrorBox>
          ) : (
            <PathResultView res={pathState.data} />
          )}
        </div>
      </Section>
    </Band>
  );
}

function PathResultView({ res }: { res: PathResponse }): JSX.Element {
  const description = describePathResult(res);

  if (description.kind === "found") {
    return (
      <div className="jg-stack jg-stack--3">
        <p className="jg-sm jg-muted">
          経路が見つかりました({res.nodes.length}ノード・訪問{res.visited}件・深さ{res.searched_depth})
          {res.undirected ? "。辺の向きを無視して探索した経路を含みます。" : ""}
        </p>
        <div className="jg-path-chain" aria-label="見つかった経路">
          {res.nodes.map((node, i) => {
            const edge = res.edges[i];
            return (
              <div className="jg-path-chain__item" key={node.id}>
                <div className="jg-path-node">
                  <TypeBadge type={node.type} size="sm" />
                  <a href={`#/entity/${node.id_path}`}>{displayName(node)}</a>
                </div>
                {edge ? (
                  <div className="jg-path-hop">
                    <span className="jg-path-hop__arrow" aria-hidden="true">
                      {edge.source === node.id ? "→" : "←"}
                    </span>
                    <span className="jg-path-hop__predicate">{predicateLabel(edge.predicate)}</span>
                    <SourceNote graphs={res.graphs} onlyGraphs={[edge.graph]} />
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  if (description.kind === "not-found-exhaustive") {
    return (
      <ErrorBox>
        経路は存在しません(深さ{res.max_depth}以内・訪問予算{res.visit_budget}件まで探索を尽くしました)。
      </ErrorBox>
    );
  }

  return (
    <div className="jg-stack jg-stack--2">
      <p>この深さ・この探索量では見つかりませんでした。「存在しない」とは言えません。</p>
      {description.reasons.length > 0 ? (
        <ul className="jg-sm jg-muted jg-path-reasons">
          {description.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
