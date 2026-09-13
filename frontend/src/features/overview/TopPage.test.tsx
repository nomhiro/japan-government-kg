// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OverviewResponse } from "../../api/client";
import { TopPage } from "./TopPage";

// **実APIの応答をテストのフィクスチャに使う(架空の政府データを作らない)。**
// `.superpowers/apisamples/overview.json`は本番の実データ——`node:fs`で
// 直接読む(Viteのモジュール解決を経由しない。プロジェクトのrootDir外の
// ファイルをimportで持ち込むと`fs.allow`等の制約に当たりうるため)。
const fixturePath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../../.superpowers/apisamples/overview.json",
);
const overviewFixture = JSON.parse(readFileSync(fixturePath, "utf-8")) as OverviewResponse;

function fakeResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

// vitest は globals 無しなので Testing Library の自動 cleanup は効かない
// (AppShell.test.tsxと同じ注記)。
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

function stubFetchWithFixture(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL) => {
      const url = String(input);
      if (url.endsWith("/overview")) return fakeResponse(200, overviewFixture);
      throw new Error(`このテストで想定していないURL: ${url}`);
    }),
  );
}

describe("TopPage(トップページ再設計)", () => {
  beforeEach(() => {
    stubFetchWithFixture();
  });

  it("ヒーロー: 当初予算・執行率・国が自ら支払った額(下限)を実データの値で出す", async () => {
    render(<TopPage />);

    // 当初予算 123.1兆円(23府省の予算額の合計。CQ15)。
    await screen.findByText("2025年度 当初予算");
    expect(screen.getByText("123.1兆円")).toBeTruthy();

    // 執行率 83.7〜87.0%(歳出予算現額に対する。CQ14。2025年度は未執行なので除く)。
    expect(screen.getByText("83.7〜87.0%")).toBeTruthy();

    // 国が自ら支払った額(下限) 126.9兆円 + 下限タグ(CQ12)。
    expect(screen.getByText("126.9兆円")).toBeTruthy();
    expect(screen.getByText("下限")).toBeTruthy();

    // 素朴な合計156.8兆円・重複29.9兆円(CQ19)を隠さない。
    expect(screen.getByText("156.8兆円")).toBeTruthy();
    expect(screen.getByText("29.9兆円")).toBeTruthy();

    // 規模の行(CQ18): 事業5,794・府省23・法令9,550・法人18,876・支出73,919。
    expect(screen.getByText("5,794")).toBeTruthy();
    expect(screen.getByText("23")).toBeTruthy();
    expect(screen.getByText("9,550")).toBeTruthy();
    expect(screen.getByText("18,876")).toBeTruthy();
    expect(screen.getByText("73,919")).toBeTruthy();

    // 3つの数字を矢印でつなげていないことの明示(裁定B96/B97)。
    expect(screen.getByText(/矢印でつながっていません/)).toBeTruthy();

    // 鮮度ではなく「集計した時刻」と正確に書く。
    expect(screen.getByText(/この画面の数字を集計した時刻/)).toBeTruthy();
    expect(screen.queryByText(/このデータの鮮度/)).toBeNull();
  });

  it("府省ツリーマップ: 23タイルが実データの金額で描かれ、クリックでエンティティ画面へ遷移する", async () => {
    const user = userEvent.setup();
    const { container } = render(<TopPage />);

    await screen.findByText("府省ごとの予算額");
    const svg = container.querySelector(".jg-treemap__svg");
    expect(svg).toBeTruthy();

    // 厚生労働省のタイル(aria-labelに正確な金額を持つ)。
    const tile = within(svg as HTMLElement).getByRole("button", {
      name: /厚生労働省 91,789,031,491,000円/,
    });
    expect(tile.tagName.toLowerCase()).toBe("rect");

    await user.click(tile);
    expect(window.location.hash).toBe("#/entity/org/6000012070001");
  });

  it("府省ツリーマップ: 400px相当のモバイル用フォールバック行(縦積み表)からもクリックで遷移できる", async () => {
    const user = userEvent.setup();
    const { container } = render(<TopPage />);

    await screen.findByText("府省ごとの予算額");
    const list = container.querySelector(".jg-treemap__mobile-list");
    expect(list).toBeTruthy();
    const row = within(list as HTMLElement).getByRole("button", { name: /国土交通省/ });
    await user.click(row);
    expect(window.location.hash).toBe("#/entity/org/2000012100001");
  });

  it("府省ツリーマップ:「厚生労働省を除いて見る」を押すと注記が動的な値で出る", async () => {
    const user = userEvent.setup();
    render(<TopPage />);

    await screen.findByText("府省ごとの予算額");
    const toggle = screen.getByRole("button", { name: "厚生労働省を除いて見る" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");

    await user.click(toggle);
    expect(toggle.getAttribute("aria-pressed")).toBe("true");

    // 除いた府省名・金額・割合(74.6%)・残りの府省数(22)を手書きせず動的に出す。
    expect(screen.getByText(/厚生労働省.*91\.8兆円.*74\.6%.*22府省/s)).toBeTruthy();
  });

  it("資金の流れ: 児童手当の例(国→市町村→受給者)が同じ金額で繋がって出る。足し算はしていない", async () => {
    render(<TopPage />);

    await screen.findByText("資金の流れ");
    expect(screen.getByText("児童手当等交付金に必要な経費")).toBeTruthy();
    expect(screen.getByText("市町村")).toBeTruthy();
    expect(screen.getByText("児童手当受給者")).toBeTruthy();
    // 同じ1,401,293,745,413円がこの事業の中で繰り返し出る(合算した別の数字は出さない)。
    expect(screen.getAllByText("1.4兆円").length).toBeGreaterThanOrEqual(1);
    // この注記は事業ごとの流れ図each1件に添えるため、4事業分だけ複数出る。
    expect(screen.getAllByText(/同じお金が再記録されています/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/合計は表示していません/).length).toBeGreaterThanOrEqual(1);
  });

  it("資金の流れ: 事業名をクリックすると**その事業のページ**へ遷移する(裁定B110)", async () => {
    // **この主張は2026-09-13に変わった。** それまでは事業名での検索へ
    // 遷移することを固定していた —— CQ13が `?project` を返しておらず、
    // 存在しないIDを組み立てるわけにはいかなかったため。CQ13にIRIを
    // 返させて直した。
    const user = userEvent.setup();
    render(<TopPage />);

    await screen.findByText("資金の流れ");
    const title = screen.getByText("児童手当等交付金に必要な経費");
    // 期待値は**フィクスチャから引く**(パスを手書きしない。転記した値は
    // 実データが変われば嘘になる)。
    const row = overviewFixture.money_through_stages.find(
      (r) => r.project_name === "児童手当等交付金に必要な経費",
    )!;
    expect(row.project_id_path).toBeTruthy();
    expect(title.getAttribute("href")).toBe(`#/entity/${row.project_id_path}`);
    await user.click(title);
    expect(window.location.hash).toBe(`#/entity/${row.project_id_path}`);
  });

  it("資金の流れ: APIが事業のIRIを返さない版でも壊れず、リンクを出さない", async () => {
    // **APIとフロントは別々に配備される**(裁定B103追記7)。古いAPIが
    // 相手のとき、存在しないIDを組み立てるより遷移できない方が正しい
    // (裁定B59/B69)。
    const stripped = {
      ...overviewFixture,
      money_through_stages: overviewFixture.money_through_stages.map((r) => {
        const { project_id, project_id_path, ...rest } = r;
        void project_id;
        void project_id_path;
        return rest as unknown as (typeof overviewFixture.money_through_stages)[number];
      }),
    };
    vi.stubGlobal("fetch", vi.fn(async () => fakeResponse(200, stripped)));
    render(<TopPage />);

    await screen.findByText("資金の流れ");
    const title = screen.getByText("児童手当等交付金に必要な経費");
    expect(title.tagName).toBe("SPAN");
    expect(title.getAttribute("href")).toBeNull();
    // **事業が1つに混ざらないこと**(鍵が無いときは名前で束ねる)。
    const names = new Set(overviewFixture.money_through_stages.map((r) => r.project_name));
    const titles = document.querySelectorAll(".jg-flow__title");
    expect(titles.length).toBe(Math.min(4, names.size));
  });

  it("年度の推移: 5年分の帯と、要求と査定の母集団の注記(32.7〜44.0%)を出す", async () => {
    const { container } = render(<TopPage />);

    await screen.findByText("年度の推移");
    const historyRows = container.querySelector(".jg-history");
    expect(historyRows).toBeTruthy();
    expect(within(historyRows as HTMLElement).getByText("2025年度")).toBeTruthy();
    expect(within(historyRows as HTMLElement).getByText("2021年度")).toBeTruthy();
    // 2025年度はまだ執行されていない(0円)ので「未執行」と出し、0%と偽らない。
    expect(screen.getByText("未執行")).toBeTruthy();

    // 事業ごとの完全一致率(32.7〜44.0%)を、全体の割合と併記する(裁定B103追記5)。
    expect(screen.getByText(/32\.7〜44\.0%程度/)).toBeTruthy();
  });

  it("支払先はどこまで特定できているか: enumValueLabelの表示名で4区分を出す(手書きしない)", async () => {
    render(<TopPage />);

    await screen.findByText("支払先はどこまで特定できているか");
    expect(screen.getByText("法人番号で特定できた")).toBeTruthy();
    expect(screen.getByText("複数の支払先をまとめた行")).toBeTruthy();
    expect(screen.getByText("法人番号が仮の値か、存在しない")).toBeTruthy();
    expect(screen.getByText("支払先を特定できなかった")).toBeTruthy();
    // 特定できなかったのは4件だけ、という事実を導出して出す。
    expect(screen.getByText(/4件だけです/)).toBeTruthy();
  });

  it("入口: 代表的なエンティティのカードを押すとエンティティ画面へ、データ/チャットへも遷移する", async () => {
    const user = userEvent.setup();
    render(<TopPage />);

    const heading = await screen.findByText("つながりを辿る");
    const section = heading.closest("section");
    expect(section).toBeTruthy();
    await user.click(within(section as HTMLElement).getByRole("button", { name: /厚生労働省/ }));
    expect(window.location.hash).toBe("#/entity/org/6000012070001");

    await user.click(screen.getByRole("link", { name: "データとAPI" }));
    expect(window.location.hash).toBe("#/data");

    await user.click(screen.getByRole("link", { name: "聞く(チャット)" }));
    expect(window.location.hash).toBe("#/chat");
  });

  it("/overviewの取得に失敗したら、内部事情を出さずに正直な告知だけを出す", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => fakeResponse(503, { detail: "aggregation failed" })),
    );
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    render(<TopPage />);

    await screen.findByText("全体の数字をいま出せません。");
    expect(screen.queryByText(/503/)).toBeNull();
    // **待つ。** 画面の告知が出た時点で `console.error` が必ず済んでいるとは
    // 限らない(全ファイル並列実行のとき1回だけ落ちた。2026-09-13)。
    // 「たまに赤くなる検査」は検査が無いより悪い(裁定B65の理由づけと同じ)。
    await waitFor(() => expect(consoleError).toHaveBeenCalled());
    consoleError.mockRestore();
  });
});
