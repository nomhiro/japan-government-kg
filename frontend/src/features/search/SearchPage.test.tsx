// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EntityRef, NeighborhoodResponse, SearchResponse } from "../../api/client";
import searchFixture from "../../../../.superpowers/apisamples/search.json";
import { SearchPage } from "./SearchPage";

// 実APIの応答をそのままフィクスチャに使う(架空の政府データを作らない)。
// `search.json`は「年金」で検索した実測(20件・truncated=true)。
const FIXTURE = searchFixture as SearchResponse;

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, search: vi.fn(), neighborhood: vi.fn() };
});
import { neighborhood, search } from "../../api/client";
const searchMock = vi.mocked(search);
const nbhdMock = vi.mocked(neighborhood);

/**
 * 近傍応答の合成。**実サンプルが単一中心の1本しか無いため**、複数ヒットの
 * 合算を確かめるにはここだけ合成データが要る(`search-graph.test.ts` と
 * 同じ判断)。構造だけを言う最小限にし、政府データとしては提示しない。
 */
/**
 * 府省のカードの読み上げ名。`GraphView` は `${型の表示名}: ${表示名}` を
 * `aria-label` にするので、**末尾一致**で府省のカードだけを指す。
 */
const MINISTRY_CARD = /: 厚生労働省$/;

const MINISTRY: EntityRef = {
  id: "https://jgkg.norr-tech.com/id/org/6000012070001",
  id_path: "org/6000012070001",
  type: "Ministry",
  label: "厚生労働省",
};

function nbhdFor(hit: { id: string; id_path: string; type: string; label: string | null }): NeighborhoodResponse {
  const center: EntityRef = { id: hit.id, id_path: hit.id_path, type: hit.type, label: hit.label };
  if (hit.type !== "BudgetProject") {
    // 法令・組織は辺を持たない応答にする(実データでも「年金」の20件中5件が
    // 辺0だった。孤立の扱いをこのテストで運動させる)。
    return base(center, [], []);
  }
  const annual: EntityRef = {
    id: `${hit.id}/annual/2024`,
    id_path: `${hit.id_path}/annual/2024`,
    type: "AnnualBudget",
    label: null,
    described_by: { predicate: "budgetFiscalYear", value: "2024" },
  };
  return base(
    center,
    [MINISTRY, annual],
    [
      { source: hit.id, target: MINISTRY.id, predicate: "ministry", graph: "g/1" },
      { source: annual.id, target: hit.id, predicate: "project", graph: "g/1" },
    ],
  );
}

function base(
  center: EntityRef,
  others: readonly EntityRef[],
  edges: NeighborhoodResponse["edges"],
): NeighborhoodResponse {
  return {
    center,
    depth: 1,
    nodes: [center, ...others],
    edges,
    graphs: {},
    node_limit: 200,
    edge_limit: 400,
    fanout_limit: 20,
    nodes_truncated: false,
    edges_truncated: false,
    fanout_truncated_nodes: [],
  };
}

function mockNeighborhoods(): void {
  nbhdMock.mockImplementation(async (idPath: string) => {
    const hit = FIXTURE.results.find((r) => r.id_path === idPath);
    return hit ? nbhdFor(hit) : null;
  });
}

afterEach(() => {
  cleanup();
  searchMock.mockReset();
  nbhdMock.mockReset();
  window.location.hash = "";
});

/** 折り畳んだ一覧の中のリンクだけを数える(グラフや孤立節のリンクと混ぜない)。 */
function listLinks(): HTMLElement[] {
  const list = document.querySelector(".jg-search-list") as HTMLElement;
  return [...list.querySelectorAll("a")] as HTMLElement[];
}

describe("SearchPage(グラフ主体。裁定B109)", () => {
  it("**核心**: 結果を1枚のグラフで描き、ヒットを太枠で示す", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    render(<SearchPage q="年金" />);

    await screen.findByText("20件");
    // 20件すべての近傍を取る(一覧を出すだけで終わらない)。
    await waitFor(() => expect(nbhdMock).toHaveBeenCalledTimes(FIXTURE.results.length));
    for (const hit of FIXTURE.results) {
      expect(nbhdMock).toHaveBeenCalledWith(hit.id_path, { depth: 1 });
    }

    // 合算の結果、どの事業からも参照される府省が1つのカードとして現れる
    // ——これが「俯瞰」の実体(各事業のページを開いても見えない関係)。
    const cards = await screen.findAllByRole("button", { name: MINISTRY_CARD });
    expect(cards).toHaveLength(1);

    // ヒットは強調して描く(中心と同じ扱い)。
    const emphasized = document.querySelectorAll(".jg-graph-node.is-center");
    expect(emphasized.length).toBe(FIXTURE.results.length);
  });

  it("ヒットどうしを繋ぎえない記録は図から外し、**外した件数を言う**", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");

    // BudgetProjectは5件で、それぞれに年度予算を1件付けた。
    const projects = FIXTURE.results.filter((r) => r.type === "BudgetProject").length;
    const caveat = await screen.findByText(/繋ぎえない記録/);
    expect(caveat.textContent).toContain(`${projects}件`);
    expect(caveat.textContent).toContain("1つの事業にしか属さない");
    // 年度予算のカードは描かれていない。
    expect(screen.queryByText("予算年度 2024")).toBeNull();
  });

  it("つながりの記録がない結果を、隠さず別の節に出す", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");

    const isolated = FIXTURE.results.filter((r) => r.type !== "BudgetProject").length;
    const heading = await screen.findByText(new RegExp(`つながりの記録がない結果\\(${isolated}件\\)`));
    expect(heading).toBeTruthy();
    expect(screen.getByText(/KGに関係の記録が無い/)).toBeTruthy();
  });

  it("一覧は消さずに折り畳んで残す(キーボードで開いて辿れる)", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");

    const summary = screen.getByText(/検索結果の一覧/);
    const details = summary.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);

    const user = userEvent.setup();
    await user.click(summary);
    expect(details.open).toBe(true);

    const links = listLinks();
    expect(links).toHaveLength(FIXTURE.results.length);
    const first = links[0] as HTMLAnchorElement;
    expect(first.getAttribute("href")).toBe(`#/entity/${FIXTURE.results[0]!.id_path}`);
    first.focus();
    expect(document.activeElement).toBe(first);
    await user.keyboard("{Enter}");
    expect(window.location.hash).toBe(`#/entity/${FIXTURE.results[0]!.id_path}`);
  });

  it("深さの切り替えは出さない(合算グラフに深さという概念が無い)", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");
    await screen.findAllByRole("button", { name: MINISTRY_CARD });
    expect(screen.queryByRole("group", { name: "深さ" })).toBeNull();
    // 並べ方の切り替えは出す(俯瞰の仕方を選べる)。
    expect(screen.getByRole("group", { name: "並べ方" })).toBeTruthy();
  });

  it("型チップを押すと、グラフと一覧の両方がその型だけになる", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");
    await screen.findAllByRole("button", { name: MINISTRY_CARD });

    const lawCount = FIXTURE.results.filter((r) => r.type === "Law").length;
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^法令$/ }));

    await waitFor(() => expect(listLinks()).toHaveLength(lawCount));
    // 法令だけに絞ると府省は繋ぎ役として残らない(法令に辺が無いため)。
    // **名前は末尾で判定する。** `/厚生労働省/` だと法令名の中の
    // 「…に伴う厚生労働省関係省令の整備…」に一致してしまい、府省のカードが
    // 消えたことを確かめられない(観察O14: アサーションは正しいのに入力の
    // 選び方で欠陥を素通りさせる型)。
    expect(screen.queryAllByRole("button", { name: MINISTRY_CARD })).toHaveLength(0);
    // 絞り込みで近傍を取り直さない(取得回数は変わらない)。
    expect(nbhdMock).toHaveBeenCalledTimes(FIXTURE.results.length);
  });

  it("グラフの状態(並べ方)をURLに載せ、検索語を落とさない", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    window.location.hash = "#/search?q=%E5%B9%B4%E9%87%91";
    render(<SearchPage q="年金" />);
    await screen.findAllByRole("button", { name: MINISTRY_CARD });

    const user = userEvent.setup();
    // 検索の既定は「構造」なので、URLに載るのは「流れ(レーン)」に変えたとき。
    await user.click(screen.getByRole("button", { name: "流れ(レーン)" }));
    expect(window.location.hash).toContain("lay=lanes");
    expect(window.location.hash).toContain("q=");
  });

  it("つながりの取得に失敗したら、失敗したことをそのまま伝える", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    nbhdMock.mockRejectedValue(new Error("503 Service Unavailable"));
    render(<SearchPage q="年金" />);
    await screen.findByText("20件");
    expect(await screen.findByText(/つながりの取得に失敗しました/)).toBeTruthy();
  });

  it("0件のとき「見つかりませんでした」と、部分一致・6種類・支出を対象外にしていることの説明を出す", async () => {
    searchMock.mockResolvedValue({ query: "存在しない語xyz", results: [], limit: 20, truncated: false });
    mockNeighborhoods();
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
    mockNeighborhoods();
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
    mockNeighborhoods();
    render(<SearchPage q="厚生労働省" />);
    await screen.findByText("1件");
    expect(screen.queryByRole("group", { name: "型で絞り込む" })).toBeNull();
  });
});

describe("SearchPage の強調の言い回し", () => {
  it("ヒットの印は「中心」ではなく「一致」(19件が全部「中心」では嘘になる)", async () => {
    searchMock.mockResolvedValue(FIXTURE);
    mockNeighborhoods();
    render(<SearchPage q="年金" />);
    await screen.findAllByRole("button", { name: MINISTRY_CARD });
    expect(screen.getAllByText("一致").length).toBe(FIXTURE.results.length);
    expect(screen.queryByText("中心")).toBeNull();
  });
});
