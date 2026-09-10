// オントロジーをAgenticに調査して答えるチャット画面(E-2。裁定B92)。
//
// **このチャットは装飾ではない。** 原則1「本体はオントロジーとKG、アプリは
// 検証装置」に照らして、この画面自体が「LLMがこの語彙を読んで正しく辿れるか」
// を利用者の目の前で実演する検証装置である——だからこそ、道具の呼び出し履歴
// (裁定B92裁定2(3))と出典(裁定2(2))を隠さず見せる。
import type { ChatMessage, ChatResponse } from "../api/client";
import { ApiError, apiUnavailableReason, chat } from "../api/client";
import { chatSourceHtml, esc, toolCallLogEntryHtml } from "../format";

interface Turn {
  role: "user" | "assistant";
  content: string;
  //: assistant turnのみ持つ、応答の構造情報(裁定B92裁定2)
  meta?: Omit<ChatResponse, "answer">;
}

export function renderChat(container: HTMLElement): void {
  // 裁定B82(2)と同じ判断(search.ts/entity.tsと同じ理由): APIが未配備なら、
  // 失敗するとわかっている取得を試みない
  const unavailable = apiUnavailableReason();
  if (unavailable) {
    container.innerHTML = `
      <p><a href="#/">&larr; 検索に戻る</a></p>
      <h1>オントロジーに質問する</h1>
      <p class="jgkg-notice">チャットは準備中です。${esc(unavailable)}</p>
    `;
    return;
  }

  const turns: Turn[] = [];

  container.innerHTML = `
    <p><a href="#/">&larr; 検索に戻る</a></p>
    <h1>オントロジーに質問する</h1>
    <p class="jgkg-lead">
      法令・府省・予算事業・支出・法人のつながりについて質問すると、
      道具(検索・エンティティ詳細・近傍・経路・オントロジー)を使って調べ、
      道具の結果だけから出典付きで答えます。道具が何も見つけなければ
      「見つからなかった」と答えます——自分の知識で補うことは禁止しています。
    </p>
    <div class="jgkg-chat-log" aria-live="polite"></div>
    <form class="jgkg-chat-form">
      <input type="text" class="jgkg-chat-input"
             placeholder="例: 厚生労働省が所管する予算事業をいくつか、出典付きで教えて">
      <button type="submit">送信</button>
    </form>
  `;

  const log = container.querySelector<HTMLElement>(".jgkg-chat-log")!;
  const form = container.querySelector<HTMLFormElement>(".jgkg-chat-form")!;
  const input = container.querySelector<HTMLInputElement>(".jgkg-chat-input")!;
  const submitButton = form.querySelector<HTMLButtonElement>("button[type=submit]")!;

  function renderTurns(pending: boolean): void {
    const turnsHtml = turns
      .map((turn) => (turn.role === "user" ? userTurnHtml(turn) : assistantTurnHtml(turn)))
      .join("");
    log.innerHTML = turnsHtml + (pending ? '<div class="jgkg-chat-turn jgkg-chat-assistant"><p class="jgkg-muted">調査中…</p></div>' : "");
    log.scrollTop = log.scrollHeight;
  }

  function userTurnHtml(turn: Turn): string {
    return `
      <div class="jgkg-chat-turn jgkg-chat-user">
        <div class="jgkg-chat-bubble">${esc(turn.content)}</div>
      </div>`;
  }

  function assistantTurnHtml(turn: Turn): string {
    const meta = turn.meta;
    if (!meta) return `<div class="jgkg-chat-turn jgkg-chat-assistant"><div class="jgkg-chat-bubble">${esc(turn.content)}</div></div>`;

    const limitNotice = meta.tool_call_limit_reached
      ? `<p class="jgkg-notice">道具の呼び出し回数の上限(${meta.tool_call_limit}回)に達しました。ここまでの調査結果だけで回答しています。</p>`
      : "";
    const truncatedNotice = meta.truncated
      ? `<p class="jgkg-notice">モデルの出力上限に達し、回答が途中で切れている可能性があります。</p>`
      : "";
    const sourcesHtml =
      meta.sources.length > 0
        ? `<div class="jgkg-chat-sources">
             <h4>出典(${meta.sources.length}件)</h4>
             <ul>${meta.sources.map((s) => `<li>${chatSourceHtml(s, meta.graphs)}</li>`).join("")}</ul>
           </div>`
        : `<p class="jgkg-muted">出典なし(道具が何も見つけられませんでした)</p>`;
    const toolLogHtml = `
      <details class="jgkg-chat-tool-log">
        <summary>道具の呼び出し履歴(${meta.tool_calls.length}件)</summary>
        <ul>${meta.tool_calls.map((tc) => `<li>${toolCallLogEntryHtml(tc)}</li>`).join("") || '<li class="jgkg-muted">道具は呼び出されませんでした</li>'}</ul>
      </details>`;

    return `
      <div class="jgkg-chat-turn jgkg-chat-assistant">
        <div class="jgkg-chat-bubble">${esc(turn.content)}</div>
        ${limitNotice}
        ${truncatedNotice}
        ${sourcesHtml}
        ${toolLogHtml}
      </div>`;
  }

  function historyForWire(): ChatMessage[] {
    return turns.map((t) => ({ role: t.role, content: t.content }));
  }

  async function submit(message: string): Promise<void> {
    const wireHistory = historyForWire();
    turns.push({ role: "user", content: message });
    renderTurns(true);
    input.value = "";
    input.disabled = true;
    submitButton.disabled = true;
    try {
      const res = await chat(message, wireHistory);
      const { answer, ...meta } = res;
      turns.push({ role: "assistant", content: answer, meta });
    } catch (e) {
      // **正直に失敗を出す(裁定B92裁定3)。** 429(レート制限/日次予算)は
      // `ApiError.message`に既に人間向けの文言が入っている(api/client.tsの
      // `chat()`参照)——ここで別の言い回しに書き換えない
      const message = e instanceof ApiError ? e.message : String(e);
      turns.push({ role: "assistant", content: `エラー: ${message}` });
    } finally {
      renderTurns(false);
      input.disabled = false;
      submitButton.disabled = false;
      input.focus();
    }
  }

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    void submit(message);
  });
}
