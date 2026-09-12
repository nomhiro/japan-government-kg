// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";

// オムニボックスは実APIを叩くので、この層のテストでは検索だけを差し替える。
// 返す形は本番の応答(.superpowers/apisamples/search.json)と同じ。
vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return {
    ...actual,
    search: vi.fn(async (q: string) => ({
      query: q,
      limit: 8,
      truncated: true,
      results: [
        {
          id: "https://jgkg.norr-tech.com/id/budget/2025/2841",
          id_path: "budget/2025/2841",
          type: "BudgetProject",
          label: "①国民年金基金等給付費負担金　／②存続厚生年金基金等未納掛金等交付金",
          summary: "2025年度・厚生労働省",
        },
        {
          id: "https://jgkg.norr-tech.com/id/org/6000012070001",
          id_path: "org/6000012070001",
          type: "Ministry",
          label: "厚生労働省",
          summary: "東京都 千代田区",
        },
      ],
    })),
  };
});

// vitest は globals 無しなので Testing Library の自動 cleanup は効かない。明示する
// (残った <main> が2つあると getByRole("main") が複数一致で落ちる)。
afterEach(() => {
  cleanup();
  window.location.hash = "";
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

describe("AppShell(共通シェル)", () => {
  it("ランドマーク header / nav / main / footer を持ち、本文を main に描く", () => {
    render(
      <AppShell route={{ name: "chat" }}>
        <p>本文</p>
      </AppShell>,
    );
    expect(screen.getByRole("banner")).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "主要なページ" })).toBeTruthy();
    expect(screen.getByRole("main").textContent).toContain("本文");
    expect(screen.getByRole("contentinfo")).toBeTruthy();
  });

  it("いまのルートに対応するナビ項目だけ aria-current=page(top)", () => {
    render(
      <AppShell route={{ name: "top" }}>
        <p />
      </AppShell>,
    );
    expect(screen.getByRole("link", { name: "全体を見る" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "経路" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("link", { name: "聞く" }).getAttribute("aria-current")).toBeNull();
  });

  it("エンティティ画面では「つながりを辿る」が現在ページになる", () => {
    render(
      <AppShell route={{ name: "entity", idPath: "org/6000012070001" }}>
        <p />
      </AppShell>,
    );
    expect(
      screen.getByRole("link", { name: "つながりを辿る" }).getAttribute("aria-current"),
    ).toBe("page");
    expect(screen.getByRole("link", { name: "全体を見る" }).getAttribute("aria-current")).toBeNull();
  });

  it("オムニボックスは検索ルートでも出す(常設。旧実装は検索画面で隠していた)", () => {
    render(
      <AppShell route={{ name: "search", q: "年金" }}>
        <p />
      </AppShell>,
    );
    expect(screen.getByRole("searchbox", { name: "府省・事業・法人・法令を探す" })).toBeTruthy();
  });

  it("オムニボックスで Enter すると #/search?q=… に遷移する(値は encodeURIComponent 1回)", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    await user.type(screen.getByRole("searchbox"), "年金{Enter}");
    expect(window.location.hash).toBe("#/search?q=%E5%B9%B4%E9%87%91");
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

  it("候補は本物のリンクで、キーボード(↓)で辿れる", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    await user.type(screen.getByRole("searchbox"), "年金");
    // デバウンス後に候補が出る。
    // 「厚生労働省」は事業の要約(2025年度・厚生労働省)にも出るので、
    // 役割と名前だけでは2件一致する。href で1件に絞る。
    const ministry = await waitFor(
      () => {
        const links = screen.getAllByRole("link", { name: /厚生労働省/ });
        const hit = links.find((l) => l.getAttribute("href") === "#/entity/org/6000012070001");
        if (!hit) throw new Error("府省の候補がまだ出ていない");
        return hit;
      },
      { timeout: 2000 },
    );
    expect(ministry.getAttribute("data-omni-item")).not.toBeNull();
    await user.keyboard("{ArrowDown}");
    // ↓で実際にフォーカスが候補へ移る(見た目だけの選択にしない)。
    await waitFor(() => {
      const active = document.activeElement as HTMLElement | null;
      expect(active?.getAttribute("data-omni-item")).not.toBeNull();
    });
  });

  it("候補を押すとそのエンティティへ遷移し、候補が閉じる", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "chat" }}>
        <p />
      </AppShell>,
    );
    await user.type(screen.getByRole("searchbox"), "年金");
    const hit = await waitFor(
      () => {
        const links = screen.getAllByRole("link", { name: /厚生労働省/ });
        const found = links.find((l) => l.getAttribute("href") === "#/entity/org/6000012070001");
        if (!found) throw new Error("府省の候補がまだ出ていない");
        return found;
      },
      { timeout: 2000 },
    );
    await user.click(hit);
    expect(window.location.hash).toBe("#/entity/org/6000012070001");
    // 候補のパネルが閉じる(候補の項目が1つも残らない)。
    expect(document.querySelectorAll("[data-omni-item]").length).toBe(0);
  });

  it("「本文へ移動」を押すと main にフォーカスが移る(href=\"#main\" を使わない——ハッシュルータが404画面へ飛ぶ)", async () => {
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

  it("ナビの項目を押すとそのルートへ遷移する", async () => {
    const user = userEvent.setup();
    render(
      <AppShell route={{ name: "top" }}>
        <p />
      </AppShell>,
    );
    await user.click(screen.getByRole("link", { name: "データとAPI" }));
    expect(window.location.hash).toBe("#/data");
  });
});

describe("タブの名前(document.title)", () => {
  it("ルートごとに変わる(全画面が同じ名前だと、タブを並べて比べられない)", () => {
    render(
      <AppShell route={{ name: "top" }}>
        <p>本文</p>
      </AppShell>,
    );
    expect(document.title).toBe("全体を見る — 日本政府ナレッジグラフ");

    cleanup();
    render(
      <AppShell route={{ name: "search", q: "年金" }}>
        <p>本文</p>
      </AppShell>,
    );
    expect(document.title).toBe("「年金」の検索結果 — 日本政府ナレッジグラフ");
  });

  it("エンティティ画面のときは題を書かない(EntityPageが表示名で書くため)", () => {
    document.title = "厚生労働省 — 日本政府ナレッジグラフ";
    render(
      <AppShell route={{ name: "entity", idPath: "org/6000012070001" }}>
        <p>本文</p>
      </AppShell>,
    );
    expect(document.title).toBe("厚生労働省 — 日本政府ナレッジグラフ");
  });
});
