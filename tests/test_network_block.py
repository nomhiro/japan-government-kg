"""`tests/conftest.py` の既定ネットワーク遮断(A-2)を検査する。

**このファイルでは遮断を無効化しない。** 遮断の壊し確認(無効化すると
どうなるかの実測)は`task-A2-report.md`に記録がある――無効化する先が
「実際に政府のサーバへ到達しうる呼び出し」を含むため、壊し確認自体を
このテストスイートの一部として毎回実行するのは危険側に振れる
(壊し確認は1度実施して記録に残すもので、恒常的なテストにはしない)。
ここに置く2つのテストは、**遮断が常に有効な状態**でのみ意味を持つ
(有効なら合格するのが正しい)。
"""
import datetime

import conftest
import httpx
import pytest

from jgkg.connectors import rs_system

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    """`rs_system.fetch_group`は実接続を試みる前に`lake.list_snapshots`を読む。

    実リポジトリの`data/lake/`を読ませない(他テストの`tmp_lake`と同じ形)。
    """
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_network_is_blocked_by_default():
    """`httpx`経由の外向き接続は既定で`NetworkBlockedError`になる。

    **`example.invalid`ではなく`example.com`を使う(実測で判明した理由)。**
    最初は名前解決自体が失敗する`example.invalid`(RFC 2606予約)で書いたが、
    実行すると`socket.socket.connect`まで届く前に`getaddrinfo`が失敗し、
    `httpx.ConnectError`(`NetworkBlockedError`ではない)になった――この遮断は
    `connect`/`connect_ex`だけを塞ぐ設計であり、名前解決止まりの失敗は
    そもそも遮断を試す前に終わる(conftest.pyの「迂回できる経路」参照)。
    `example.com`はIANAが実運用する実在ドメインなので名前解決は成功し、
    `connect()`まで届いてから塞がれる――遮断そのものを検査できる。
    (接続先が実在しても、`connect()`自体を塞ぐのでTCPパケットは一切出ない。)
    """
    with pytest.raises(conftest.NetworkBlockedError):
        httpx.get("http://example.com/", timeout=2)


def test_a1s_actual_incident_path_is_stopped_before_reaching_the_government_server():
    """A-1の壊し確認手順ミスで実際に起きた事故と全く同じ呼び出しを、スタブ化せずに行う。

    2026-08-24、`fetch.py`の`--year`検査を(壊し確認のため)`if False:`に
    変えたまま関連テストを実行し、`year=None`が`rs_system`のコネクタまで
    素通りして `https://rssystem.go.jp/files/None/rs/1-1_RS_None_基本情報_組織情報.zip`
    への実GETが発生した(`url_for`はf文字列で埋めるだけで型検査が無いため、
    `None`はそのまま文字列化されて素通りする)。`task-A1-report.md`に自己開示・
    是正の記録がある。

    このテストは同じ引数(`year=None`)・同じコネクタ関数を、今度は
    スタブ化せずにそのまま呼ぶ。`tests/conftest.py`の遮断が無ければ実際に
    政府のサーバへ到達する呼び出しなので、**このテストでは遮断を外さない**
    (無効化しての実行は`task-A2-report.md`に記録した1回限りの壊し確認のみ)。
    """
    with pytest.raises(conftest.NetworkBlockedError):
        rs_system.fetch_group("organization_information", None, DAY)
