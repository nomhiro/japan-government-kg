// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EntityDetailResponse, PathResponse, SearchResponse } from "../../api/client";
import { predicateLabel } from "../../labels";
import { parseHash } from "../../router";
import { PathPage } from "./PathPage";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, search: vi.fn(), entityDetail: vi.fn(), findPath: vi.fn() };
});
import { entityDetail, findPath, search } from "../../api/client";
const searchMock = vi.mocked(search);
const entityDetailMock = vi.mocked(entityDetail);
const findPathMock = vi.mocked(findPath);

afterEach(() => {
  cleanup();
  searchMock.mockReset();
  entityDetailMock.mockReset();
  findPathMock.mockReset();
  window.location.hash = "";
});

// 実際の検索フィクスチャに現れる実体をそのまま使う(架空の政府データを作らない)。
const START_ENTITY: EntityDetailResponse = {
  id: "https://jgkg.norr-tech.com/id/budget/2025/2841",
  id_path: "budget/2025/2841",
  type: "BudgetProject",
  label: "①国民年金基金等給付費負担金　／②存続厚生年金基金等未納掛金等交付金",
  attributes: {},
  relationships: {},
  graphs: {},
  relationships_limit: 50,
  relationships_truncated: false,
};

const GOAL_HIT: SearchResponse = {
  query: "企業年金連合会",
  limit: 10,
  truncated: false,
  results: [
    {
      id: "https://jgkg.norr-tech.com/id/org/1700150004794",
      id_path: "org/1700150004794",
      type: "Organization",
      label: "企業年金連合会",
      summary: "東京都港区",
    },
  ],
};

function foundPathResponse(): PathResponse {
  return {
    start: { id: START_ENTITY.id, id_path: START_ENTITY.id_path, type: START_ENTITY.type, label: START_ENTITY.label },
    goal: {
      id: GOAL_HIT.results[0]!.id,
      id_path: GOAL_HIT.results[0]!.id_path,
      type: GOAL_HIT.results[0]!.type,
      label: GOAL_HIT.results[0]!.label,
    },
    nodes: [
      { id: START_ENTITY.id, id_path: START_ENTITY.id_path, type: START_ENTITY.type, label: START_ENTITY.label },
      {
        id: GOAL_HIT.results[0]!.id,
        id_path: GOAL_HIT.results[0]!.id_path,
        type: GOAL_HIT.results[0]!.type,
        label: GOAL_HIT.results[0]!.label,
      },
    ],
    edges: [
      { source: START_ENTITY.id, target: GOAL_HIT.results[0]!.id, predicate: "recipient", graph: "g1" },
    ],
    graphs: {
      g1: {
        graph: "g1",
        source: "https://rssystem.go.jp/",
        fetched_on: "2026-08-25",
        license: "PDL1.0",
        available: true,
      },
    },
    found: true,
    max_depth: 4,
    visit_budget: 400,
    visited: 12,
    searched_depth: 1,
    budget_exhausted: false,
    depth_limited: false,
    fanout_limit: 50,
    fanout_truncated: false,
    exhaustive: false,
    undirected: true,
  };
}

function basePathResponse(overrides: Partial<PathResponse>): PathResponse {
  const start = { id: "https://jgkg.norr-tech.com/id/a", id_path: "a", type: "Law", label: "テスト法令" };
  const goal = { id: "https://jgkg.norr-tech.com/id/b", id_path: "b", type: "Organization", label: "テスト法人" };
  return {
    start,
    goal,
    nodes: [],
    edges: [],
    graphs: {},
    found: false,
    max_depth: 4,
    visit_budget: 400,
    visited: 10,
    searched_depth: 2,
    budget_exhausted: false,
    depth_limited: false,
    fanout_limit: 50,
    fanout_truncated: false,
    exhaustive: false,
    undirected: true,
    ...overrides,
  };
}

describe("PathPage", () => {
  it("URLのfromを/entityから解決してカードで見せ、終点を検索して選び、探すと経路が横一列のチェーンで出る", async () => {
    entityDetailMock.mockResolvedValue(START_ENTITY);
    searchMock.mockResolvedValue(GOAL_HIT);
    findPathMock.mockResolvedValue(foundPathResponse());

    render(<PathPage from="budget/2025/2841" />);

    // 始点: id_pathの生文字列ではなく、型バッジ+表示名のカードで見える
    await waitFor(() => expect(entityDetailMock).toHaveBeenCalledWith("budget/2025/2841"));
    expect(await screen.findByText((content) => content.includes("国民年金基金等給付費負担金"))).toBeTruthy();
    expect(screen.queryByText("budget/2025/2841")).toBeNull();

    // 終点: 検索して選ぶ
    const user = userEvent.setup();
    const goalInput = screen.getByPlaceholderText("法令・府省・法人・予算事業などを検索");
    await user.type(goalInput, "企業年金連合会");
    const hit = await screen.findByRole("button", { name: /企業年金連合会/ });
    // キーボードで選べる: Tabで辿ってこられる要素であり、Enter/Spaceで押せる
    hit.focus();
    expect(document.activeElement).toBe(hit);
    await user.keyboard("{Enter}");

    expect(screen.getAllByText("企業年金連合会").length).toBeGreaterThan(0);

    const submit = screen.getByRole("button", { name: "探す" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    await user.click(submit);

    await waitFor(() =>
      expect(findPathMock).toHaveBeenCalledWith("budget/2025/2841", "org/1700150004794", expect.any(Object)),
    );

    // URLに経路(from/to)が反映される
    expect(parseHash(window.location.hash)).toEqual({
      name: "path",
      from: "budget/2025/2841",
      to: "org/1700150004794",
    });

    // 結果が横一列のチェーンで出る: ノードカード → 述語ラベル → 次のカード
    expect(await screen.findByText(predicateLabel("recipient"))).toBeTruthy();
    expect(screen.getByRole("link", { name: START_ENTITY.label! }).getAttribute("href")).toBe(
      "#/entity/budget/2025/2841",
    );
    expect(screen.getByRole("link", { name: "企業年金連合会" }).getAttribute("href")).toBe(
      "#/entity/org/1700150004794",
    );
  });

  it("**核心**: found=false かつ exhaustive=true のときだけ「経路は存在しません」と表示する", async () => {
    entityDetailMock.mockResolvedValue(START_ENTITY);
    findPathMock.mockResolvedValue(basePathResponse({ found: false, exhaustive: true }));

    render(<PathPage from="budget/2025/2841" to="org/1700150004794" />);

    expect(await screen.findByText(/経路は存在しません/)).toBeTruthy();
  });

  it("**核心**: found=false かつ exhaustive=false のときは「存在しない」と言わず、理由(打ち切り)を出す", async () => {
    entityDetailMock.mockResolvedValue(START_ENTITY);
    findPathMock.mockResolvedValue(
      basePathResponse({ found: false, exhaustive: false, budget_exhausted: true, visit_budget: 400 }),
    );

    render(<PathPage from="budget/2025/2841" to="org/1700150004794" />);

    const notice = await screen.findByText(/この深さ・この探索量では見つかりませんでした/);
    expect(notice.textContent).toContain("「存在しない」とは言えません");
    expect(screen.queryByText(/経路は存在しません/)).toBeNull();
    const resultArea = document.querySelector<HTMLElement>(".jg-path-result")!;
    expect(within(resultArea).getByText(/訪問予算/).textContent).toContain("使い切りました");
  });

  it("**核心**(実ブラウザ確認で見つけた欠陥): `to`がURLから外れたら、古い終点のカードを残さない", async () => {
    // `useApiQuery`は`key`が非nullからnullに変わってもdataをクリアしない
    // (この画面のマウント中に`to`が外れるのは、経路が見つかった後にURLの
    // `to`を伴わない別の遷移が起きたとき等)。ここで古い解決結果に
    // フォールバックすると、外したはずの終点が残って見える。
    entityDetailMock.mockImplementation(async (idPath: string) =>
      idPath === "budget/2025/2841"
        ? START_ENTITY
        : {
            ...START_ENTITY,
            id: "https://jgkg.norr-tech.com/id/" + idPath,
            id_path: idPath,
            type: "Organization",
            label: "企業年金連合会",
          },
    );
    findPathMock.mockResolvedValue(basePathResponse({ found: false, exhaustive: false }));

    const { rerender } = render(<PathPage from="budget/2025/2841" to="org/1700150004794" />);
    expect(await screen.findByText("企業年金連合会")).toBeTruthy();

    rerender(<PathPage from="budget/2025/2841" />);

    await waitFor(() => {
      expect(screen.queryByText("企業年金連合会")).toBeNull();
    });
    expect(screen.getByPlaceholderText("法令・府省・法人・予算事業などを検索")).toBeTruthy();
  });
});
