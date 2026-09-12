// @vitest-environment jsdom
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useApiQuery } from "./useApiQuery";

// vitest は globals 無しなので Testing Library の自動 cleanup は効かない。明示する。
afterEach(cleanup);

describe("useApiQuery", () => {
  it("key が非nullなら fetcher を呼び、結果を ready で返す", async () => {
    const fetcher = vi.fn(async () => "結果A");
    const { result } = renderHook(() => useApiQuery("k1", fetcher));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data).toBe("結果A");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("key が変わると呼び直し、新しい結果に入れ替わる", async () => {
    const fetcher = vi.fn(async (k: string) => `結果:${k}`);
    const { result, rerender } = renderHook(({ k }: { k: string }) =>
      useApiQuery(k, () => fetcher(k)),
    { initialProps: { k: "k1" } });
    await waitFor(() => expect(result.current.data).toBe("結果:k1"));
    rerender({ k: "k2" });
    await waitFor(() => expect(result.current.data).toBe("結果:k2"));
  });

  it("**核心**: key が null になったら前の結果を捨てる(古い応答を画面に残さない)", async () => {
    const fetcher = vi.fn(async () => "結果A");
    const { result, rerender } = renderHook(({ k }: { k: string | null }) => useApiQuery(k, fetcher),
      { initialProps: { k: "k1" as string | null } });
    await waitFor(() => expect(result.current.data).toBe("結果A"));

    // 検索語を消した・選択を外した状況。ここで前の応答が残ると、
    // 利用者は「消したのに結果が出ている」画面を見る。
    rerender({ k: null });
    await waitFor(() => expect(result.current.data).toBeUndefined());
    expect(result.current.status).toBe("ready");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("失敗は error で返し、retry しない(503/429を正直に出すため)", async () => {
    const fetcher = vi.fn(async () => {
      throw new Error("503");
    });
    const { result } = renderHook(() => useApiQuery("k1", fetcher));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.message).toBe("503");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
