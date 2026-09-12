// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { AppShell } from "./AppShell";

// vitest は globals 無しなので Testing Library の自動 cleanup は効かない。明示する
// (残った <main> が2つあると getByRole("main") が複数一致で落ちる)。
afterEach(() => {
  cleanup();
  window.location.hash = "";
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

describe("AppShell(共通シェル)", () => {
  it("ランドマーク header / nav / main を持ち、本文を main に描く", () => {
    render(
      <AppShell route={{ name: "chat" }}>
        <p>本文</p>
      </AppShell>,
    );
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "主要なページ" })).toBeTruthy();
    expect(screen.getByRole("main").textContent).toContain("本文");
  });

  it("いまのルートに対応するナビ項目だけ aria-current=page", () => {
    render(
      <AppShell route={{ name: "path" }}>
        <p />
      </AppShell>,
    );
    expect(screen.getByRole("link", { name: "経路" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "全体を見る" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("link", { name: "聞く" }).getAttribute("aria-current")).toBeNull();
  });

  it("検索ルートではオムニボックスを出さない(旧検索ビューが自分の検索欄を持つため二重にしない)", () => {
    render(
      <AppShell route={{ name: "search", q: "" }}>
        <p />
      </AppShell>,
    );
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("オムニボックスで Enter すると #/?q=… に遷移する(値は encodeURIComponent 1回)", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    const box = screen.getByRole("searchbox", { name: "府省・事業・法人・法令を探す" });
    await user.type(box, "年金{Enter}");
    expect(window.location.hash).toBe("#/?q=%E5%B9%B4%E9%87%91");
  });

  it("空欄で Enter しても遷移しない", async () => {
    const user = userEvent.setup();
    window.location.hash = "#/chat";
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    await user.type(screen.getByRole("searchbox"), "   {Enter}");
    expect(window.location.hash).toBe("#/chat");
  });

  it("「本文へ移動」を押すと main にフォーカスが移る(href=\"#main\" を使わない——ハッシュルータが検索へ遷移してしまう)", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p>本文</p>
      </AppShell>,
    );
    await user.click(screen.getByRole("button", { name: "本文へ移動" }));
    expect(document.activeElement).toBe(screen.getByRole("main"));
    expect(window.location.hash).toBe("");
  });

  it("テーマ切替を押すと <html data-theme> が明示値になり、localStorage に保存される", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
    await user.click(screen.getByRole("button", { name: /表示を.*に切り替える/ }));
    const applied = document.documentElement.getAttribute("data-theme");
    expect(applied === "dark" || applied === "light").toBe(true);
    expect(window.localStorage.getItem("jgkg-theme")).toBe(applied);
  });
});
