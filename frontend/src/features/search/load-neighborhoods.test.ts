import { afterEach, describe, expect, it, vi } from "vitest";
import { neighborhood, type SearchHit } from "../../api/client";
import { nbhdMinistry } from "../graph/test-fixtures";
import { loadNeighborhoods } from "./load-neighborhoods";
vi.mock("../../api/client", async (original) => ({ ...await original<typeof import("../../api/client")>(), neighborhood: vi.fn() }));
afterEach(() => vi.resetAllMocks());
describe("検索結果の近傍取得", () => {
  it("同時要求は4件以内で、1件の失敗が成功した結果を消さず、入力順を保持する", async () => {
    let active = 0;
    let maximum = 0;
    vi.mocked(neighborhood).mockImplementation(async (id) => {
      maximum = Math.max(maximum, ++active);
      await Promise.resolve();
      active--;
      if (id === "failed") throw new Error("503");
      return { ...nbhdMinistry(), center: { ...nbhdMinistry().center, id_path: id } };
    });
    const paths = ["first", "failed", ...Array.from({ length: 15 }, (_, i) => `path/${i}`)];
    const result = await loadNeighborhoods(paths.map((id_path) => ({ id_path }) as SearchHit));
    expect(maximum).toBeLessThanOrEqual(4);
    expect(maximum).toBeGreaterThan(1);
    expect(result.failedCount).toBe(1);
    expect(result.neighborhoods.map((n) => n?.center.id_path ?? "failed")).toEqual(paths);
  });
});
