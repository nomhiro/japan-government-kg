import { useState, type FormEvent, type JSX } from "react";
import { navigate } from "../../router";

// 常設の検索欄(仕様 §2.1)。Phase 0 では「Enter で #/?q= に遷移する」だけ。
// 候補のドロップダウンは Phase 1(#/search)で足す。
export function Omnibox(): JSX.Element {
  const [q, setQ] = useState("");
  function onSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const trimmed = q.trim();
    if (!trimmed) return;
    navigate({ name: "search", q: trimmed });
  }
  return (
    <form className="jgkg-omnibox" role="search" onSubmit={onSubmit}>
      <input
        type="search"
        className="jgkg-omnibox-input"
        aria-label="府省・事業・法人・法令を探す"
        placeholder="府省・事業・法人・法令を探す"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
    </form>
  );
}
