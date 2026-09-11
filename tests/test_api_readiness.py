"""起動時のトリプルストア応答待ち(`jgkg.api.readiness`)のテスト。裁定B103追記3。

`jgkg.api.warmup`のテスト(`tests/test_api_warmup.py`)と同じ土台
——`KGClient`の最小限のスパイ実装で、実ネットワークに触れずに
`wait_for_triplestore_ready`自身のロジックを検査する。
"""
from __future__ import annotations

import time

from jgkg.api.readiness import wait_for_triplestore_ready


class _EventuallyRespondsClient:
    """最初の`fail_times`回は例外を投げ、それ以降は成功するスパイ。"""

    def __init__(self, *, fail_times: int):
        self.queries: list[str] = []
        self._fail_times = fail_times

    def query(self, sparql: str):
        self.queries.append(sparql)
        if len(self.queries) <= self._fail_times:
            raise ConnectionRefusedError(
                "トリプルストアがまだ応答しない(テスト用の故意の失敗)"
            )
        return []


class _AlwaysFailsClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, sparql: str):
        self.queries.append(sparql)
        raise ConnectionRefusedError("トリプルストアに接続できない(テスト用の故意の失敗)")


def test_wait_for_triplestore_ready_retries_until_the_client_succeeds():
    """**待ちが効いていること**: 諦めずに再試行し、最終的に成功する。

    何があれば落ちるか: 再試行せずに1回で諦める実装に戻すと、
    `elapsed`が`None`のままになる。
    """
    client = _EventuallyRespondsClient(fail_times=3)
    elapsed = wait_for_triplestore_ready(client, timeout_seconds=5.0, poll_interval_seconds=0.01)
    assert elapsed is not None, "3回失敗した後に成功しているはずなのにNoneが返った"
    assert elapsed >= 0
    assert len(client.queries) == 4, (
        f"3回失敗+1回成功=4回のはずが{len(client.queries)}回になっている: {client.queries}"
    )


def test_wait_for_triplestore_ready_uses_a_light_query_not_a_handwritten_ask():
    """**軽い問い合わせであること。** `ASK {}`ではない(モジュールdocstring
    「`ASK {}`にしなかった理由」参照——`RdflibKGClient.query()`は
    `result.vars`が`None`になるASKクエリを`TypeError`にする)。
    """
    client = _EventuallyRespondsClient(fail_times=0)
    wait_for_triplestore_ready(client, timeout_seconds=5.0, poll_interval_seconds=0.01)
    assert len(client.queries) == 1
    query = client.queries[0]
    assert query.strip().upper().startswith("SELECT"), (
        f"軽い問い合わせがSELECT形式ではない(ASK等に変わった疑い): {query!r}"
    )
    assert "PREFIX" not in query, f"重いクエリ(名前空間を持つ実クエリ)を使っている疑い: {query!r}"


def test_wait_for_triplestore_ready_gives_up_after_the_timeout_and_returns_none():
    """**上限を超えたら諦めること(無限ループにならない)。**

    何があれば落ちるか: 上限を見ずに無限に再試行する実装に戻すと、
    このテスト自身が終わらなくなる——壁時計で「上限をわずかに超えた
    時間で実際に戻ってくる」ことまで確認する(タイムアウトそのものが
    機能していることの直接的な証拠)。
    """
    client = _AlwaysFailsClient()
    started = time.monotonic()
    elapsed = wait_for_triplestore_ready(client, timeout_seconds=0.1, poll_interval_seconds=0.01)
    wall_clock = time.monotonic() - started
    assert elapsed is None, "常に失敗するclientなのにNoneではない値が返った"
    assert wall_clock < 2.0, (
        f"上限(0.1秒)を大幅に超えて戻ってきた——諦めずに待ち続けている疑い: {wall_clock:.3f}秒"
    )
    assert len(client.queries) >= 2, "1回も再試行していない(上限内に複数回試すはず)"


def test_wait_for_triplestore_ready_tries_at_least_once_even_with_a_non_positive_timeout():
    """`timeout_seconds<=0`でも最低1回は試し、無限ループにはならないこと。"""
    client = _AlwaysFailsClient()
    started = time.monotonic()
    elapsed = wait_for_triplestore_ready(client, timeout_seconds=0.0, poll_interval_seconds=0.01)
    wall_clock = time.monotonic() - started
    assert elapsed is None
    assert len(client.queries) >= 1
    assert wall_clock < 2.0
