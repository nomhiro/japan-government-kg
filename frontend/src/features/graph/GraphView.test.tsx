// @vitest-environment jsdom
// 「描画された」は「動く」ではない(裁定B93)。ここでは押せるものを実際に
// 押した結果をTesting Libraryで見る——実データのサンプル(厚労省近傍26/25)を
// fetchのモック経由で流し、DOMの状態変化(クラス・件数・要素の出現)を確かめる。
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EntityRef } from "../../api/client";
import { DEFAULT_GRAPH_PARAMS, type GraphParams } from "../../router";
import { GraphView } from "./GraphView";
import { entityMinistry, nbhdMinistry } from "./test-fixtures";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const NBHD = nbhdMinistry();
const DETAIL = entityMinistry();
const CENTER: EntityRef = NBHD.center;

function stubFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.includes("/neighborhood/")) {
        return new Response(JSON.stringify(NBHD), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/entity/")) {
        return new Response(JSON.stringify(DETAIL), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response("not found", { status: 404 });
    }),
  );
}

beforeEach(() => {
  stubFetch();
});

function Harness({
  onParamsChange,
  onRecenter,
}: {
  onParamsChange?: (p: GraphParams) => void;
  onRecenter?: (idPath: string) => void;
}) {
  const [params, setParams] = useState<GraphParams>(DEFAULT_GRAPH_PARAMS);
  return (
    <GraphView
      center={CENTER}
      params={params}
      onParamsChange={(next) => {
        onParamsChange?.(next);
        setParams(next);
      }}
      onRecenter={(idPath) => onRecenter?.(idPath)}
    />
  );
}

async function renderReady() {
  render(<Harness />);
  // 近傍応答が来て「厚生労働省」の中心カードが出るまで待つ。
  await screen.findByRole("button", { name: /Ministry.*厚生労働省|厚生労働省/ });
}

function parseViewBox(svg: SVGSVGElement): { x: number; y: number; w: number; h: number } {
  const [x = 0, y = 0, w = 0, h = 0] = (svg.getAttribute("viewBox") ?? "")
    .split(/\s+/)
    .map(Number);
  return { x, y, w, h };
}

describe("GraphView(厚労省の実サンプル: 26ノード・25辺)", () => {
  it("中心と事業のカードが実テキストとして描かれ、状態行が件数を報告する(打ち切りの告知も含む)", async () => {
    await renderReady();
    expect(screen.getByRole("button", { name: /厚生労働省/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /出産費用情報提供推進等経費/ })).toBeTruthy();
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("ノード26件・辺25件");
    expect(status.textContent).toContain("分岐数の上限に達しています");
  });

  it("「事業」レーンは既定18件までに折り畳まれ、「+7件」が出る。押すと全25件になる", async () => {
    const user = userEvent.setup();
    await renderReady();
    const more = screen.getByRole("button", { name: /残り7件を表示する/ });
    expect(more.textContent).toContain("+7件");
    await user.click(more);
    expect(screen.getByRole("button", { name: /院内感染地域支援ネットワーク相談事業/ })).toBeTruthy();
  });

  it("ノードをクリックするとonParamsChangeにselectedが載り、インスペクタに表示名が出る", async () => {
    const onParamsChange = vi.fn();
    const user = userEvent.setup();
    render(<Harness onParamsChange={onParamsChange} />);
    await screen.findByRole("button", { name: /厚生労働省/ });

    await user.click(screen.getByRole("button", { name: /出産費用情報提供推進等経費/ }));

    expect(onParamsChange).toHaveBeenCalledWith(
      expect.objectContaining({ selected: "budget/2025/18695" }),
    );
    const inspector = screen.getByRole("complementary", { name: "ノードの詳細" });
    expect(within(inspector).getByText("出産費用情報提供推進等経費")).toBeTruthy();
  });

  it("同じノードをもう一度クリックすると選択が外れる(selectedがundefinedになる)", async () => {
    const onParamsChange = vi.fn();
    const user = userEvent.setup();
    render(<Harness onParamsChange={onParamsChange} />);
    await screen.findByRole("button", { name: /厚生労働省/ });
    const card = screen.getByRole("button", { name: /出産費用情報提供推進等経費/ });
    await user.click(card);
    await user.click(card);
    const last = onParamsChange.mock.calls.at(-1)?.[0] as GraphParams;
    expect(last.selected).toBeUndefined();
  });

  it("中心ノードを選び、Inspectorで型を展開すると、グラフのノード・辺が増え、状態行が更新される", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await screen.findByRole("button", { name: /厚生労働省/ });

    await user.click(screen.getByRole("button", { name: "府省: 厚生労働省" }));

    const inspector = screen.getByRole("complementary", { name: "ノードの詳細" });
    const expandBtn = await within(inspector).findByRole("button", { name: /この型の先を展開.*事業.*50件/ });
    await user.click(expandBtn);

    const status = screen.getByRole("status");
    expect(status.textContent).toContain("ノード51件・辺50件");
    // 展開後は「追加済み」に変わり、もう一度は押せない。
    const addedBtn = within(inspector).getByRole("button", { name: /追加済み/ }) as HTMLButtonElement;
    expect(addedBtn.disabled).toBe(true);
  });

  it("hoverすると、隔てたノード(隣接しないノード)がis-dimになる", async () => {
    await renderReady();
    const projectA = screen.getByRole("button", { name: /中毒情報センター情報基盤整備費/ });
    const projectB = screen.getByRole("button", { name: /出産費用情報提供推進等経費/ });
    fireEvent.mouseEnter(projectA);
    expect(projectB.getAttribute("class")).toContain("is-dim");
    expect(projectA.getAttribute("class")).not.toContain("is-dim");
  });

  it("軸チップを押すと、一致しないノードがis-dimになる(消えない。DOMに残る)", async () => {
    const user = userEvent.setup();
    await renderReady();
    await user.click(screen.getByRole("button", { name: "誰が(主体)" }));
    const project = screen.getByRole("button", { name: /出産費用情報提供推進等経費/ });
    const ministry = screen.getByRole("button", { name: "府省: 厚生労働省" });
    expect(project.getAttribute("class")).toContain("is-dim");
    expect(ministry.getAttribute("class")).not.toContain("is-dim");
  });

  it("並べ方を「力学」に切り替えるとレーンの見出しが消える。「流れ(レーン)」に戻すと出る", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await screen.findByRole("button", { name: /厚生労働省/ });
    expect(container.querySelectorAll(".jg-graph-lane-title").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "力学" }));
    expect(container.querySelectorAll(".jg-graph-lane-title").length).toBe(0);

    await user.click(screen.getByRole("button", { name: "流れ(レーン)" }));
    expect(container.querySelectorAll(".jg-graph-lane-title").length).toBeGreaterThan(0);
  });

  it("既定の表示は器の幅に合わせ、拡大率は1.0を超えない(カードが読める大きさで描かれる)", async () => {
    const { container } = render(<Harness />);
    await screen.findByRole("button", { name: /厚生労働省/ });
    const svg = container.querySelector("svg.jg-graph-svg") as SVGSVGElement;
    const { w, h } = parseViewBox(svg);

    // **全体を収めない。** 1レーンに25枚のカードが縦に並ぶ実データで全体を収めると
    // 0.5倍程度まで縮み、カードの文字が読めなくなる(実ブラウザで確認した欠陥)。
    // 器(jsdomでは既定の1000x600)と同じ大きさのviewBox = 拡大率1.0 で描く。
    expect(w).toBe(1000);
    expect(h).toBe(600);
  });

  it("ズーム: 「＋」でviewBoxが縮小(拡大表示)。「全体をフィット」は全体を収める(=縦に広がる)", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);
    await screen.findByRole("button", { name: /厚生労働省/ });
    const svg = container.querySelector("svg.jg-graph-svg") as SVGSVGElement;
    const initial = parseViewBox(svg);

    await user.click(screen.getByRole("button", { name: "拡大" }));
    expect(parseViewBox(svg).w).toBeLessThan(initial.w);

    // 「フィット」は既定に戻すのではなく**全体を収める**。この実サンプルは
    // 器より縦に長い(事業25件が1レーンに並ぶ)ので、viewBoxは縦に広がる。
    await user.click(screen.getByRole("button", { name: "全体をフィット" }));
    const fitted = parseViewBox(svg);
    expect(fitted.h).toBeGreaterThan(initial.h);

    // 冪等: もう一度押しても同じ。
    await user.click(screen.getByRole("button", { name: "全体をフィット" }));
    expect(parseViewBox(svg)).toEqual(fitted);
  });

  it("「すべての関係を表で」を押すと、辺と同じ本数の行を持つ表が現れる", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await screen.findByRole("button", { name: /厚生労働省/ });
    expect(screen.queryByRole("table")).toBeNull();

    await user.click(screen.getByRole("button", { name: "すべての関係を表で" }));
    const table = screen.getByRole("table");
    // ヘッダ行 + 25辺。
    expect(within(table).getAllByRole("row")).toHaveLength(26);
  });

  it("深さボタンを押すとonParamsChangeにdepthが載る", async () => {
    const onParamsChange = vi.fn();
    const user = userEvent.setup();
    render(<Harness onParamsChange={onParamsChange} />);
    await screen.findByRole("button", { name: /厚生労働省/ });
    await user.click(screen.getByRole("button", { name: "深さ2" }));
    expect(onParamsChange).toHaveBeenCalledWith(expect.objectContaining({ depth: 2 }));
  });

  it("「このノードを中心にする」を押すとonRecenterが選択中のidPathで呼ばれる", async () => {
    const onRecenter = vi.fn();
    const user = userEvent.setup();
    render(<Harness onRecenter={onRecenter} />);
    await screen.findByRole("button", { name: /厚生労働省/ });
    await user.click(screen.getByRole("button", { name: /出産費用情報提供推進等経費/ }));
    const inspector = screen.getByRole("complementary", { name: "ノードの詳細" });
    await user.click(within(inspector).getByRole("button", { name: "このノードを中心にする" }));
    expect(onRecenter).toHaveBeenCalledWith("budget/2025/18695");
  });
});

describe("表示名を持たないノード(裁定B108)", () => {
  /**
   * 実サンプル(`neighborhood-ministry.json`)は `described_by` を持たない
   * ——APIに足す前に本番から取った応答なので、この場面だけ合成データを足す
   * (本番の応答を手で書き換えると「実サンプル」でなくなる)。
   *
   * 足すのは**同じ型の名前なしノード2件**。「見分けられること」が要求なので、
   * 1件では検査にならない。
   */
  function nbhdWithNamelessNodes() {
    const base = nbhdMinistry();
    const centerId = base.center.id;
    // 出典グラフは実サンプルの値を使う(架空のグラフ名を作らない)。
    const graph = base.edges[0]?.graph ?? "";
    return {
      ...base,
      nodes: [
        ...base.nodes,
        {
          id: "https://jgkg.norr-tech.com/id/b/annual/2024",
          id_path: "b/annual/2024",
          type: "AnnualBudget",
          label: null,
          described_by: { predicate: "budgetFiscalYear", value: "2024" },
        },
        {
          id: "https://jgkg.norr-tech.com/id/b/annual/2025",
          id_path: "b/annual/2025",
          type: "AnnualBudget",
          label: null,
          described_by: { predicate: "budgetFiscalYear", value: "2025" },
        },
      ],
      edges: [
        ...base.edges,
        {
          source: centerId,
          target: "https://jgkg.norr-tech.com/id/b/annual/2024",
          predicate: "project",
          graph,
        },
        {
          source: centerId,
          target: "https://jgkg.norr-tech.com/id/b/annual/2025",
          predicate: "project",
          graph,
        },
      ],
    };
  }

  function stubFetchWith(nbhd: unknown): void {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url.includes("/neighborhood/")) {
          return new Response(JSON.stringify(nbhd), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/entity/")) {
          return new Response(JSON.stringify(DETAIL), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response("not found", { status: 404 });
      }),
    );
  }

  it("カードに「述語のラベル 値」が出て、同じ「表示名なし」が並ばない", async () => {
    stubFetchWith(nbhdWithNamelessNodes());
    render(<Harness />);
    // SVGのカードは可視テキストと `<title>`(全文)の2箇所に同じ文字列を持つ。
    await screen.findAllByText("予算年度 2024");
    expect(screen.getAllByText("予算年度 2025").length).toBeGreaterThan(0);
    expect(screen.queryByText("(表示名なし)")).toBeNull();
  });

  it("読み上げ用のラベルも同じ1行を使う(型: 値)", async () => {
    stubFetchWith(nbhdWithNamelessNodes());
    render(<Harness />);
    await screen.findAllByText("予算年度 2024");
    expect(
      screen.getByRole("button", { name: "年度ごとの予算と執行: 予算年度 2024" }),
    ).toBeTruthy();
  });

  it("見分けのための属性が無ければ、今までどおり「(表示名なし)」と言う", async () => {
    const nbhd = nbhdWithNamelessNodes();
    const stripped = {
      ...nbhd,
      nodes: nbhd.nodes.map((n) =>
        n.type === "AnnualBudget" ? { ...n, described_by: null } : n,
      ),
    };
    stubFetchWith(stripped);
    render(<Harness />);
    const cards = await screen.findAllByRole("button", { name: /年度ごとの予算と執行/ });
    expect(cards.length).toBe(2);
    // 可視テキストと `<title>` の2箇所 × 2ノード。
    expect(screen.getAllByText("(表示名なし)").length).toBe(4);
  });
});

describe("外から与えたグラフ(裁定B109)", () => {
  const A = { id: "https://x/id/a", id_path: "a", type: "BudgetProject", label: "事業A" };
  const B = { id: "https://x/id/b", id_path: "b", type: "Ministry", label: "府省B" };
  const SUPPLIED = {
    raw: {
      nodes: [A, B],
      edges: [{ source: A.id, target: B.id, predicate: "ministry", graph: "g/1" }],
    },
    centerId: A.id,
    fanoutTruncatedIds: new Set<string>(),
    emphasizedIds: new Set([A.id, B.id]),
    nodesTruncated: true,
    edgesTruncated: false,
  };

  function SuppliedHarness() {
    const [params, setParams] = useState<GraphParams>(DEFAULT_GRAPH_PARAMS);
    return (
      <GraphView
        center={A}
        supplied={SUPPLIED}
        showDepth={false}
        params={params}
        onParamsChange={setParams}
        onRecenter={() => {}}
      />
    );
  }

  it("**近傍を取りに行かず**、与えられたノードをそのまま描く", async () => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    render(<SuppliedHarness />);
    await screen.findAllByText("事業A");
    expect(screen.getAllByText("府省B").length).toBeGreaterThan(0);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("強調するノードは中心と同じ扱いで描く", async () => {
    stubFetch();
    render(<SuppliedHarness />);
    await screen.findAllByText("事業A");
    expect(document.querySelectorAll(".jg-graph-node.is-center")).toHaveLength(2);
  });

  it("深さの切り替えを隠し、打ち切りは呼び出し側の申告をそのまま出す", async () => {
    stubFetch();
    render(<SuppliedHarness />);
    await screen.findAllByText("事業A");
    expect(screen.queryByRole("group", { name: "深さ" })).toBeNull();
    // `nodesTruncated: true` を渡したので、状態行が上限に達したことを言う。
    expect(screen.getByText(/上限/)).toBeTruthy();
  });
});
