// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useRoute } from "./useRoute";

// jsdom は location.hash の代入で hashchange を発火するが、発火のタイミングに
// 依存しないよう、テストでは明示的にも dispatch する(同じ値のスナップショットが
// 2回届いても useSyncExternalStore は再描画しないので無害)。
function setHash(hash: string): void {
  act(() => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

// vitest は globals 無しなので Testing Library の自動 cleanup は効かない。明示する
// (前のレンダーが残ると後のテストが二重購読・複数一致で偽の結果になる)。
afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("useRoute", () => {
  it("初期値は現在の location.hash を parseHash した Route", () => {
    window.location.hash = "#/chat";
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "chat" });
  });

  it("hashchange で Route が更新される", () => {
    window.location.hash = "#/";
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "search", q: "" });
    setHash("#/entity/org/6000012070001");
    expect(result.current).toEqual({ name: "entity", idPath: "org/6000012070001" });
  });

  it("パーセントエンコード済み id_path を再デコードしない(裁定B69/B73 の族)", () => {
    // router.test.ts と同じ実例(廃止府省「厚生省」)。フックを通しても往復が崩れないこと。
    const idPath = "org/abolished/%E5%8E%9A%E7%94%9F%E7%9C%81";
    window.location.hash = `#/entity/${idPath}`;
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "entity", idPath });
  });

  it("アンマウント後は hashchange の購読が外れる", () => {
    window.location.hash = "#/";
    const { result, unmount } = renderHook(() => useRoute());
    unmount();
    // 購読が残っていれば React が警告を出す/例外になる。ここでは例外が出ないことだけ固定する。
    expect(() => setHash("#/chat")).not.toThrow();
    expect(result.current).toEqual({ name: "search", q: "" });
  });
});
