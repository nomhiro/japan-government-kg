"""チャット(`jgkg.api.chat`/`jgkg.api.chat_tools`)のテスト(E-2。裁定B92)。

**LLMを呼ぶテストを書かない**(task-E2-brief.mdの拘束条件)。`ChatModel`
Protocol(`llm.py`)を実装する`ScriptedChatModel`(このファイル)で応答を
スクリプト化し、こちらのコード(道具の実行・上限・出典の組み立て)の
判定だけを検査する。`tests/phase1_fixture.py`のfixtureに対して
`RdflibKGClient`経由で実行する——実ネットワーク無し(`test_api_search.py`
と同じ土台)。
"""
from __future__ import annotations

import json
from pathlib import Path

import phase1_fixture as fx
import pytest
from fastapi.testclient import TestClient
from rdflib import Dataset

from jgkg.api.app import create_app
from jgkg.api.chat import (
    ChatService,
    DailyTokenBudget,
    DailyTokenBudgetExceeded,
    RateLimiter,
    RateLimitExceeded,
)
from jgkg.api.chat_tools import SourceCollector, build_tool_schemas, run_tool
from jgkg.api.kgclient import RdflibKGClient
from jgkg.api.llm import ChatCompletionResult, ToolCallRequest
from jgkg.api.models import ChatRequest
from jgkg.site import module_names

BASE = "https://jgkg.norr-tech.com"
GENERATED_DIR = Path("schema/generated")


@pytest.fixture(autouse=True)
def _allow_loopback(allow_loopback_for_asgi_testclient):
    """`TestClient`のためのループバック限定の抜け穴(`test_api_app.py`と同じ定義を
    再利用する。Windows固有の`socket.socketpair()`フォールバック事情——
    そちらのファイル冒頭のdocstring参照)。
    """
    yield


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", BASE)
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def kg(tmp_path) -> Dataset:
    return fx.build_dataset(tmp_path / "out")


@pytest.fixture
def client(kg) -> RdflibKGClient:
    return RdflibKGClient(kg)


class ScriptedChatModel:
    """`ChatModel`のテスト用実装。あらかじめ用意した応答を順に返すだけ。"""

    def __init__(self, script: list[ChatCompletionResult]) -> None:
        self._script = list(script)
        self.calls: list[tuple[list[dict], list[dict], int]] = []

    def complete(self, messages, tools, max_completion_tokens):
        self.calls.append((messages, tools, max_completion_tokens))
        if not self._script:
            raise AssertionError("スクリプトが尽きた(想定より多くLLMを呼び出した)")
        return self._script.pop(0)


def _tool_call(tool_id: str, name: str, **arguments: object) -> ToolCallRequest:
    return ToolCallRequest(id=tool_id, name=name, arguments_json=json.dumps(arguments, ensure_ascii=False))


def _final(content: str, total_tokens: int = 100) -> ChatCompletionResult:
    return ChatCompletionResult(content=content, tool_calls=[], finish_reason="stop", total_tokens=total_tokens)


def _service(
    client: RdflibKGClient,
    model: ScriptedChatModel,
    *,
    tool_call_limit: int = 6,
    daily_budget: int = 1_000_000,
    rate_limit_per_minute: int = 1000,
) -> ChatService:
    return ChatService(
        kg_client=client,
        base_uri=BASE,
        generated_dir=GENERATED_DIR,
        chat_model=model,
        tool_call_limit=tool_call_limit,
        max_completion_tokens=4000,
        rate_limiter=RateLimiter(rate_limit_per_minute),
        daily_budget=DailyTokenBudget(daily_budget),
    )


# =============================================================================
# 実データに対する道具1本ずつの単体テスト(件数をアサートする。空虚にしない)
# =============================================================================


def test_run_tool_search_entities_returns_exact_hit_count_for_known_query(client):
    collector = SourceCollector()
    result = run_tool(
        "search_entities",
        {"q": "厚生労働省", "limit": 20},
        kg_client=client,
        base_uri=BASE,
        generated_dir=GENERATED_DIR,
        collector=collector,
    )
    body = json.loads(result.content)
    # test_api_search.py/test_api_app.pyの前提と同じ(Ministry+Lawが混在)。
    # 「1件以上」ではなく実際の型集合を検査する
    types = {hit["type"] for hit in body["results"]}
    assert types == {"Ministry", "Law"}, body["results"]
    assert result.result_count == len(body["results"])
    sources, _ = collector.finalize()
    assert len(sources) == result.result_count
    # 検索はグラフ(出典)を返さない(queries.pyのSearchHit参照)——捏造しない
    assert all(s["graphs"] == [] for s in sources)


def test_run_tool_get_entity_normalizes_percent_encoded_id_path_from_search(client):
    """`%`を含むid_path(検索が返す形)を直接関数呼び出しで渡しても解決できること
    (chat_tools.pyの`unquote`正規化。裁定B59/B69と同じ族の壊し確認)。

    `unquote`を忘れると、既にパーセントエンコード済みの`id_path`が
    `canonical_iri`/`sparql_iri`でもう一度エンコードされ、実在するエンティティが
    0件になる——このテストはその退化を検出する。
    """
    collector = SourceCollector()
    search_result = run_tool(
        "search_entities",
        {"q": fx.OLD_KOUSEISHO_NAME, "limit": 20},
        kg_client=client,
        base_uri=BASE,
        generated_dir=GENERATED_DIR,
        collector=collector,
    )
    hits = json.loads(search_result.content)["results"]
    abolished = [h for h in hits if h["type"] == "AbolishedGovernmentOrgan"]
    assert len(abolished) == 1, f"前提(厚生省が1件ヒットする)が崩れている: {hits}"
    id_path = abolished[0]["id_path"]
    assert "%" in id_path, f"前提(id_pathがpercent-encodeを必要とする)が崩れている: {abolished}"

    detail_result = run_tool(
        "get_entity",
        {"id_path": id_path},
        kg_client=client,
        base_uri=BASE,
        generated_dir=GENERATED_DIR,
        collector=collector,
    )
    assert detail_result.result_count == 1, detail_result.content
    body = json.loads(detail_result.content)
    assert body["label"] == fx.OLD_KOUSEISHO_NAME
    assert body["id"] == abolished[0]["id"]


def test_run_tool_get_ontology_returns_requested_module_content(client):
    result = run_tool(
        "get_ontology",
        {"module": "core"},
        kg_client=client,
        base_uri=BASE,
        generated_dir=GENERATED_DIR,
        collector=SourceCollector(),
    )
    assert result.result_count == 1
    on_disk = (GENERATED_DIR / "core.owl.ttl").read_text(encoding="utf-8")
    assert result.content == on_disk


def test_run_tool_get_ontology_rejects_unknown_module_without_raising(client):
    result = run_tool(
        "get_ontology",
        {"module": "not-a-real-module"},
        kg_client=client,
        base_uri=BASE,
        generated_dir=GENERATED_DIR,
        collector=SourceCollector(),
    )
    assert result.result_count == 0
    assert "error" in json.loads(result.content)


def test_run_tool_zero_hits_leaves_sources_empty_no_fabrication(client):
    """裁定B92裁定2: 道具が0件を返したら出典は0件のまま(捏造しない)。"""
    collector = SourceCollector()
    result = run_tool(
        "search_entities",
        {"q": "実在しないはずの検索語_xyz123", "limit": 20},
        kg_client=client,
        base_uri=BASE,
        generated_dir=GENERATED_DIR,
        collector=collector,
    )
    assert result.result_count == 0
    sources, graphs = collector.finalize()
    assert sources == []
    assert graphs == {}


# =============================================================================
# `get_ontology`のモジュール名は`site.module_names()`から導出する(手書きへの退化を防ぐ)
# =============================================================================


def test_get_ontology_module_enum_is_derived_from_site_module_names():
    schemas = build_tool_schemas(GENERATED_DIR)
    ontology_schema = next(s for s in schemas if s["function"]["name"] == "get_ontology")
    enum = ontology_schema["function"]["parameters"]["properties"]["module"]["enum"]
    assert enum == module_names(GENERATED_DIR)
    assert len(enum) >= 4, "手書きの短い一覧に後退していないか(実際のモジュール数の下限)"


# =============================================================================
# ChatService: 出典の組み立て・道具呼び出し履歴・上限
# =============================================================================


def test_handle_chat_happy_path_search_then_answer_has_matching_sources(client):
    model = ScriptedChatModel(
        [
            ChatCompletionResult(
                content=None,
                tool_calls=[_tool_call("c1", "search_entities", q="厚生労働省", limit=20)],
                finish_reason="tool_calls",
                total_tokens=200,
            ),
            _final("厚生労働省が見つかりました。"),
        ]
    )
    service = _service(client, model)
    resp = service.handle_chat(ChatRequest(message="厚生労働省について教えて"), "1.2.3.4")

    assert resp.answer == "厚生労働省が見つかりました。"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].tool == "search_entities"
    assert resp.tool_calls[0].result_count == 2  # Ministry + Law の2件(上のテストで固定した数)
    assert resp.tool_call_limit_reached is False
    assert resp.truncated is False
    assert len(resp.sources) == 2
    assert {s.type for s in resp.sources} == {"Ministry", "Law"}


def test_handle_chat_zero_tool_hits_yields_zero_sources_not_fabricated(client):
    model = ScriptedChatModel(
        [
            ChatCompletionResult(
                content=None,
                tool_calls=[_tool_call("c1", "search_entities", q="存在しない語_abc999")],
                finish_reason="tool_calls",
                total_tokens=50,
            ),
            _final("見つかりませんでした。"),
        ]
    )
    service = _service(client, model)
    resp = service.handle_chat(ChatRequest(message="存在しない語_abc999について教えて"), "1.2.3.4")
    assert resp.tool_calls[0].result_count == 0
    assert resp.sources == []
    assert resp.graphs == {}


def test_handle_chat_tool_call_limit_is_enforced_and_reported(client):
    """裁定B92裁定3(1): 上限に達したら`tool_call_limit_reached`を必ず立てる。

    **壊し確認の対象**: `chat.py`の`limit_reached`設定を消すとこのテストが
    落ちる(応答が「打ち切った」と言わない=黙って打ち切る状態の再現)。
    """
    limit = 2
    script = [
        ChatCompletionResult(
            content=None,
            tool_calls=[_tool_call(f"c{i}", "get_ontology", module="core")],
            finish_reason="tool_calls",
            total_tokens=10,
        )
        for i in range(1, limit + 1)
    ]
    script.append(_final("上限に達したので、ここまでの結果で回答します。"))
    model = ScriptedChatModel(script)
    service = _service(client, model, tool_call_limit=limit)

    resp = service.handle_chat(ChatRequest(message="オントロジーを全部読んで"), "1.2.3.4")

    assert len(resp.tool_calls) == limit, "実行された道具呼び出しの件数が上限と一致しない"
    assert resp.tool_call_limit == limit
    assert resp.tool_call_limit_reached is True
    # 最後のLLM呼び出しでは道具を提示していない(offer_tools=Falseで上限を強制した)
    last_tools_offered = model.calls[-1][1]
    assert last_tools_offered == []


def test_handle_chat_marks_truncated_when_model_hits_output_token_cap(client):
    model = ScriptedChatModel(
        [
            ChatCompletionResult(content=None, tool_calls=[], finish_reason="length", total_tokens=4000),
        ]
    )
    service = _service(client, model)
    resp = service.handle_chat(ChatRequest(message="長い質問"), "1.2.3.4")
    assert resp.truncated is True


# =============================================================================
# 費用の上限(裁定B92裁定3): レート制限・日次トークン予算
# =============================================================================


def test_rate_limiter_blocks_after_limit_within_the_same_minute():
    now = [1_000_000.0]
    limiter = RateLimiter(3, clock=lambda: now[0])
    for _ in range(3):
        limiter.check("9.9.9.9")
    with pytest.raises(RateLimitExceeded):
        limiter.check("9.9.9.9")
    # 別IPは影響を受けない
    limiter.check("8.8.8.8")


def test_rate_limiter_resets_in_a_new_minute_window():
    now = [1_000_000.0]
    limiter = RateLimiter(1, clock=lambda: now[0])
    limiter.check("9.9.9.9")
    with pytest.raises(RateLimitExceeded):
        limiter.check("9.9.9.9")
    now[0] += 61  # 次の分の窓へ
    limiter.check("9.9.9.9")  # 再び許可される


def test_daily_token_budget_blocks_once_exceeded_and_resets_next_day():
    now = [1_700_000_000.0]
    budget = DailyTokenBudget(1000, clock=lambda: now[0])
    budget.ensure_available()  # まだ0件
    budget.record(1500)  # 1回で予算を超える(切って良い量まで待たない)
    with pytest.raises(DailyTokenBudgetExceeded):
        budget.ensure_available()
    now[0] += 86_400  # 次の日(UTC)
    budget.ensure_available()  # リセットされている


def test_handle_chat_raises_daily_budget_exceeded_before_calling_the_model_again(client):
    """壊し確認の対象: 1日のトークン上限を超えたのに200を返す(=このメソッドが
    例外を投げない)状態を作ると、下のHTTPレベルのテストが429ではなく200を見て落ちる。
    ここではChatService単体でその前提(例外が飛ぶこと)を確認する。
    """
    model = ScriptedChatModel([_final("最初の1回は通る", total_tokens=2000)])
    service = _service(client, model, daily_budget=1000)

    first = service.handle_chat(ChatRequest(message="1回目"), "1.2.3.4")
    assert first.answer == "最初の1回は通る"

    with pytest.raises(DailyTokenBudgetExceeded):
        service.handle_chat(ChatRequest(message="2回目"), "1.2.3.4")


# =============================================================================
# HTTPルート経由(app.py): 429・503・応答の形
# =============================================================================


def test_post_chat_returns_503_when_chat_model_is_not_configured(client):
    app = create_app(client, base_uri=BASE)  # chat_model省略
    with TestClient(app) as tc:
        resp = tc.post("/chat", json={"message": "こんにちは"})
    assert resp.status_code == 503, resp.text


def test_post_chat_end_to_end_returns_structured_sources_and_tool_history(client, monkeypatch):
    model = ScriptedChatModel(
        [
            ChatCompletionResult(
                content=None,
                tool_calls=[_tool_call("c1", "search_entities", q="厚生労働省", limit=20)],
                finish_reason="tool_calls",
                total_tokens=200,
            ),
            _final("厚生労働省が見つかりました。"),
        ]
    )
    app = create_app(client, base_uri=BASE, chat_model=model, generated_dir=GENERATED_DIR)
    with TestClient(app) as tc:
        resp = tc.post("/chat", json={"message": "厚生労働省について教えて"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "厚生労働省が見つかりました。"
    assert len(body["sources"]) == 2
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["tool"] == "search_entities"
    assert body["tool_call_limit_reached"] is False


def test_post_chat_returns_429_once_daily_token_budget_is_exceeded(client, monkeypatch):
    monkeypatch.setenv("JGKG_CHAT_DAILY_TOKEN_BUDGET", "1000")
    from jgkg.config import get_settings

    get_settings.cache_clear()
    model = ScriptedChatModel(
        [
            _final("1回目は通る", total_tokens=2000),
            _final("ここには来ない"),
        ]
    )
    app = create_app(client, base_uri=BASE, chat_model=model, generated_dir=GENERATED_DIR)
    with TestClient(app) as tc:
        first = tc.post("/chat", json={"message": "1回目"})
        assert first.status_code == 200, first.text
        second = tc.post("/chat", json={"message": "2回目"})
    assert second.status_code == 429, second.text
    get_settings.cache_clear()


def test_post_chat_returns_429_once_per_minute_rate_limit_is_exceeded(client, monkeypatch):
    monkeypatch.setenv("JGKG_CHAT_RATE_LIMIT_PER_MINUTE", "1")
    from jgkg.config import get_settings

    get_settings.cache_clear()
    model = ScriptedChatModel([_final("1回目"), _final("ここには来ない")])
    app = create_app(client, base_uri=BASE, chat_model=model, generated_dir=GENERATED_DIR)
    with TestClient(app) as tc:
        first = tc.post("/chat", json={"message": "1回目"})
        assert first.status_code == 200, first.text
        second = tc.post("/chat", json={"message": "2回目"})
    assert second.status_code == 429, second.text
    get_settings.cache_clear()


def test_post_chat_history_is_forwarded_to_the_model_and_not_stored_server_side(client):
    """仕様§6.3: 履歴はクライアントが送る。サーバはこの呼び出しの外で保持しない
    (`ChatService`はプロセス内に会話状態を持たない——引数として渡された
    `request.history`だけをこの1回のモデル呼び出しに使う)。
    """
    model = ScriptedChatModel([_final("了解しました。")])
    service = _service(client, model)
    req = ChatRequest(
        message="それはどの法令?",
        history=[{"role": "user", "content": "厚生労働省について教えて"}, {"role": "assistant", "content": "..."}],
    )
    service.handle_chat(req, "1.2.3.4")
    sent_messages = model.calls[0][0]
    roles_and_content = [(m["role"], m["content"]) for m in sent_messages]
    assert ("user", "厚生労働省について教えて") in roles_and_content
    assert ("assistant", "...") in roles_and_content
