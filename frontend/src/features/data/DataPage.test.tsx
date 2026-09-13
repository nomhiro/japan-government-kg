// @vitest-environment jsdom
//
// 「データとAPI」画面のテスト。**鮮度の表(裁定B111)を足したときに新設した**
// ——それまでこの画面にはテストが無かった(静的な文章とリンクが主で、
// APIの応答から作る部分が無かったため)。
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { OverviewResponse } from "../../api/client";
import { foldFreshness } from "../../lib/freshness";
import { DataPage } from "./DataPage";

// 実APIの応答をそのままフィクスチャに使う(架空の政府データを作らない)。
const fixturePath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../../.superpowers/apisamples/overview.json",
);
const overviewFixture = JSON.parse(readFileSync(fixturePath, "utf-8")) as OverviewResponse;

function fakeResponse(status: number, body: unknown): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("DataPage", () => {
  it("**KGの「データの時点」を表で出し、取得日と記録日を区別する**(裁定B111)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => fakeResponse(200, overviewFixture)));
    render(<DataPage />);

    const heading = await screen.findByRole("heading", { name: "データの時点" });
    const section = heading.closest("div")!;
    const rows = within(section).getAllByRole("row").slice(1); // 見出し行を除く

    // **期待値はフィクスチャから畳んで導く**(件数や日付を手書きしない)。
    const folded = foldFreshness(overviewFixture.release_freshness);
    expect(rows).toHaveLength(folded.length);
    for (const f of folded) {
      const row = rows.find((r) => r.textContent?.includes(f.sourceName))!;
      expect(row).toBeTruthy();
      expect(within(row).getByText(f.asOfDate)).toBeTruthy();
      expect(within(row).getByText(f.dateKind)).toBeTruthy();
    }

    // 2つの日付の意味が違うことを本文で言う(列だけ出しても読めない)。
    expect(screen.getByText(/「取得日」と「記録日」は意味が違います/)).toBeTruthy();
    // 出所のCQ名を出す(裁定B103: 画面の値の出所を辿れる)。
    expect(screen.getByText(/cq10-release-freshness\.rq/)).toBeTruthy();
  });

  it("APIが鮮度を返さない版でも壊れず、節そのものを出さない", async () => {
    const stripped = { ...overviewFixture };
    delete (stripped as { release_freshness?: unknown }).release_freshness;
    vi.stubGlobal("fetch", vi.fn(async () => fakeResponse(200, stripped)));
    render(<DataPage />);

    await screen.findByRole("heading", { name: "ライセンス" });
    expect(screen.queryByRole("heading", { name: "データの時点" })).toBeNull();
  });
});
