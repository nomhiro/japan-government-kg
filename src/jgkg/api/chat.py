"""オントロジーをAgenticに調査して答えるチャットの本体(E-2。裁定B92)。

ルート(`app.py`)は`ChatService.handle_chat()`しか呼ばない
(`queries.py`のモジュールdocstringと同じ、HTTP層とロジックを分ける作法)。

**このモジュールが実装する3つの裁定:**

- **裁定1(生のSPARQLを渡さない)**: 道具は`chat_tools.run_tool`が実行する
  5つに限る。ここでは道具名の集合を意識しない——`chat_tools.build_tool_schemas`
  が返すJSON Schemaをそのままモデルに渡すだけ
- **裁定2(出典の無い答えを返さない)**: `SYSTEM_PROMPT`で明示し、
  `chat_tools.SourceCollector`が道具の戻り値だけから`sources`を組み立てる
- **裁定3(費用の上限を構造で縛る)**: `ToolCallBudgetExceeded`は起きない
  (ループ側が上限で止める。黙って打ち切らない=`tool_call_limit_reached`を
  必ず立てる)。`RateLimitExceeded`/`DailyTokenBudgetExceeded`はルートが
  HTTP 429にする。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jgkg.api.chat_tools import SourceCollector, build_tool_schemas, run_tool
from jgkg.api.kgclient import KGClient
from jgkg.api.llm import ChatModel, parse_tool_arguments
from jgkg.api.models import ChatRequest, ChatResponse, ChatSource, ToolCallLogEntry

SYSTEM_PROMPT = """あなたは日本政府オープンデータのナレッジグラフ(JGKG)を、
道具(tools)を使って調査し、その結果だけから日本語で答えるアシスタントです。

規則:
1. **道具の結果だけから答えてください。** あなた自身が既に知っている日本政府に
   関する知識で補ってはいけません。道具を1回も呼ばずに事実を答えることも、
   道具の結果に無い事実を付け加えることも禁止します。
2. **道具が何も返さなければ「見つからなかった」と答えてください。**
   確信が持てないときに、無いものをあるかのように書かないでください。
3. エンティティの実データを調べたいときは`search_entities`(検索)・
   `get_entity`(詳細)・`get_neighborhood`(近傍)・`find_path`(2点間の経路)を
   使ってください。語彙・クラス・プロパティの定義そのものを確認したいときは
   `get_ontology`を使ってください。
4. 道具の呼び出し回数には上限があります。上限に達した後は道具を呼べません
   ——それまでに分かったことだけで答えてください。
5. 回答の最後に、根拠にした主なエンティティを`id_path`で短く列挙してください。
   出典リンクは画面側が別に描くので、ここでは触れるだけで十分です。
"""


class RateLimitExceeded(Exception):
    """IPごとの分あたりレート制限(裁定B92裁定3(2))に達した。"""


class DailyTokenBudgetExceeded(Exception):
    """1日あたりのトークン予算(裁定B92裁定3(3))を使い切った。"""


class RateLimiter:
    """IPごとの固定窓(60秒)レート制限。プロセス内カウンタ
    (`maxReplicas=1`前提。裁定B92裁定3(4))。スレッド安全(uvicornの
    同期ルートはスレッドプールで実行される)。
    """

    def __init__(self, limit_per_minute: int, *, clock: object = time.time) -> None:
        self._limit = limit_per_minute
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}  # ip -> (window_start_minute, count)

    def check(self, client_ip: str) -> None:
        now_minute = int(self._clock() // 60)  # type: ignore[operator]
        with self._lock:
            window_start, count = self._windows.get(client_ip, (now_minute, 0))
            if window_start != now_minute:
                window_start, count = now_minute, 0
            count += 1
            self._windows[client_ip] = (window_start, count)
            if count > self._limit:
                raise RateLimitExceeded(
                    f"IPごとの利用上限(1分あたり{self._limit}回)に達しました"
                )


class DailyTokenBudget:
    """1日あたりのトークン予算。プロセス内カウンタ(`maxReplicas=1`前提)。

    **日の境界はUTC。** JSTの日付境界とはずれる(「本日」という文言に対して
    厳密ではない)——公開財の費用上限という目的にはこの粒度で足りると判断した
    (気になる点として報告する)。
    """

    def __init__(self, daily_budget: int, *, clock: object = time.time) -> None:
        self._budget = daily_budget
        self._clock = clock
        self._lock = threading.Lock()
        self._date = self._today()
        self._used = 0

    def _today(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=UTC).date().isoformat()  # type: ignore[operator]

    def ensure_available(self) -> None:
        """まだ予算が残っているかを確認する(呼ぶだけでは消費しない)。"""
        with self._lock:
            self._roll_if_new_day()
            if self._used >= self._budget:
                raise DailyTokenBudgetExceeded("本日のAI利用上限に達しました")

    def record(self, tokens: int) -> None:
        with self._lock:
            self._roll_if_new_day()
            self._used += tokens

    def _roll_if_new_day(self) -> None:
        today = self._today()
        if today != self._date:
            self._date = today
            self._used = 0


@dataclass
class ChatService:
    kg_client: KGClient
    base_uri: str
    generated_dir: Path
    chat_model: ChatModel
    tool_call_limit: int
    max_completion_tokens: int
    rate_limiter: RateLimiter
    daily_budget: DailyTokenBudget

    def handle_chat(self, request: ChatRequest, client_ip: str) -> ChatResponse:
        self.rate_limiter.check(client_ip)
        self.daily_budget.ensure_available()

        tool_schemas = build_tool_schemas(self.generated_dir)
        messages: list[dict[str, object]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in request.history:
            messages.append({"role": turn.role, "content": turn.content})
        messages.append({"role": "user", "content": request.message})

        collector = SourceCollector()
        tool_call_log: list[ToolCallLogEntry] = []
        tool_calls_used = 0
        limit_reached = False
        truncated = False
        answer = ""

        # **安全上限は`tool_call_limit`より少し大きい**(道具呼び出し無しで
        # 終わる最後の1往復のぶん)。無限ループを構造的に防ぐための値であり、
        # 業務上の意味は持たない(道具呼び出し自体の上限は`tool_calls_used`側で縛る)
        max_iterations = self.tool_call_limit + 2
        for _ in range(max_iterations):
            self.daily_budget.ensure_available()
            offer_tools = tool_calls_used < self.tool_call_limit
            result = self.chat_model.complete(
                messages,
                tool_schemas if offer_tools else [],
                self.max_completion_tokens,
            )
            self.daily_budget.record(result.total_tokens)

            if result.finish_reason == "length":
                truncated = True

            if not result.tool_calls:
                answer = result.content or ""
                break

            # アシスタントのtool_calls付きメッセージを履歴に積む(Chat
            # Completionsの契約: 直後に対応する"tool"メッセージが要る)
            messages.append(
                {
                    "role": "assistant",
                    "content": result.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.arguments_json},
                        }
                        for tc in result.tool_calls
                    ],
                }
            )

            for tc in result.tool_calls:
                if tool_calls_used >= self.tool_call_limit:
                    limit_reached = True
                    tool_content = '{"error": "道具呼び出しの上限に達したため実行しなかった"}'
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": tool_content}
                    )
                    continue
                arguments: dict[str, object] = {}
                try:
                    arguments = parse_tool_arguments(tc.arguments_json)
                    invocation = run_tool(
                        tc.name,
                        arguments,
                        kg_client=self.kg_client,
                        base_uri=self.base_uri,
                        generated_dir=self.generated_dir,
                        collector=collector,
                    )
                except Exception as e:  # noqa: BLE001 - 道具の失敗を必ず履歴に残す(黙って落とさない)
                    invocation_count = 0
                    tool_content = f'{{"error": "道具の実行に失敗: {str(e)!r}"}}'
                else:
                    invocation_count = invocation.result_count
                    tool_content = invocation.content
                tool_calls_used += 1
                tool_call_log.append(
                    ToolCallLogEntry(
                        tool=tc.name,
                        arguments=_stringify_arguments(arguments),
                        result_count=invocation_count,
                    )
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_content})
        else:
            # **安全上限そのものに達した(通常は起こらない)。** 黙って
            # 空の答えを返さない——上限到達として扱う(裁定B77の族)
            limit_reached = True
            answer = "(内部の反復回数の上限に達したため、ここまでの調査結果のみで回答します)"

        # **`tool_calls_used`がちょうど上限に達しただけで、モデルがそれ以上
        # 呼ぼうとしなかった場合も「上限に達した」である。** 直前のループ内の
        # 判定(道具呼び出しをその場で拒否したとき)だけに頼ると、この
        # 「ちょうど使い切って、次のモデル呼び出しでは道具を提示しなかった
        # (offer_tools=False)ため、モデル自身も要求しなかった」経路を
        # 取り落とす——ここで一度、実際に使った回数から再判定して確実にする
        if tool_calls_used >= self.tool_call_limit:
            limit_reached = True

        sources_raw, graphs = collector.finalize()
        sources = [ChatSource.model_validate(s) for s in sources_raw]
        return ChatResponse(
            answer=answer,
            sources=sources,
            graphs=graphs,
            tool_calls=tool_call_log,
            tool_call_limit=self.tool_call_limit,
            tool_call_limit_reached=limit_reached,
            truncated=truncated,
        )


def _stringify_arguments(arguments: dict[str, object]) -> dict[str, str | int]:
    """`ToolCallLogEntry.arguments`(`dict[str, str | int]`)に合わせて値を落とす。

    モデルの生成した引数は型が保証されない(JSON任意値)——監査ログとしては
    表示できれば十分なので、`str`/`int`以外は`str()`で落とす(落とすことを
    明示するためのヘルパーとして1箇所にまとめる)。
    """
    out: dict[str, str | int] = {}
    for k, v in arguments.items():
        out[k] = v if isinstance(v, (str, int)) and not isinstance(v, bool) else str(v)
    return out
