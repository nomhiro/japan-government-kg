// 検索して1件選ぶ部品。検索結果画面(SearchPage)と経路画面(PathPage)の両方から
// 使う共通部品(team-leadの指示: 「両方からimportする」)。
//
// **候補は本物の`<button>`にする**(旧`views/path.ts`の`mountPicker`と同じ
// 発想の焼き直しだが、クリックだけに頼らない)。ボタンはTabで自然に順番に
// フォーカスが移り、Enter/Spaceで押せる——`role="option"`のような専用の
// ARIAパターンを自作して`aria-activedescendant`を半端に実装するより、
// ネイティブな要素で正しく動かすほうが確実(team-leadの指示)。
import { useId, useState, type JSX } from "react";
import { search, type SearchHit } from "../../api/client";
import { useApiQuery, useDebounced } from "../../api/useApiQuery";
import { TypeBadge } from "../../components/ui";
import "./search.css";
import { displayName } from "../../lib/display-name";

export interface EntityPickerValue {
  readonly idPath: string;
  readonly type: string;
  readonly label: string | null;
}

export interface EntityPickerProps {
  /** 見出し(「始点」「終点」等)。 */
  readonly label: string;
  readonly placeholder?: string;
  readonly selected: EntityPickerValue | null;
  readonly onChange: (value: EntityPickerValue | null) => void;
  /** URLから渡された初期値をまだ解決している間。 */
  readonly busy?: boolean;
  /** 解決できなかった等、検索欄の上に出す短い説明。 */
  readonly notFoundHint?: string;
}

const PICKER_LIMIT = 10;
const DEBOUNCE_MS = 300;

export function EntityPicker({
  label,
  placeholder,
  selected,
  onChange,
  busy,
  notFoundHint,
}: EntityPickerProps): JSX.Element {
  const inputId = useId();
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, DEBOUNCE_MS);
  const trimmed = debounced.trim();

  const key = !selected && trimmed ? trimmed : null;
  const state = useApiQuery(key, () => search(trimmed, PICKER_LIMIT));

  if (busy) {
    return (
      <div className="jg-picker">
        <span className="jg-eyebrow">{label}</span>
        <p className="jg-sm jg-muted">解決中…</p>
      </div>
    );
  }

  if (selected) {
    return (
      <div className="jg-picker">
        <span className="jg-eyebrow">{label}</span>
        <div className="jg-row jg-picker__selected">
          <TypeBadge type={selected.type} size="sm" />
          <span className="jg-picker__label">{displayName(selected)}</span>
          <button type="button" className="jg-btn jg-btn--quiet jg-btn--sm" onClick={() => onChange(null)}>
            変更
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="jg-picker">
      <label className="jg-eyebrow" htmlFor={inputId}>
        {label}
      </label>
      {notFoundHint ? <p className="jg-sm jg-muted">{notFoundHint}</p> : null}
      <input
        id={inputId}
        type="search"
        className="jg-picker__input"
        placeholder={placeholder ?? "名前で検索"}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {/* **`state.data !== undefined`も必ず確かめる**: `useApiQuery`は`key`が
          `null`から実の文字列に変わった直後の1レンダー分だけ、まだ
          マウント時の初期値(`key===null`用の`{status:"ready", data:undefined}`)
          を返す(`useEffect`が走ってloadingに切り替わる前)。ここで
          `state.status==="ready"`だけを見ると、その1レンダーで
          `state.data.results`が未定義エラーになる。 */}
      {trimmed && state.status === "loading" ? <p className="jg-sm jg-muted">検索中…</p> : null}
      {trimmed && state.status === "error" ? (
        <p className="jg-sm jg-muted">検索に失敗しました。</p>
      ) : null}
      {trimmed && state.status === "ready" && state.data !== undefined ? (
        state.data.results.length === 0 ? (
          <p className="jg-sm jg-muted">見つかりませんでした。</p>
        ) : (
          <ul className="jg-picker__results">
            {state.data.results.map((hit: SearchHit) => (
              <li key={hit.id_path}>
                <button
                  type="button"
                  className="jg-picker__hit"
                  onClick={() => onChange({ idPath: hit.id_path, type: hit.type, label: hit.label })}
                >
                  <TypeBadge type={hit.type} size="sm" />
                  <span>{displayName(hit)}</span>
                </button>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}
