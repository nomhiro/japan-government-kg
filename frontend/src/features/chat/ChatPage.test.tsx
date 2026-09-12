// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatResponse } from "../../api/client";
import { ChatPage } from "./ChatPage";
import { loadChatTurns, saveChatTurns } from "./chat-storage";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, chat: vi.fn() };
});
import { ApiError, chat } from "../../api/client";
const chatMock = vi.mocked(chat);

afterEach(() => {
  cleanup();
  chatMock.mockReset();
  sessionStorage.clear();
});

function emptyMeta(): Omit<ChatResponse, "answer"> {
  return {
    sources: [],
    ontology_sources: [],
    graphs: {},
    tool_calls: [],
    tool_call_limit: 6,
    tool_call_limit_reached: false,
    truncated: false,
  };
}

describe("ChatPage", () => {
  it("sessionStorageに保存された履歴をリロード後も復元して表示する", () => {
    saveChatTurns([
      { role: "user", content: "厚生労働省が所管する予算事業を教えて" },
      { role: "assistant", content: "たとえばこちらです。", meta: emptyMeta() },
    ]);
    render(<ChatPage />);
    expect(screen.getByText("厚生労働省が所管する予算事業を教えて")).toBeTruthy();
    expect(screen.getByText("たとえばこちらです。")).toBeTruthy();
  });

  it("よくある問いのカードを押すと、送信せずに質問欄へ文言が入る", async () => {
    render(<ChatPage />);
    const user = userEvent.setup();
    const card = screen.getAllByRole("button", { name: /厚生労働省/ })[0]!;
    await user.click(card);
    expect(screen.getByRole("textbox", { name: "質問" })).toHaveProperty(
      "value",
      "厚生労働省が所管する予算事業をいくつか教えて",
    );
    expect(chatMock).not.toHaveBeenCalled();
  });

  it("**核心**: 待っている間は経過秒数を数えるだけで、偽の段階を出さない。応答が来たら答え・調べたエンティティ・根拠にした語彙・道具呼び出し履歴を出し、履歴を保存する", async () => {
    let resolveChat!: (value: ChatResponse) => void;
    chatMock.mockImplementation(
      () =>
        new Promise<ChatResponse>((resolve) => {
          resolveChat = resolve;
        }),
    );

    render(<ChatPage />);
    const textbox = screen.getByRole("textbox", { name: "質問" });
    fireEvent.change(textbox, { target: { value: "厚生労働省が所管する予算事業を教えて" } });
    fireEvent.submit(textbox.closest("form")!);

    const pendingArea = await waitFor(() => document.querySelector<HTMLElement>(".jg-chat-pending")!);
    expect(within(pendingArea).getByText("ナレッジグラフを道具で調べています。道具は最大6回呼ばれます。")).toBeTruthy();
    // 経過秒数の表示があり、実際に時間が進むにつれて増える(偽の段階は出ない)。
    expect(within(pendingArea).getByText(/経過 [0-9]+秒/)).toBeTruthy();
    await waitFor(
      () => {
        const el = within(pendingArea).getByText(/経過 [0-9]+秒/);
        expect(el.textContent).not.toBe("経過 0秒");
      },
      { timeout: 3000 },
    );
    // 偽の段階(「検索中」「読み込み中」等の作り物のステップ)は出ていない
    expect(screen.queryByText(/検索中/)).toBeNull();

    const response: ChatResponse = {
      answer: "厚生労働省が所管する予算事業には、①国民年金基金等給付費負担金などがあります。",
      sources: [
        {
          id: "https://jgkg.norr-tech.com/id/budget/2025/2841",
          id_path: "budget/2025/2841",
          type: "BudgetProject",
          label: "①国民年金基金等給付費負担金",
          graphs: ["g1"],
        },
      ],
      ontology_sources: [{ module: "budget", url: "/def/budget" }],
      graphs: {
        g1: {
          graph: "g1",
          source: "https://laws.e-gov.go.jp/",
          fetched_on: "2026-08-25",
          license: "PDL1.0",
          available: true,
        },
      },
      tool_calls: [{ tool: "search_entities", arguments: { q: "厚生労働省" }, result_count: 1 }],
      tool_call_limit: 6,
      tool_call_limit_reached: false,
      truncated: false,
    };

    resolveChat(response);

    expect(await screen.findByText(response.answer)).toBeTruthy();
    expect(screen.getByText("調べたエンティティ(1件)")).toBeTruthy();
    expect(screen.getByText("①国民年金基金等給付費負担金")).toBeTruthy();
    expect(screen.getByText(/根拠にした語彙/)).toBeTruthy();
    expect(screen.getByText("道具の呼び出し履歴(1件)")).toBeTruthy();

    await waitFor(() => {
      const saved = loadChatTurns();
      expect(saved).toHaveLength(2);
      expect(saved[1]!.content).toBe(response.answer);
    });
  });

  it("道具呼び出し上限に達した・回答が切れた通知を出す", async () => {
    chatMock.mockResolvedValue({
      answer: "調査は途中までです。",
      sources: [],
      ontology_sources: [],
      graphs: {},
      tool_calls: [],
      tool_call_limit: 6,
      tool_call_limit_reached: true,
      truncated: true,
    });
    render(<ChatPage />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "質問" }), "質問");
    await user.click(screen.getByRole("button", { name: "送信" }));

    expect(await screen.findByText(/道具の呼び出し回数の上限\(6回\)に達しました/)).toBeTruthy();
    expect(screen.getByText(/回答が途中で切れている可能性があります/)).toBeTruthy();
  });

  it("**核心**: 429等の失敗はApiError.messageをそのまま出し、次の送信の履歴には含めない", async () => {
    chatMock.mockRejectedValueOnce(new ApiError(429, "本日の利用上限に達しました"));
    chatMock.mockResolvedValueOnce({ answer: "2回目の回答", ...emptyMeta() });

    render(<ChatPage />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "質問" }), "1回目");
    await user.click(screen.getByRole("button", { name: "送信" }));
    expect(await screen.findByText("本日の利用上限に達しました")).toBeTruthy();

    await user.type(screen.getByRole("textbox", { name: "質問" }), "2回目");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await screen.findByText("2回目の回答");

    expect(chatMock).toHaveBeenLastCalledWith("2回目", [{ role: "user", content: "1回目" }]);
  });
});
