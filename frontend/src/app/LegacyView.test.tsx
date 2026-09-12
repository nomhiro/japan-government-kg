// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LegacyView, type LegacyMount } from "./LegacyView";

// vitest は globals 無しなので Testing Library の自動 cleanup は効かない。明示する。
afterEach(cleanup);

describe("LegacyView(旧 innerHTML ビューを React ツリーに載せる橋)", () => {
  it("マウント時に mount(el) を1回呼び、el は DOM 上の要素である", () => {
    const mount = vi.fn<LegacyMount>((el) => {
      el.innerHTML = "<p>旧ビュー</p>";
    });
    const { container } = render(<LegacyView mount={mount} />);
    expect(mount).toHaveBeenCalledTimes(1);
    expect(container.querySelector("p")?.textContent).toBe("旧ビュー");
    expect(document.body.contains(mount.mock.calls[0]![0])).toBe(true);
  });

  it("アンマウント時に controller.destroy() を呼び、描いた内容を消す", () => {
    const destroy = vi.fn();
    const mount: LegacyMount = (el) => {
      el.innerHTML = "<canvas></canvas>";
      return { destroy };
    };
    const { unmount, container } = render(<LegacyView mount={mount} />);
    expect(container.querySelector("canvas")).not.toBeNull();
    unmount();
    expect(destroy).toHaveBeenCalledTimes(1);
  });

  it("controller を返さない旧ビュー(destroy を持たない)でもアンマウントで例外にならない", () => {
    const mount: LegacyMount = (el) => {
      el.textContent = "戻り値なし";
    };
    const { unmount } = render(<LegacyView mount={mount} />);
    expect(() => unmount()).not.toThrow();
  });

  it("key が変わると破棄→再マウントされる(ルート遷移ごとに描き直す現行挙動と同じ)", () => {
    const destroy = vi.fn();
    const mount = vi.fn<LegacyMount>(() => ({ destroy }));
    const { rerender } = render(<LegacyView key="#/" mount={mount} />);
    rerender(<LegacyView key="#/chat" mount={mount} />);
    expect(destroy).toHaveBeenCalledTimes(1);
    expect(mount).toHaveBeenCalledTimes(2);
  });

  it("key が同じなら再描画(props の関数が変わっても)で mount を呼び直さない", () => {
    const mount1 = vi.fn<LegacyMount>(() => undefined);
    const mount2 = vi.fn<LegacyMount>(() => undefined);
    const { rerender } = render(<LegacyView key="#/" mount={mount1} />);
    rerender(<LegacyView key="#/" mount={mount2} />);
    expect(mount1).toHaveBeenCalledTimes(1);
    expect(mount2).not.toHaveBeenCalled();
  });
});
