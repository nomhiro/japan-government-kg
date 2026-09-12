// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SearchResponse } from "../../api/client";
import searchFixture from "../../../../.superpowers/apisamples/search.json";
import { SearchPage } from "./SearchPage";

// 実APIの応答をそのままフィクスチャに使う(架空の政府データを作らない。
// team-leadの指示)。`search.json`は「年金」で検索した実測(20件・truncated=true)。
const FIXTURE = searchFixture as SearchResponse;

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, search: vi.fn() };
});
import { search } from "../../api/client";
const searchMock = vi.mocked(search);

afterEach(() => {
  cleanup();
  searchMock.mockReset();
});

describe("SearchPage", () => {
  it("結果件数と、実際に現れた型のチップを表示し、キーボードで結果へ辿ってEnterで開ける(hrefが#/entity/…になる)", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    render(<SearchPage q="年金" />);

    await waitFor(() => expect(searchMock).toHaveBeenCalledWith("年金", 20));
    expect(await screen.findByText("20件")).toBeTruthy();

    // フィクスチャに実際に現れる型: BudgetProject(予算事業)・Law(法令)・Organization(組織)
    const group = screen.getByRole("group", { name: "型で絞り込む" });
    expect(within(group).getByRole("button", { name: /予算事業/ })).toBeTruthy();
    expect(within(group).getByRole("button", { name: /法令/ })).toBeTruthy();
    expect(within(group).getByRole("button", { name: /組織/ })).toBeTruthy();

    // 本物のリンク(<a href>)で、クリック専用の<li>ではない
    const firstLink = screen.getAllByRole("link")[0] as HTMLAnchorElement;
    expect(firstLink.getAttribute("href")).toBe(`#/entity/${FIXTURE.results[0]!.id_path}`);

    firstLink.focus();
    expect(document.activeElement).toBe(firstLink);
    const user = userEvent.setup();
    await user.keyboard("{Enter}");
    expect(window.location.hash).toBe(`#/entity/${FIXTURE.results[0]!.id_path}`);
  });

  it("型チップを押すと、その型だけに絞り込む(他の型は隠れる)", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");

    const lawTypeCount = FIXTURE.results.filter((r) => r.type === "Law").length;
    const budgetTypeCount = FIXTURE.results.filter((r) => r.type === "BudgetProject").length;
    expect(screen.getAllByRole("link")).toHaveLength(FIXTURE.results.length);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /法令/ }));

    expect(screen.getAllByRole("link")).toHaveLength(lawTypeCount);
    expect(screen.getByRole("button", { name: /法令/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /予算事業/ }).getAttribute("aria-pressed")).toBe("false");
    void budgetTypeCount;
  });

  it("0件のとき「見つかりませんでした」と、部分一致・6種類・支出を対象外にしていることの説明を出す", async () => {
    searchMock.mockResolvedValue({ query: "存在しない語xyz", results: [], limit: 20, truncated: false });
    render(<SearchPage q="存在しない語xyz" />);

    const message = await screen.findByText(/見つかりませんでした/);
    expect(message.textContent).toContain("部分一致");
    expect(message.textContent).toContain("6種類");
    expect(message.textContent).toContain("支出");
  });

  it("**核心**: truncated=trueのとき「もっと表示」が出て、押すとlimit=100で再取得し、上限に達したら消える", async () => {
    searchMock.mockResolvedValueOnce(FIXTURE); // limit=20
    const allLoaded: SearchResponse = { ...FIXTURE, limit: 100, truncated: false };
    searchMock.mockResolvedValueOnce(allLoaded); // limit=100
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");

    const more = screen.getByRole("button", { name: /もっと表示/ });
    const user = userEvent.setup();
    await user.click(more);

    await waitFor(() => expect(searchMock).toHaveBeenCalledWith("年金", 100));
    await waitFor(() => expect(screen.queryByRole("button", { name: /もっと表示/ })).toBeNull());
  });

  it("型が1種類しか現れないときは絞り込みチップを出さない(絞り込む意味が無い)", async () => {
    const single: SearchResponse = {
      query: "厚生労働省",
      results: [FIXTURE.results.find((r) => r.type === "Law")!],
      limit: 20,
      truncated: false,
    };
    searchMock.mockResolvedValue(single);
    render(<SearchPage q="厚生労働省" />);
    await screen.findByText("1件");
    expect(screen.queryByRole("group", { name: "型で絞り込む" })).toBeNull();
  });
});
