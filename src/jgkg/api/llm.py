"""Azure AI Foundryのチャットモデルへの薄いクライアント(E-2。裁定B92)。

**Chat Completions APIを選ぶ(Responses APIではない)。理由:**

1. **実測(2026-09-11・このタスク自身)**: `aif-jgkg`の`gpt-5.6-luna`は
   Chat Completions API(`/openai/deployments/{deployment}/chat/completions`)
   に`tools`と`max_completion_tokens`を渡すだけでHTTP 200・
   `finish_reason="tool_calls"`が返る。Microsoft Learnの公式ドキュメント
   (Azure OpenAI reasoning models)は「`gpt-5.6`系はChat Completions APIで
   関数ツールを使うと`reasoning_effort`を`none`にしない限り拒否される
   (Responses APIを使うこと)」と書いているが、**この配備・このAPI版
   (`2024-10-21`)でその拒否は実際には起きなかった**——文書の記述と実測が
   食い違ったので、実測を信じてこの経路を採用する(このプロジェクトが
   繰り返し重視してきた「文書が実態と異なる主張をしうる」という警戒を、
   ここでは逆方向——外部の文書の方を疑う側——に適用した。E-2報告に
   検証の生ログを書く)。
2. **状態を持たない設計(仕様§6.3)と相性が良い**: Chat Completionsは
   1回のPOSTが1回の応答を返すだけの薄いプロトコルで、Responses APIの
   `previous_response_id`によるサーバ側の会話状態や、続けるために前回の
   `reasoning`項目を再送する契約を持たない。このAPIは会話履歴をサーバに
   保存しない(履歴はクライアントが送る)ので、そもそも後者の恩恵が無い。
3. **依存を増やさない**: `httpx`は既存の依存(`pyproject.toml`)。
   `openai` SDKを足すと、この用途(有限回数のツール呼び出しループを
   1つの`/chat`リクエストの中で完結させるだけ)に対して不釣り合いに
   大きい——`azure-identity`(トークン取得)だけを新規依存として足す。

**資格情報を書かない。** 認証は`azure.identity.DefaultAzureCredential`
(本番: マネージドID/開発機: `az login`セッション)がトークンを取る。
APIキーを使う経路はこのモジュールに実装しない(存在しないため使えない。
task-E2-brief.md)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

import httpx

#: Azure AI Foundry(Cognitive Services系エンドポイント)のトークンスコープ。
#: 2026-09-11実測で通ることを確認済み(このタスク自身。probeスクリプトは
#: コミットしない一時ファイル)。
AOAI_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


@dataclass(frozen=True)
class ToolCallRequest:
    """モデルが要求した1件の道具呼び出し(Chat Completionsの`tool_calls[]`を正規化した形)。"""

    id: str
    name: str
    #: モデルが生成した引数(JSON文字列)。パース済みの`dict`ではなく生の
    #: 文字列で持つ——不正なJSON(モデルの出力揺れ)を握りつぶさず、
    #: 呼び出し側(`chat_tools.run_tool`)が例外にできるようにするため。
    arguments_json: str


@dataclass(frozen=True)
class ChatCompletionResult:
    """Chat Completions APIの1回の応答を正規化した形。"""

    #: `finish_reason="stop"`のときの最終回答。ツール呼び出しのときは`None`。
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    #: `usage.total_tokens`(プロンプト+完了。推論トークンも含む)。
    #: 日次トークン予算(裁定B92裁定3(3))はこれを積む。
    total_tokens: int = 0
    #: `usage.completion_tokens_details.reasoning_tokens`(実測用。予算には
    #: 別途積まない——`total_tokens`に既に含まれている)。
    reasoning_tokens: int = 0


class ChatModel(Protocol):
    """道具呼び出しループ(`chat.py`)が依存する唯一のインターフェース。

    `KGClient`(`kgclient.py`)と同じ継ぎ目の作法: 本番は`AzureFoundryChatModel`、
    テストは固定の応答を返すスタブ(`tests/test_api_chat.py`)。
    **LLMを呼ぶテストを書かない**(ブリーフの拘束条件)ので、本物の
    `AzureFoundryChatModel`を経由するテストは存在しない——このProtocolの
    後ろにいるかぎり、テストは常にスタブを束縛する。
    """

    def complete(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        max_completion_tokens: int,
    ) -> ChatCompletionResult: ...


class AzureFoundryChatModel:
    """本番用: Azure AI Foundry(`aif-jgkg`)のChat Completions APIを叩く。

    `client`(httpx)・`get_token`(トークン取得)を注入できるようにしてある
    ——`RemoteKGClient`(kgclient.py)と同じ理由: テストで実ソケット/実認証を
    一切経由せずにこのクラス自身を検証できるようにするため。
    """

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_version: str,
        *,
        client: httpx.Client | None = None,
        get_token: object | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._api_version = api_version
        self._client = client or httpx.Client(timeout=httpx.Timeout(60.0, read=120.0))
        if get_token is None:
            # **ここでだけ`azure-identity`をimportする。** モジュール冒頭で
            # importすると、このモジュールをimportするだけで(呼ばなくても)
            # `azure-identity`が無い環境で失敗する——`create_production_app()`が
            # 遅延importする理由と同じ(必要になるまで依存の存在を要求しない)。
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()

            def _get_token() -> str:
                return credential.get_token(AOAI_TOKEN_SCOPE).token

            get_token = _get_token
        self._get_token = get_token

    def complete(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        max_completion_tokens: int,
    ) -> ChatCompletionResult:
        url = (
            f"{self._endpoint}/openai/deployments/{self._deployment}/chat/completions"
            f"?api-version={self._api_version}"
        )
        body: dict[str, object] = {
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
        }
        if tools:
            body["tools"] = tools
        token = self._get_token()  # type: ignore[operator]
        resp = self._client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
        resp.raise_for_status()
        payload = resp.json()
        choice = payload["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")
        tool_calls = [
            ToolCallRequest(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments_json=tc["function"]["arguments"],
            )
            for tc in (message.get("tool_calls") or [])
        ]
        usage = payload.get("usage") or {}
        reasoning_tokens = (usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens", 0
        )
        return ChatCompletionResult(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            total_tokens=usage.get("total_tokens", 0),
            reasoning_tokens=reasoning_tokens,
        )


def parse_tool_arguments(raw: str) -> dict[str, object]:
    """`ToolCallRequest.arguments_json`を辞書にする。

    **不正なJSONを黙って`{}`にしない。** モデルの出力揺れは道具呼び出し
    そのものの失敗として扱い、その道具呼び出しの結果件数を0件・
    その旨を呼び出し履歴に残す(`chat.py`)——「無かった」と「壊れていた」を
    混同しない。
    """
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError(f"道具の引数がJSONオブジェクトではない: {raw!r}")
    return parsed
