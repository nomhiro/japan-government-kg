// 聞く(チャット)画面(#/chat)。旧画面(views/chat.ts)の置き換え。
//
// **旧画面の欠陥**: 同期で数十秒沈黙し、履歴が残らなかった。応答は素の段落
// だった。ここで直すべきことは team-lead の指示どおり最重要:
// 「応答を待つ間の見せ方」——APIはストリーミングしないので、偽の段階表示
// (「調査中→検索中→……」のような作り物の進捗)を作らない。実際に分かって
// いること(道具は最大6回まで呼ばれる・経過時間)だけを見せる。
import { useEffect, useRef, useState, type FormEvent, type JSX } from "react";
import type { ChatResponse, ChatSource } from "../../api/client";
import { ApiError, apiUnavailableReason, chat } from "../../api/client";
import { Band, ErrorBox, Section, SourceNote, TypeBadge } from "../../components/ui";
import { historyForWire, loadChatTurns, saveChatTurns, type ChatTurn } from "./chat-storage";
import "./chat.css";
import { displayName } from "../../lib/display-name";

// よくある問いのカード(UI文言。自分の言葉で書く——データの値ではない)。
const FAQ_QUESTIONS = [
  "厚生労働省が所管する予算事業をいくつか教えて",
  "年金に関する法律にはどんな種類がある?",
  "デジタル庁が所管する予算事業を教えて",
  "ある法人が支出先になっている予算事業を教えて",
] as const;

const TOOL_CALL_EXPLANATION = "ナレッジグラフを道具で調べています。道具は最大6回呼ばれます。";

export function ChatPage(): JSX.Element {
  const [turns, setTurns] = useState<ChatTurn[]>(() => loadChatTurns());
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [srStatus, setSrStatus] = useState("");
  const [elapsedSec, setElapsedSec] = useState(0);
  const logRef = useRef<HTMLDivElement>(null);

  // 履歴はsessionStorageに保存し、リロードで復元する(URLには載せない)。
  useEffect(() => {
    saveChatTurns(turns);
  }, [turns]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [turns, pending]);

  // **経過時間だけを数える。偽の段階を進めない。** 待っている間、本当に
  // 分かっているのは「道具は最大6回呼ばれる」ことと「経過した時間」だけ。
  useEffect(() => {
    if (!pending) return;
    const startedAt = Date.now();
    setElapsedSec(0);
    const timer = setInterval(() => setElapsedSec(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [pending]);

  const unavailable = apiUnavailableReason();

  async function submit(message: string): Promise<void> {
    const wireHistory = historyForWire(turns);
    setTurns((prev) => [...prev, { role: "user", content: message }]);
    setPending(true);
    // スクリーンリーダー向けの通知は開始時と終了時の2回だけ(`aria-live`の
    // 領域を経過秒ごとに書き換えると、その秒読みが毎秒読み上げられてしまう)。
    setSrStatus(TOOL_CALL_EXPLANATION);
    try {
      const res = await chat(message, wireHistory);
      const { answer, ...meta } = res;
      setTurns((prev) => [...prev, { role: "assistant", content: answer, meta }]);
      setSrStatus("回答が届きました。");
    } catch (e) {
      // **正直に失敗を出す。** 429(レート制限/日次予算)は`ApiError.message`に
      // 既に人間向けの文言が入っている——ここで別の言い回しに書き換えない。
      const errorMessage = e instanceof ApiError ? e.message : String(e);
      setTurns((prev) => [...prev, { role: "assistant", content: "", error: errorMessage }]);
      setSrStatus("エラーが発生しました。");
    } finally {
      setPending(false);
    }
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const message = input.trim();
    if (!message || pending) return;
    setInput("");
    void submit(message);
  }

  if (unavailable) {
    return (
      <Band full>
        <Section title="聞く">
          <ErrorBox>チャットは準備中です。{unavailable}</ErrorBox>
        </Section>
      </Band>
    );
  }

  return (
    <Band full>
      <Section
        title="聞く"
        note={
          <span>
            法令・府省・予算事業・法人のつながりについて質問すると、道具(検索・エンティティ詳細・
            近傍・経路・オントロジー)を使って調べ、その結果だけから出典付きで答えます。道具が何も
            見つけなければ「見つからなかった」と答えます——自分の知識で補うことはしません。
          </span>
        }
      >
        {/* 秒読みそのものはここに入れない(毎秒読み上げられてしまう)。開始/終了の2回だけ通知する。 */}
        <div aria-live="polite" className="jg-sr">
          {srStatus}
        </div>

        <div className="jg-chat-log" ref={logRef}>
          {turns.map((turn, i) => (
            <ChatTurnView key={i} turn={turn} />
          ))}
          {pending ? <PendingNotice elapsedSec={elapsedSec} /> : null}
        </div>

        {turns.length === 0 ? (
          <div className="jg-chat-faq">
            <span className="jg-eyebrow">よくある問い</span>
            <div className="jg-chat-faq__cards">
              {FAQ_QUESTIONS.map((q) => (
                <button key={q} type="button" className="jg-chat-faq__card" onClick={() => setInput(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        <form className="jg-chat-form" onSubmit={handleSubmit}>
          <textarea
            className="jg-chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="例: 厚生労働省が所管する予算事業をいくつか、出典付きで教えて"
            aria-label="質問"
            disabled={pending}
            rows={3}
          />
          <button type="submit" className="jg-btn jg-btn--primary" disabled={pending || !input.trim()}>
            送信
          </button>
        </form>
      </Section>
    </Band>
  );
}

function PendingNotice({ elapsedSec }: { elapsedSec: number }): JSX.Element {
  return (
    <div className="jg-chat-pending">
      <span className="jg-loading__bar" aria-hidden="true" />
      <div>
        <p className="jg-sm">{TOOL_CALL_EXPLANATION}</p>
        <p className="jg-xs jg-muted jg-num">経過 {elapsedSec}秒</p>
      </div>
    </div>
  );
}

function ChatTurnView({ turn }: { turn: ChatTurn }): JSX.Element {
  if (turn.role === "user") {
    return (
      <div className="jg-chat-turn jg-chat-turn--user">
        <div className="jg-chat-bubble">{turn.content}</div>
      </div>
    );
  }
  if (turn.error !== undefined) {
    return (
      <div className="jg-chat-turn jg-chat-turn--assistant">
        <ErrorBox>{turn.error}</ErrorBox>
      </div>
    );
  }
  return (
    <div className="jg-chat-turn jg-chat-turn--assistant">
      <div className="jg-chat-bubble">{turn.content}</div>
      {turn.meta ? <AssistantMeta meta={turn.meta} /> : null}
    </div>
  );
}

function AssistantMeta({ meta }: { meta: Omit<ChatResponse, "answer"> }): JSX.Element {
  return (
    <div className="jg-stack jg-stack--2 jg-chat-meta">
      {meta.tool_call_limit_reached ? (
        <p className="jg-sm jg-muted">
          道具の呼び出し回数の上限({meta.tool_call_limit}回)に達しました。ここまでの調査結果だけで回答しています。
        </p>
      ) : null}
      {meta.truncated ? (
        <p className="jg-sm jg-muted">モデルの出力上限に達し、回答が途中で切れている可能性があります。</p>
      ) : null}

      {meta.sources.length > 0 ? (
        <details className="jg-chat-sources">
          {/* 「出典」と呼ばない(裁定B94): 道具が触れたものすべてで、回答が使ったものに限らない。 */}
          <summary>調べたエンティティ({meta.sources.length}件)</summary>
          <p className="jg-xs jg-muted">道具が実際に返したものの一覧です。回答が使ったものに限りません。</p>
          <ul>
            {meta.sources.map((s) => (
              <ChatSourceRow key={s.id_path} source={s} graphs={meta.graphs} />
            ))}
          </ul>
        </details>
      ) : null}

      {meta.ontology_sources.length > 0 ? (
        // 政府データの出典(SourceNote)とは種類が違うので混ぜない(裁定B94)。
        <div className="jg-chat-sources">
          <span className="jg-eyebrow">根拠にした語彙({meta.ontology_sources.length}件)</span>
          <ul>
            {meta.ontology_sources.map((o) => (
              <li key={o.module}>
                <a href={o.url} target="_blank" rel="noopener noreferrer">
                  {o.module}
                </a>
                モジュールの定義
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {meta.sources.length === 0 && meta.ontology_sources.length === 0 ? (
        <p className="jg-xs jg-muted">出典なし(道具が何も見つけられませんでした)</p>
      ) : null}

      <details className="jg-chat-tool-log">
        <summary>道具の呼び出し履歴({meta.tool_calls.length}件)</summary>
        {meta.tool_calls.length === 0 ? (
          <p className="jg-xs jg-muted">道具は呼び出されませんでした。</p>
        ) : (
          <ul>
            {meta.tool_calls.map((tc, i) => (
              <li key={i} className="jg-xs">
                <code>{tc.tool}</code>{" "}
                <span className="jg-muted">
                  ({Object.entries(tc.arguments).map(([k, v]) => `${k}=${String(v)}`).join(", ")})
                </span>{" "}
                → {tc.result_count}件
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}

function ChatSourceRow({ source, graphs }: { source: ChatSource; graphs: ChatResponse["graphs"] }): JSX.Element {
  return (
    <li className="jg-chat-source">
      <TypeBadge type={source.type} size="sm" />
      <span>{displayName(source)}</span>
      {source.graphs.length > 0 ? (
        <SourceNote graphs={graphs} onlyGraphs={source.graphs} />
      ) : (
        <span className="jg-xs jg-muted">出典が取れていない</span>
      )}
    </li>
  );
}
