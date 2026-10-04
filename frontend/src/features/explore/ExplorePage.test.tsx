// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { OverviewResponse } from "../../api/client";
import { entityMinistry, nbhdMinistry } from "../graph/test-fixtures";
import { ExplorePage } from "./ExplorePage";

const data = JSON.parse(readFileSync(resolve(process.cwd(), "../.superpowers/apisamples/overview.json"), "utf8")) as OverviewResponse;
afterEach(() => { cleanup(); vi.unstubAllGlobals(); location.hash = ""; });
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url.endsWith("/overview") ? data : url.includes("/search?") ? { results: [], truncated: false, limit: 100 } : url.includes("/neighborhood/") ? nbhdMinistry() : entityMinistry()
  ), { headers: { "Content-Type": "application/json" } })));
});
describe("検索を前提にしない探索", () => {
  it("検索なしで収録府省を選べ、最初の対象のグラフを表示する", async () => {
    render(<ExplorePage />);
    await screen.findByRole("button", { name: "府省: 厚生労働省" });
    expect(screen.getByRole("combobox", { name: "入口の府省" })).toBeTruthy();
    expect(screen.getByText(/最初は記録された事業が最も多い/)).toBeTruthy();
    expect(screen.getByText(/KG全体ではありません/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "構造" }).getAttribute("aria-pressed")).toBe("true");
    expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes("/search?q="))).toBe(true);
  });
  it("府省を選ぶとAPI応答のid_pathで探索URLへ進む", async () => {
    render(<ExplorePage />);
    const select = await screen.findByRole("combobox", { name: "入口の府省" });
    const other = data.ministries.find((m) => m.id_path !== nbhdMinistry().center.id_path)!;
    fireEvent.change(select, { target: { value: other.id_path } });
    await waitFor(() => expect(location.hash).toContain(encodeURIComponent(other.id_path)));
  });
  it("全体集計が失敗しても、直接指定された対象のグラフを開ける", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/overview")
      ? new Response("unavailable", { status: 503 })
      : new Response(JSON.stringify(url.includes("/search?") ? { results: [], truncated: false, limit: 100 } : url.includes("/neighborhood/") ? nbhdMinistry() : entityMinistry()))));
    render(<ExplorePage center={nbhdMinistry().center.id_path} />);
    await screen.findByRole("button", { name: "府省: 厚生労働省" });
    expect(screen.getByText(/府省の一覧をいま取得できません/)).toBeTruthy();
  });
});
