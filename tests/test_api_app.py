"""FastAPI app(`jgkg.api.app`)のHTTP面のテスト: ルーティング・上限の拒否・404・起動時の温め処理。

ここでは`RdflibKGClient`をfixtureに束縛して使う——`create_app()`がclientを
1回だけ束縛する設計(advisorレビュー: これにより起動時の温め処理も同じ
テスト用clientに対して実行され、本物のFusekiへ接続しようとしない)。

**Windows固有の既知の摩擦(実測)。** `fastapi.testclient.TestClient`は
ASGI越しの同期呼び出しをasyncioのイベントループで裏打ちする。Windowsには
`AF_UNIX`が無いため、CPython標準の`socket.socketpair()`は
loopback(127.0.0.1)TCPソケットで代用する(`Lib/socket.py`の
`_fallback_socketpair`)——asyncioのイベントループ自身の自己pipeがこれを
使い、`tests/conftest.py`の`socket.socket.connect`遮断に引っかかる
(実測)。これは外部ネットワークへの実アクセスではなく同一プロセス内の
asyncio配線であり、Linux(CIの実行環境。ubuntu-latest)では
`socket.socketpair()`が`AF_UNIX`で実装されているためそもそも発生しない
——**Windows上のこの遮断だけを狙って外す**(下の`_allow_loopback_for_asgi_testclient`。
`tests/conftest.py`のdocstring項4「テスト自身がmonkeypatchで上書きすれば
迂回できる」という明示的に許容された経路を使い、127.0.0.1以外への接続は
従来通り遮断したままにする)。
"""
import socket as _socket_module

import conftest
import phase1_fixture as fx
import pytest
from fastapi.testclient import TestClient
from rdflib import Dataset

from jgkg.api.app import create_app
from jgkg.api.kgclient import RdflibKGClient
from jgkg.api.queries import ENTITY_RELATIONSHIPS_MAX_LIMIT, SEARCH_MAX_LIMIT

BASE = "https://jgkg.norr-tech.com"

# **収集時点(conftest.pyの遮断がまだ効いていない時点)で本物のconnectを捕捉する。**
# フィクスチャの中で`socket.socket.connect`を読んでも、その時点では既に
# conftest.pyの`_block_network`(autouse)が`_blocked`へ書き換え済みである
# ため、本物を取れない
_REAL_SOCKET_CONNECT = _socket_module.socket.connect
_REAL_SOCKET_CONNECT_EX = _socket_module.socket.connect_ex
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@pytest.fixture(autouse=True)
def _allow_loopback_for_asgi_testclient(monkeypatch):
    """127.0.0.1/::1宛だけ本物のconnectを通す。他は従来通り`conftest._blocked`。"""

    def _connect(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK_HOSTS:
            return _REAL_SOCKET_CONNECT(sock, address, *args, **kwargs)
        return conftest._blocked(sock, address, *args, **kwargs)

    def _connect_ex(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK_HOSTS:
            return _REAL_SOCKET_CONNECT_EX(sock, address, *args, **kwargs)
        return conftest._blocked(sock, address, *args, **kwargs)

    monkeypatch.setattr(_socket_module.socket, "connect", _connect)
    monkeypatch.setattr(_socket_module.socket, "connect_ex", _connect_ex)
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


class _RecordingClient:
    """`warm_up`が実際に束縛済みclientへ問い合わせることを確認するための薄いスパイ。"""

    def __init__(self, inner):
        self._inner = inner
        self.queries: list[str] = []

    def query(self, sparql: str):
        self.queries.append(sparql)
        return self._inner.query(sparql)


@pytest.fixture
def app_and_spy(kg):
    spy = _RecordingClient(RdflibKGClient(kg))
    app = create_app(spy, base_uri=BASE)
    return app, spy


# =============================================================================
# 起動時のキャッシュ温め(裁定B55対策)がテスト用clientに対して実際に走ること
# =============================================================================


def test_startup_runs_warmup_against_the_bound_client_without_hitting_network(app_and_spy):
    """advisorレビューで指摘された食い違い(設定から新規clientを作ると温め処理
    だけ本物のFusekiに繋ぎに行ってしまう)が無いことの直接的な証拠。

    `TestClient`をコンテキストマネージャとして使う(`with`)と、実際にlifespanの
    startupが走る——単に`create_app()`を呼ぶだけでは走らない。
    """
    app, spy = app_and_spy
    assert spy.queries == [], "with句に入る前から温め処理が走っている(前提が崩れている)"
    with TestClient(app):
        pass
    assert any("budget:Expenditure" in q for q in spy.queries), (
        f"起動時に支出の索引へ触れる温めクエリが実行されていない: {spy.queries}"
    )


# =============================================================================
# ルーティング(検索・エンティティ詳細)
# =============================================================================


def test_get_search_returns_mixed_type_results(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get("/search", params={"q": "厚生労働省"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {hit["type"] for hit in body["results"]}
    assert "Ministry" in types
    assert "Law" in types
    assert body["truncated"] is False


def test_get_entity_detail_for_a_known_project(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get(f"/entity/budget/2025/{fx.PROJECT_CORE}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "BudgetProject"
    assert "Ministry" in body["relationships"]
    assert "Expenditure" in body["relationships"]


def test_get_entity_detail_404_for_unknown_id(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get("/entity/org/0000000000000")
    assert resp.status_code == 404, resp.text


# =============================================================================
# 上限を超えるlimitは黙って丸めず拒否する(422)
# =============================================================================


def test_search_limit_over_max_is_rejected_not_silently_clamped(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get("/search", params={"q": "厚生労働省", "limit": SEARCH_MAX_LIMIT + 1})
    assert resp.status_code == 422, resp.text


def test_entity_detail_limit_over_max_is_rejected_not_silently_clamped(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get(
            f"/entity/budget/2025/{fx.PROJECT_CORE}",
            params={"limit": ENTITY_RELATIONSHIPS_MAX_LIMIT + 1},
        )
    assert resp.status_code == 422, resp.text


# =============================================================================
# SPARQLを外に出さない(仕様§9.1)
# =============================================================================


def test_no_route_accepts_a_raw_sparql_query(app_and_spy):
    """このアプリのルートは`/search`と`/entity/{id}`しか無いこと自体が
    「公開SPARQLを作らない」ことの証拠になる——OpenAPIスキーマのパス一覧で確認する。
    """
    app, _ = app_and_spy
    paths = set(app.openapi()["paths"])
    assert paths == {"/search", "/entity/{entity_id}"}, paths


# =============================================================================
# Windows用ループバック限定の抜け穴(このファイル冒頭)が
# 127.0.0.1以外を今も遮断していることの確認(壊し確認)
# =============================================================================


def test_loopback_exemption_still_blocks_non_loopback_hosts():
    """壊し確認: このファイルが足した抜け穴は127.0.0.1/::1限定であり、
    それ以外の宛先(実在しないTEST-NET-1。RFC 5737)への接続は
    tests/conftest.pyと同じく`NetworkBlockedError`のままであること。
    """
    import socket

    with pytest.raises(conftest.NetworkBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("192.0.2.1", 80))
