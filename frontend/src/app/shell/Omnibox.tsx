// 常設の検索欄(仕様§2.1)。**候補をその場に出し、キーボードで選べる。**
//
// 旧実装の問題: 検索結果が `<li>` + click ハンドラで、Tab でも矢印でも辿れず
// キーボードだけでは1件も開けなかった。ここでは候補を本物の `<a>` にして、
// 矢印キーでの移動は `aria-activedescendant` ではなく**実際にフォーカスを移す**
// 方式にする —— 実フォーカスなら読み上げも既存のフォーカスリングもそのまま効き、
// 「見た目だけ選択されている」状態を作らない。
import { useEffect, useId, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { ApiError, search, type SearchHit } from "../../api/client";
import { SEARCH_LIMIT } from "../../api/limits";
import { useApiQuery, useDebounced } from "../../api/useApiQuery";
import { TypeBadge } from "../../components/ui";
import { navigate, routeToHash } from "../../router";
import { displayName } from "../../lib/display-name";

const DEBOUNCE_MS = 250;
/** 候補は少なく出す。全部見たい人は「すべての結果」へ行く。 */
const SUGGEST_LIMIT = 8;

export function Omnibox(): JSX.Element {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const q = useDebounced(text.trim(), DEBOUNCE_MS);
  const panelId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const state = useApiQuery<SearchHit[] | null>(
    q.length > 0 && open ? `omnibox:${q}` : null,
    async () => {
      const res = await search(q, Math.min(SUGGEST_LIMIT, SEARCH_LIMIT.max));
      return res.results;
    },
  );

  // "/" でどこからでも検索欄へ。入力中の要素にいるときは邪魔しない。
  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent): void {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = document.activeElement;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (el as HTMLElement | null)?.isContentEditable) {
        return;
      }
      e.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function close(): void {
    setOpen(false);
  }

  function goToResults(): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    close();
    navigate({ name: "search", q: trimmed });
  }

  function focusItem(delta: number): void {
    const items = listRef.current?.querySelectorAll<HTMLElement>("[data-omni-item]");
    if (!items || items.length === 0) return;
    const current = [...items].findIndex((el) => el === document.activeElement);
    const next = current === -1 ? (delta > 0 ? 0 : items.length - 1) : current + delta;
    const clamped = Math.max(0, Math.min(items.length - 1, next));
    items[clamped]?.focus();
  }

  function onInputKeyDown(e: KeyboardEvent<HTMLInputElement>): void {
    if (e.key === "Enter") {
      e.preventDefault();
      goToResults();
      return;
    }
    if (e.key === "Escape") {
      close();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      // 候補が描かれた後でフォーカスを移す。
      requestAnimationFrame(() => focusItem(1));
    }
  }

  function onPanelKeyDown(e: KeyboardEvent<HTMLDivElement>): void {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      focusItem(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      focusItem(-1);
    } else if (e.key === "Escape") {
      close();
      inputRef.current?.focus();
    }
  }

  const hits = state.status === "ready" ? (state.data ?? []) : undefined;
  const showPanel = open && text.trim().length > 0;

  return (
    <div
      className="jg-omnibox"
      onBlur={(e) => {
        // パネルの中から外へ出たときだけ閉じる。
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) close();
      }}
    >
      <div className="jg-omnibox__field">
        <svg className="jg-omnibox__icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
        <input
          ref={inputRef}
          type="search"
          className="jg-omnibox__input"
          aria-label="府省・事業・法人・法令を探す"
          placeholder="府省・事業・法人・法令を探す"
          autoComplete="off"
          aria-expanded={showPanel}
          aria-controls={panelId}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onInputKeyDown}
        />
        {text ? (
          <button
            type="button"
            className="jg-omnibox__clear"
            aria-label="検索語を消す"
            onClick={() => {
              setText("");
              inputRef.current?.focus();
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        ) : (
          <span className="jg-omnibox__hint" aria-hidden="true">
            /
          </span>
        )}
      </div>

      {showPanel ? (
        <div
          id={panelId}
          className="jg-omnibox__panel"
          ref={listRef}
          onKeyDown={onPanelKeyDown}
        >
          {state.status === "loading" ? (
            <p className="jg-omnibox__status" role="status">
              探しています…
            </p>
          ) : state.status === "error" ? (
            <p className="jg-omnibox__status">
              検索できませんでした:{" "}
              {state.error instanceof ApiError ? state.error.message : String(state.error)}
            </p>
          ) : hits && hits.length === 0 ? (
            <p className="jg-omnibox__status">見つかりませんでした。</p>
          ) : (
            <>
              <div className="jg-omnibox__list">
                {(hits ?? []).map((hit) => (
                  <a
                    key={hit.id_path}
                    data-omni-item
                    className="jg-omnibox__item"
                    href={routeToHash({ name: "entity", idPath: hit.id_path })}
                    onClick={(e) => {
                      e.preventDefault();
                      close();
                      setText("");
                      navigate({ name: "entity", idPath: hit.id_path });
                    }}
                  >
                    <TypeBadge type={hit.type} size="sm" />
                    <span className="jg-omnibox__label">{displayName(hit)}</span>
                    {hit.summary ? (
                      <span className="jg-omnibox__summary">{hit.summary}</span>
                    ) : null}
                  </a>
                ))}
              </div>
              <button type="button" className="jg-omnibox__more" onClick={goToResults}>
                「{text.trim()}」のすべての結果を見る
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
