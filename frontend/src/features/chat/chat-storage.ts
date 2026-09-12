// チャット履歴の保存(仕様: 履歴は`sessionStorage`に保存し、リロードで復元する。
// URLには載せない——会話内容をURLに残さないための判断)。
//
// **DOM(`document`/`window`以外)に依存しない純粋関数群にしてある**。
// `sessionStorage`はブラウザのグローバルだが、jsdom環境なら本物と同じ挙動で
// 動くため、DOM非依存の他ファイル(`format.ts`等)と同じ分離までは行わず、
// ここに直接置く——`ChatPage.tsx`から呼ぶだけの薄い層。
import type { ChatResponse } from "../../api/client";

export type ChatTurnRole = "user" | "assistant";

export interface ChatTurn {
  readonly role: ChatTurnRole;
  readonly content: string;
  /** assistantターンのみ持つ、応答の構造情報(裁定B92裁定2)。 */
  readonly meta?: Omit<ChatResponse, "answer">;
  /** 送信に失敗したとき(429等)のエラー文言。答えではないので`content`と混ぜない。 */
  readonly error?: string;
}

const STORAGE_KEY = "jgkg-chat-history";

function isChatTurn(v: unknown): v is ChatTurn {
  if (typeof v !== "object" || v === null) return false;
  const obj = v as Record<string, unknown>;
  if (obj.role !== "user" && obj.role !== "assistant") return false;
  if (typeof obj.content !== "string") return false;
  if (obj.error !== undefined && typeof obj.error !== "string") return false;
  return true;
}

/**
 * 保存されている履歴を読む。無い・壊れている・`sessionStorage`が使えない
 * (プライベートモード等)場合は空配列——チャット自体は続行できるので
 * 例外を投げない(履歴が消えるだけの縮退)。
 */
export function loadChatTurns(): ChatTurn[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isChatTurn);
  } catch {
    return [];
  }
}

/** 履歴を保存する。`sessionStorage`が使えない場合は黙って諦める(チャットは続行できる)。 */
export function saveChatTurns(turns: readonly ChatTurn[]): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns));
  } catch {
    // 保存できないだけで、チャット自体は続行できる。
  }
}

/** 履歴を消す(将来「履歴を消す」操作を足すときのための土台。今は未使用でも置いておく)。 */
export function clearChatTurns(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // 何もできないなら何もしない。
  }
}

/**
 * APIに送る`history`(`ChatMessage[]`)を組み立てる。
 *
 * **エラーになったターンは送らない**——`error`を持つターンは実際の
 * assistant発言ではない(空文字の`content`しか持たない)。これを履歴に
 * 混ぜると、次のリクエストで「assistantが空文字を発言した」という
 * 存在しない会話をサーバに送ることになる。
 */
export function historyForWire(turns: readonly ChatTurn[]): { role: ChatTurnRole; content: string }[] {
  return turns.filter((t) => t.error === undefined).map((t) => ({ role: t.role, content: t.content }));
}
