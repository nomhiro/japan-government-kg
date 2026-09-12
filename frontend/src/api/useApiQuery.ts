// 画面がAPIを読むための小さなフック(裁定B106)。
//
// TanStack Query を入れない理由: 既存コードが手で守っていたレース防止
// (最新の要求だけを描く)と 404→null の規約は、effect の cleanup に
// 1:1で写る。Query の既定 `retry: 3` は `/overview` の503や `/chat` の429を
// 「正直に失敗として出す」方針(裁定B82/B92)と衝突し、無効化設定が必須に
// なる。画面をまたぐキャッシュ共有・再検証が要求として出てきた時点で
// 「データ取得の目的で1つ」入れる —— 戻り型をその時と同じ形にしてある。

import { useEffect, useRef, useState } from "react";
import { ApiError } from "./client";

export type QueryState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "ready"; data: T; error?: undefined }
  | { status: "error"; data?: undefined; error: Error };

/**
 * `key` が変わるたびに `fetcher` を呼び直す。
 *
 * - 古い応答は描かない(`key` を捕まえた世代番号で弾く)
 * - アンマウント後は state を触らない
 * - `fetcher` は `key` から決まるものだけを読むこと(クロージャで毎回
 *   新しい関数になるので、依存には `key` だけを入れる)
 */
export function useApiQuery<T>(key: string | null, fetcher: () => Promise<T>): QueryState<T> {
  const [state, setState] = useState<QueryState<T>>(
    key === null ? { status: "ready", data: undefined as T } : { status: "loading" },
  );
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (key === null) {
      // **`key === null` は「問い合わせない」であって「前の結果を持ち続ける」ではない。**
      // 何もせず抜けると、検索語を消した・選択を外したときに直前の応答が画面に
      // 残り続ける(実装者が SearchPage / EntityPicker / PathPage の3か所で踏み、
      // 1件は実ブラウザでしか出なかった)。結果を空に戻す。
      setState({ status: "ready", data: undefined as T });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    fetcherRef.current().then(
      (data) => {
        if (!cancelled) setState({ status: "ready", data });
      },
      (e: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          error: e instanceof Error ? e : new Error(String(e)),
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key]);

  return state;
}

/** 404 を「値としての null」に変える(`api/client.ts` の規約に合わせる)。 */
export async function orNullOn404<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

/** 入力の変化を遅らせる(検索の打鍵ごとに投げない)。 */
export function useDebounced<T>(value: T, ms: number): T {
  const [held, setHeld] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setHeld(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return held;
}
