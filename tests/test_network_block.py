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

    **リテラルIP `192.0.2.1`(RFC 5737 TEST-NET-1)を使う。名前解決を経ない。**
    最初は`example.com`(名前解決に成功する実在ドメイン)で書いたが、
    A-2レビューで「オフラインだと`getaddrinfo`自体が失敗して別の例外になる」
    という同じ限界がこのテスト自身にも現れると指摘された。`socket.socket.connect`
    を塞いでいるので、名前解決を経ない宛先(リテラルIP)なら`connect()`に
    直接届き、DNSの成否に依存せずこの遮断だけを検査できる。

    **`192.0.2.1`は文書用に予約され、経路が実在しない**(RFC 5737)ため、
    `example.com`より安全側でもある――遮断が万が一効いていなくても、
    どこにも実際には到達しない(パケットは送出されるが応答する実サーバが無い)。
    """
    with pytest.raises(conftest.NetworkBlockedError):
        httpx.get("http://192.0.2.1/", timeout=2)


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
