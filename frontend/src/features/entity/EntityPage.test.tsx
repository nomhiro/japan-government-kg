// @vitest-environment jsdom
//
// 押せるものは自分で押すテスト(裁定B93: 「描画された」は「動く」ではない)。
// `GraphView`(別のエージェントが同時に実装している部品)はモックする——
// ここで検査したいのは「EntityPageがGraphViewPropsの契約通りに呼ぶか」
// (`onRecenter`/`onUseAsPathStart`/`onParamsChange`が正しい先に配線されて
// いるか)であって、グラフの中身の正しさではない。
//
// 実データ(`.superpowers/apisamples/entity-*.json`)を厚労省(府省)と
// 予算事業のフィクスチャに使う(架空の政府データを作らない)。それ以外の型
// (組織・法令・支出・汎用)は、`/entity`のAPIから来る実在の型でも
// サンプルが無いため、型分岐の配線だけを確かめる最小限の構造データ
// (政府データとして提示しない、テスト専用の合成値)を使う。
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import type { EntityDetailResponse } from "../../api/client";
import { entityDetail } from "../../api/client";
import { ENTITY_RELATIONSHIPS_LIMIT } from "../../api/limits";
import { EntityPage } from "./EntityPage";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, entityDetail: vi.fn() };
});

vi.mock("../graph/GraphView", () => ({
  GraphView: (props: {
    center: { id_path: string };
    onParamsChange: (p: { depth: number; layout: "lanes" | "force"; axes: string[] }) => void;
    onRecenter: (idPath: string) => void;
    onUseAsPathStart?: (idPath: string) => void;
  }) => (
    <div data-testid="graph-view-mock">
      <span data-testid="graph-view-center">{props.center.id_path}</span>
      <button type="button" onClick={() => props.onRecenter("budget/2025/1735")}>
        [モック]グラフでノードをクリック(中心を移す)
      </button>
      <button type="button" onClick={() => props.onUseAsPathStart?.("budget/2025/1735")}>
        [モック]グラフから経路の始点にする
      </button>
      <button
        type="button"
        onClick={() => props.onParamsChange({ depth: 2, layout: "force", axes: [] })}
      >
        [モック]深さを変える
      </button>
    </div>
  ),
}));

// jsdom環境では`import.meta.url`がfile:スキームにならないため、
// `process.cwd()`(`npm test`実行時は`frontend/`)からの相対パスで読む。
const REPO_ROOT = resolve(process.cwd(), "..");

function readJson<T>(relPath: string): T {
  return JSON.parse(readFileSync(resolve(REPO_ROOT, relPath), "utf-8")) as T;
}

function entityMinistry(): EntityDetailResponse {
  return readJson<EntityDetailResponse>(".superpowers/apisamples/entity-ministry.json");
}

function entityProject(): EntityDetailResponse {
  return readJson<EntityDetailResponse>(".superpowers/apisamples/entity-project.json");
}

const mockedEntityDetail = entityDetail as unknown as Mock;

beforeEach(() => {
  mockedEntityDetail.mockReset();
  // jsdomは scrollIntoView を実装しないため、呼べることだけを確認できるよう
  // スタブを与える(無ければ EntityHeader は素通りする実装だが、
  // 「押して何が起きたか」を確認するにはスタブが要る)。
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
  vi.restoreAllMocks();
});

describe("EntityPage(府省: 厚生労働省。実データ)", () => {
  async function renderMinistry(): Promise<void> {
    mockedEntityDetail.mockImplementation(async (_idPath: string, limit?: number) => {
      const base = entityMinistry();
      if (limit === ENTITY_RELATIONSHIPS_LIMIT.max) {
        return { ...base, relationships_truncated: false, relationships_limit: ENTITY_RELATIONSHIPS_LIMIT.max };
      }
      return base;
    });
    render(<EntityPage idPath="org/6000012070001" />);
    await screen.findByRole("heading", { level: 1, name: "厚生労働省" });
  }

  it("名前・型バッジ・所管する予算事業の件数を描く", async () => {
    await renderMinistry();
    expect(screen.getByRole("heading", { level: 1, name: "厚生労働省" })).toBeTruthy();
    // 型バッジとパンくずの両方に「府省」が出るので複数一致してよい。
    expect(screen.getAllByText("府省").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: /所管する予算事業/ })).toBeTruthy();
    expect(screen.getByText("50件")).toBeTruthy();
  });

  it("府省自身のパンくずに「所管」は無い(自分自身の所管は無いため)", async () => {
    await renderMinistry();
    const nav = screen.getByRole("navigation", { name: "現在位置" });
    expect(within(nav).getByRole("link", { name: "全体を見る" })).toBeTruthy();
    expect(within(nav).queryByRole("link", { name: "厚生労働省" })).toBeNull();
  });

  it("事実(属性)を出典1行にまとめ、属性ごとに出典を繰り返さない", async () => {
    await renderMinistry();
    const facts = screen.getByRole("complementary", { name: "事実" });
    expect(within(facts).getByText("千代田区")).toBeTruthy();
    // 旧画面は出典を属性ごとに繰り返し1画面に21個のリンクを生んだ。
    // 4属性・1出典に畳んだ今回は、出典のリンクはただ1つ。
    expect(within(facts).getAllByRole("link")).toHaveLength(1);
    expect(within(facts).getByRole("link").textContent).toBe("www.houjin-bangou.nta.go.jp");
    // 出典が1行しかないので、値に丸数字の印は付けない。
    expect(within(facts).queryByText("①")).toBeNull();
  });

  it("関係の一覧は<details>に畳まず、表としてそのまま見える", async () => {
    await renderMinistry();
    expect(document.querySelector("details")).toBeNull();
    expect(screen.getByRole("link", { name: "薬事工業生産動態統計調査業務費" })).toBeTruthy();
  });

  it("50件は先頭15件+「すべて見る」で残りを開ける(クライアント側の展開)", async () => {
    await renderMinistry();
    const user = userEvent.setup();
    const section = screen.getByRole("heading", { name: /所管する予算事業/ }).closest("section")!;
    expect(within(section).queryAllByRole("row")).toHaveLength(16); // 見出し行1 + 先頭15件
    await user.click(within(section).getByRole("button", { name: "すべて見る(50件)" }));
    expect(within(section).queryAllByRole("row")).toHaveLength(51); // 見出し行1 + 50件
    await user.click(within(section).getByRole("button", { name: "折りたたむ" }));
    expect(within(section).queryAllByRole("row")).toHaveLength(16);
  });

  it("relationships_truncated=trueなので「もっと見る」が出て、押すと上限まで再取得する", async () => {
    await renderMinistry();
    const user = userEvent.setup();
    expect(mockedEntityDetail).toHaveBeenCalledTimes(1);
    expect(mockedEntityDetail).toHaveBeenCalledWith("org/6000012070001", undefined);

    const loadMore = screen.getByRole("button", { name: /もっと見る/ });
    await user.click(loadMore);

    await waitFor(() => expect(mockedEntityDetail).toHaveBeenCalledWith("org/6000012070001", ENTITY_RELATIONSHIPS_LIMIT.max));
    // 打ち切りが解消したので、もう「もっと見る」は出ない。
    await waitFor(() => expect(screen.queryByRole("button", { name: /もっと見る/ })).toBeNull());
  });

  it("関係の行のリンクを押すと、そのエンティティへ遷移する(#/entity/...)", async () => {
    await renderMinistry();
    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: "薬事工業生産動態統計調査業務費" }));
    expect(window.location.hash).toBe("#/entity/budget/2025/1735");
  });

  it("「経路の始点にする」を押すと#/path?from=...へ遷移する", async () => {
    await renderMinistry();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "経路の始点にする" }));
    expect(window.location.hash).toBe("#/path?from=org%2F6000012070001");
  });

  it("「この画面について聞く」を押すと#/chatへ遷移する", async () => {
    await renderMinistry();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "この画面について聞く" }));
    expect(window.location.hash).toBe("#/chat");
  });

  it("「URLをコピー」を押すとクリップボードに現在のURLを書き込み、文言が変わる", async () => {
    await renderMinistry();
    const user = userEvent.setup();
    // `userEvent.setup()`が独自の`navigator.clipboard`実装を差し込むため、
    // それより後にスパイを仕込む(先に仕込んでも上書きされる)。
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    await user.click(screen.getByRole("button", { name: "URLをコピー" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "コピーしました" })).toBeTruthy());
    expect(writeText).toHaveBeenCalledWith(location.href);
  });

  it("「つながりをグラフで見る」を押すとグラフへスクロールする(scrollIntoViewを呼ぶ)", async () => {
    await renderMinistry();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "つながりをグラフで見る" }));
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("GraphViewへ中心(EntityRef)を渡し、GraphViewからの操作(中心移動)を配線する", async () => {
    await renderMinistry();
    expect(screen.getByTestId("graph-view-center").textContent).toBe("org/6000012070001");
    fireEvent.click(screen.getByRole("button", { name: /グラフでノードをクリック/ }));
    expect(window.location.hash).toBe("#/entity/budget/2025/1735");
  });

  it("GraphViewからの経路始点操作を#/path?from=...に配線する", async () => {
    await renderMinistry();
    fireEvent.click(screen.getByRole("button", { name: /グラフから経路の始点にする/ }));
    expect(window.location.hash).toBe("#/path?from=budget%2F2025%2F1735");
  });

  it("GraphViewからのパラメタ変更を、履歴を積まずにURLへ書き戻す(replaceGraphParams)", async () => {
    await renderMinistry();
    const before = history.length;
    fireEvent.click(screen.getByRole("button", { name: /深さを変える/ }));
    expect(window.location.hash).toBe("#/entity/org/6000012070001?d=2&lay=force");
    expect(history.length).toBe(before);
  });
});

describe("EntityPage(予算事業。実データ)", () => {
  beforeEach(() => {
    mockedEntityDetail.mockResolvedValue(entityProject());
  });

  it("予算額(Amount)・所管府省へのリンク・支出/年度予算/支出先ブロックの件数を描く", async () => {
    render(<EntityPage idPath="budget/2025/2841" />);
    await screen.findByRole("heading", { level: 1 });
    // 予算額はProjectBodyのStat(本体)とFactsPanel(サイド)の両方に出るため複数一致する。
    expect(screen.getAllByText(/4,628,011,000円/).length).toBeGreaterThan(0);
    // パンくずと「所管府省庁」欄の両方に厚生労働省へのリンクが出る。
    expect(screen.getAllByRole("link", { name: "厚生労働省" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "支出" })).toBeTruthy();
    expect(screen.getAllByRole("heading", { name: /年度予算/ }).length).toBeGreaterThan(0);
    // Sectionの見出し(h2)とRelationshipsの型ごとの見出し(h3)の両方に
    // 「支出先ブロック」が出る。
    expect(screen.getAllByRole("heading", { name: /支出先ブロック/ }).length).toBeGreaterThan(0);
  });

  it("パンくずに所管(厚生労働省)が現れる", async () => {
    render(<EntityPage idPath="budget/2025/2841" />);
    await screen.findByRole("heading", { level: 1 });
    const nav = screen.getByRole("navigation", { name: "現在位置" });
    expect(within(nav).getByRole("link", { name: "厚生労働省" })).toBeTruthy();
  });

  it("根拠法令が実データに無いため空表示になる(捏造しない)", async () => {
    render(<EntityPage idPath="budget/2025/2841" />);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText("根拠法令は記録されていません。")).toBeTruthy();
  });

  it("未解決の根拠が節として現れ、**元の記述がそのまま読める**(裁定B108)", async () => {
    // **この主張は2026-09-13に変わった。** それまでは「(表示名なし)」が
    // 出ることを固定していた——`UnresolvedReference` は `skos:prefLabel` を
    // 持たないため。APIが `described_by`(`core:unresolved_text`)を返すように
    // なって、元の文字列が読めるようになった。実サンプルを本番から取り直した
    // ことでこのテストが落ち、現実が変わったことを教えた。
    render(<EntityPage idPath="budget/2025/2841" />);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("heading", { name: /未解決の根拠/ })).toBeTruthy();
    const section = screen.getByRole("heading", { name: /未解決の根拠/ }).closest("section")!;
    expect(within(section).queryByText("(表示名なし)")).toBeNull();
    expect(within(section).getAllByText(/^元の記述 /).length).toBeGreaterThan(0);
  });

});

describe("EntityPage(読み込み中・見つからない・失敗の各状態)", () => {
  it("読み込み中はLoadingを描く", () => {
    mockedEntityDetail.mockReturnValue(new Promise(() => {})); // 解決させない
    render(<EntityPage idPath="org/x" />);
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("404(null)は「見つからなかった」と伝え、全体を見るへのリンクを出す", async () => {
    mockedEntityDetail.mockResolvedValue(null);
    render(<EntityPage idPath="org/x" />);
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain("見つかりません");
    expect(screen.getByRole("link", { name: /全体を見るに戻る/ })).toBeTruthy();
  });

  it("取得が失敗したら、失敗したことをそのまま伝える(嘘をつかない)", async () => {
    mockedEntityDetail.mockRejectedValue(new Error("APIが500を返しました"));
    render(<EntityPage idPath="org/x" />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("APIが500を返しました");
  });
});

describe("EntityPage(組織・法令・支出・汎用: 型分岐の配線を確かめる最小限の構造データ)", () => {
  // 実データのサンプルが無い型についても、`kindOf`がどの本体を選ぶかを
  // 確かめる。値そのもの(法人番号・法令番号等)は実在のものではない
  // ——政府データとしては提示せず、型分岐が正しく効くかだけを見る。
  const graphs: EntityDetailResponse["graphs"] = {
    "g/1": { graph: "g/1", source: "https://example.jp/x", fetched_on: "2026-01-01", license: "L", available: true },
  };

  function minimalEntity(overrides: Partial<EntityDetailResponse>): EntityDetailResponse {
    return {
      id: "https://example.jp/id/x",
      id_path: "x",
      type: "Organization",
      label: "テスト組織",
      attributes: {},
      relationships: {},
      graphs,
      relationships_limit: 50,
      relationships_truncated: false,
      ...overrides,
    };
  }

  it("Organization: 法人番号・受けた支出の表を描く", async () => {
    mockedEntityDetail.mockResolvedValue(
      minimalEntity({
        type: "Organization",
        label: "テスト組織",
        attributes: { houjinBangou: [{ value: "1234567890123", graphs: ["g/1"] }] },
        relationships: {
          Expenditure: [
            {
              predicate: "recipient",
              direction: "incoming",
              related: { id: "e", id_path: "budget/2025/1/0", label: "テスト支出", type: "Expenditure" },
              graph: "g/1",
            },
          ],
        },
      }),
    );
    render(<EntityPage idPath="org/test" />);
    await screen.findByRole("heading", { level: 1, name: "テスト組織" });
    // 法人番号もStat(本体)とFactsPanel(サイド)の両方に出る。
    expect(screen.getAllByText("1234567890123").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: /受けた支出/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "テスト支出" })).toBeTruthy();
  });

  it("Law: 法令番号・所管府省・改正記録の注記を描く", async () => {
    mockedEntityDetail.mockResolvedValue(
      minimalEntity({
        type: "Law",
        label: "テスト法",
        attributes: { lawNum: [{ value: "令和七年テスト法第一号", graphs: ["g/1"] }] },
        relationships: {
          Ministry: [
            {
              predicate: "jurisdiction",
              direction: "outgoing",
              related: { id: "m", id_path: "org/1", label: "テスト省", type: "Ministry" },
              graph: "g/1",
            },
          ],
        },
      }),
    );
    render(<EntityPage idPath="law/test" />);
    await screen.findByRole("heading", { level: 1, name: "テスト法" });
    // 法令番号もStat(本体)とFactsPanel(サイド)の両方に出る。
    expect(screen.getAllByText("令和七年テスト法第一号").length).toBeGreaterThan(0);
    // パンくずと「所管府省」の表の両方にリンクが出る。
    expect(screen.getAllByRole("link", { name: "テスト省" }).length).toBeGreaterThan(0);
    // グラフの下の注記と、根拠とする事業の節の注記の両方に出る。
    expect(screen.getAllByText(/改正記録.*辺を持たない/).length).toBeGreaterThan(0);
  });

  it("Expenditure: 金額・照合区分・支払先を描く", async () => {
    mockedEntityDetail.mockResolvedValue(
      minimalEntity({
        type: "Expenditure",
        label: "テスト支出",
        attributes: {
          amount_jpy: [{ value: "1000", graphs: ["g/1"] }],
          recipientMatchCategory: [{ value: "resolved", graphs: ["g/1"] }],
        },
        relationships: {
          Organization: [
            {
              predicate: "recipient",
              direction: "outgoing",
              related: { id: "o", id_path: "org/1", label: "テスト支払先", type: "Organization" },
              graph: "g/1",
            },
          ],
        },
      }),
    );
    render(<EntityPage idPath="budget/2025/1/0" />);
    await screen.findByRole("heading", { level: 1, name: "テスト支出" });
    // 支払先の照合区分もStat(本体)とFactsPanel(サイド)の両方に出る。
    expect(screen.getAllByText("法人番号で特定できた").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "テスト支払先" })).toBeTruthy();
  });

  it("汎用(それ以外の型): 属性と関係を相手型ごとの表で描く", async () => {
    mockedEntityDetail.mockResolvedValue(
      minimalEntity({
        type: "ExpenditureBlock",
        label: "テストブロック",
        relationships: {
          BudgetProject: [
            {
              predicate: "project",
              direction: "outgoing",
              related: { id: "p", id_path: "budget/2025/1", label: "テスト事業", type: "BudgetProject" },
              graph: "g/1",
            },
          ],
        },
      }),
    );
    render(<EntityPage idPath="budget/2025/1/block/A" />);
    await screen.findByRole("heading", { level: 1, name: "テストブロック" });
    expect(screen.getByRole("link", { name: "テスト事業" })).toBeTruthy();
  });

  it("labelがnullなら「(表示名なし)」と描く(表示名を合成しない。裁定B78/B88)", async () => {
    mockedEntityDetail.mockResolvedValue(minimalEntity({ type: "Organization", label: null }));
    render(<EntityPage idPath="org/test" />);
    await screen.findByRole("heading", { level: 1, name: "(表示名なし)" });
  });
  it("タブの名前をこのエンティティの表示名にする(履歴やブックマークで区別できるように)", async () => {
    document.title = "前の画面 — 日本政府ナレッジグラフ";
    mockedEntityDetail.mockResolvedValue(entityMinistry());
    render(<EntityPage idPath="org/6000012070001" />);
    // 応答が来るまでは「読み込み中」と正直に言う。
    expect(document.title).toBe("読み込み中 — 日本政府ナレッジグラフ");
    await screen.findByRole("heading", { level: 1, name: "厚生労働省" });
    expect(document.title).toBe("厚生労働省 — 日本政府ナレッジグラフ");
  });

  it("labelがnullならタブの名前も「(表示名なし)」(id_pathから名前を作らない)", async () => {
    mockedEntityDetail.mockResolvedValue(minimalEntity({ type: "Organization", label: null }));
    render(<EntityPage idPath="org/test" />);
    await screen.findByRole("heading", { level: 1, name: "(表示名なし)" });
    expect(document.title).toBe("(表示名なし) — 日本政府ナレッジグラフ");
  });
  it("AnnualBudgetはlabelを持たないが、見分けのための属性で年度が出る(裁定B108)", async () => {
    // **実サンプル(`entity-project.json`)は `described_by` を持たない**
    // ——APIに足す前に本番から取った応答なので、この場面だけ合成データを使う
    // (本番の応答を手で書き換えると「実サンプル」でなくなる)。値は年度を
    // 見分けられることだけを言う最小限にする。
    mockedEntityDetail.mockResolvedValue(
      minimalEntity({
        type: "BudgetProject",
        label: "テスト事業",
        relationships: {
          AnnualBudget: [
            {
              predicate: "project",
              direction: "incoming",
              related: {
                id: "https://example.jp/id/b/annual/2024",
                id_path: "b/annual/2024",
                type: "AnnualBudget",
                label: null,
                described_by: { predicate: "budgetFiscalYear", value: "2024" },
              },
              graph: "g/1",
            },
            {
              predicate: "project",
              direction: "incoming",
              related: {
                id: "https://example.jp/id/b/annual/2025",
                id_path: "b/annual/2025",
                type: "AnnualBudget",
                label: null,
                described_by: { predicate: "budgetFiscalYear", value: "2025" },
              },
              graph: "g/1",
            },
          ],
        },
      }),
    );
    render(<EntityPage idPath="budget/2025/2841" />);
    await screen.findByRole("heading", { level: 1 });
    const section = screen.getByRole("heading", { name: /年度予算/ }).closest("section")!;
    // **「表示名なし」が1件も無いこと**が要求(同じ文言が並ぶのをやめる)。
    expect(within(section).queryByText("(表示名なし)")).toBeNull();
    expect(within(section).getByRole("link", { name: "予算年度 2024" })).toBeTruthy();
    expect(within(section).getByRole("link", { name: "予算年度 2025" })).toBeTruthy();
  });

  it("見分けのための属性も無ければ、今までどおり「(表示名なし)」と言う", async () => {
    mockedEntityDetail.mockResolvedValue(
      minimalEntity({
        type: "BudgetProject",
        label: "テスト事業",
        relationships: {
          AnnualBudget: [
            {
              predicate: "project",
              direction: "incoming",
              related: {
                id: "https://example.jp/id/b/annual/2024",
                id_path: "b/annual/2024",
                type: "AnnualBudget",
                label: null,
              },
              graph: "g/1",
            },
          ],
        },
      }),
    );
    render(<EntityPage idPath="budget/2025/2841" />);
    await screen.findByRole("heading", { level: 1 });
    const section = screen.getByRole("heading", { name: /年度予算/ }).closest("section")!;
    expect(within(section).getByText("(表示名なし)")).toBeTruthy();
  });

  it("見出しとタブ名も見分けのための属性を使う(リンク先で「表示名なし」に戻らない)", async () => {
    mockedEntityDetail.mockResolvedValue(
      minimalEntity({
        id: "https://example.jp/id/b/annual/2024",
        id_path: "b/annual/2024",
        type: "AnnualBudget",
        label: null,
        described_by: { predicate: "budgetFiscalYear", value: "2024" },
      }),
    );
    render(<EntityPage idPath="b/annual/2024" />);
    await screen.findByRole("heading", { level: 1, name: "予算年度 2024" });
    expect(document.title).toBe("予算年度 2024 — 日本政府ナレッジグラフ");
  });
});
