// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import type { ChatTurn } from "./chat-storage";
import { clearChatTurns, historyForWire, loadChatTurns, saveChatTurns } from "./chat-storage";

afterEach(() => {
  sessionStorage.clear();
});

describe("loadChatTurns / saveChatTurns", () => {
  it("何も保存されていなければ空配列を返す", () => {
    expect(loadChatTurns()).toEqual([]);
  });

  it("保存した履歴をそのまま復元できる", () => {
    const turns: ChatTurn[] = [
      { role: "user", content: "厚生労働省が所管する予算事業を教えて" },
      { role: "assistant", content: "たとえば…", meta: undefined },
    ];
    saveChatTurns(turns);
    expect(loadChatTurns()).toEqual(turns);
  });

  it("**核心**: 壊れたJSONが入っていても例外を投げず、空配列に縮退する", () => {
    sessionStorage.setItem("jgkg-chat-history", "{not json");
    expect(loadChatTurns()).toEqual([]);
  });

  it("配列でない値が入っていても空配列に縮退する", () => {
    sessionStorage.setItem("jgkg-chat-history", JSON.stringify({ role: "user" }));
    expect(loadChatTurns()).toEqual([]);
  });

  it("role/contentの形を満たさない要素は読み飛ばす(全部を捨てない)", () => {
    sessionStorage.setItem(
      "jgkg-chat-history",
      JSON.stringify([{ role: "user", content: "ok" }, { role: "invalid" }, { content: 42 }]),
    );
    expect(loadChatTurns()).toEqual([{ role: "user", content: "ok" }]);
  });

  it("clearChatTurnsで消せる", () => {
    saveChatTurns([{ role: "user", content: "x" }]);
    clearChatTurns();
    expect(loadChatTurns()).toEqual([]);
  });
});

describe("historyForWire", () => {
  it("role/contentだけの形に変換する(metaを送らない)", () => {
    const turns: ChatTurn[] = [
      { role: "user", content: "質問" },
      {
        role: "assistant",
        content: "回答",
        meta: {
          sources: [],
          ontology_sources: [],
          graphs: {},
          tool_calls: [],
          tool_call_limit: 6,
          tool_call_limit_reached: false,
          truncated: false,
        },
      },
    ];
    expect(historyForWire(turns)).toEqual([
      { role: "user", content: "質問" },
      { role: "assistant", content: "回答" },
    ]);
  });

  it("**核心**: エラーになったターン(error持ち)は送らない——存在しないassistant発言をサーバに送らない", () => {
    const turns: ChatTurn[] = [
      { role: "user", content: "質問" },
      { role: "assistant", content: "", error: "本日の利用上限に達しました" },
    ];
    expect(historyForWire(turns)).toEqual([{ role: "user", content: "質問" }]);
  });
});
