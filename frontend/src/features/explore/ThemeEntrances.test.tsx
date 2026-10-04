// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SearchResponse } from "../../api/client";
import { ThemeEntrances } from "./ThemeEntrances";

const fixture = JSON.parse(readFileSync(resolve(process.cwd(), "../.superpowers/apisamples/search.json"), "utf8")) as SearchResponse;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("活動・制度・組織の入口", () => {
  it("APIの型別に入口を出し、名称から関与を断定せず、人物の未収録を示す", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(fixture))));
    render(<ThemeEntrances />);
    const law = fixture.results.find((r) => r.type === "Law")!;
    await screen.findByRole("link", { name: `${law.label} →` });
    for (const [title, type] of [["活動・事業", "BudgetProject"], ["制度・法令", "Law"], ["組織・行政機関", "Organization"]]) {
      const hit = fixture.results.find((r) => r.type === type)!;
      const group = screen.getByRole("region", { name: title });
      expect(within(group).getByRole("link", { name: `${hit.label} →` }).getAttribute("href")).toContain(encodeURIComponent(hit.id_path));
    }
    expect(screen.getByText(/テーマとの関与を示すものではありません/)).toBeTruthy();
    expect(screen.getByText(/人物・役職・会議・発言.*未収録/)).toBeTruthy();
    expect(screen.getByText(/先頭20件/)).toBeTruthy();
  });

  it("テーマを変えると前の候補を消し、取得範囲の0件を全KGの不在と混同しない", async () => {
    let finish!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes(encodeURIComponent("教育"))
      ? new Promise<Response>((resolve) => { finish = resolve; })
      : new Response(JSON.stringify(fixture))));
    render(<ThemeEntrances />);
    const law = fixture.results.find((r) => r.type === "Law")!;
    await screen.findByRole("link", { name: `${law.label} →` });
    fireEvent.click(screen.getByRole("button", { name: "教育" }));
    expect(screen.queryByRole("link", { name: `${law.label} →` })).toBeNull();
    finish(new Response(JSON.stringify({ results: [], limit: 100, truncated: false })));
    expect(await screen.findAllByText("取得した一覧に一致する記録がありません。")).toHaveLength(3);
  });

  it("一覧取得の失敗から再取得できる", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("error", { status: 503 })).mockResolvedValue(new Response(JSON.stringify(fixture)));
    vi.stubGlobal("fetch", fetcher);
    render(<ThemeEntrances />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "一覧を再取得" }));
    await screen.findByRole("link", { name: `${fixture.results[0]!.label} →` });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
