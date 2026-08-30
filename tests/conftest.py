"""テスト全体で、外向きネットワーク接続を既定で禁止する(A-2)。

**なぜ**: A-1の壊し確認で、コネクタをスタブ化し忘れたまま検証を実行し、
e-Gov法令APIへの完全な取得(約96ページ)とrssystem.go.jpへの1リクエストが
実際に発生した(自己開示・是正済み。`task-A1-report.md`参照)。
**規律(気をつける)ではなく構造(できなくする)で防ぐ**のがこのプロジェクトの
作法である――公開物の`_headers`を「欠落したパスがturtleを名乗れない」形にした
(`src/jgkg/site.py`の`build_headers()`)のと同じ考え方を、テスト実行そのものに
適用する。

**遮断のレベル: `socket.socket.connect` / `connect_ex`。**
`httpx`(コネクタが使う)も`urllib.request`(`scripts/verify-site.py`が使う)も、
最終的にはCPython標準の`socket`モジュールのこの2メソッドを通って実際の接続を
確立する。ここを塞ぐことで、個々のHTTPライブラリのAPIに依存せず一括で塞げる。

**迂回できる、既知の経路(塞いでいない)**:

1. **名前解決(`socket.getaddrinfo`)は塞いでいない。** DNSクエリ自体は
   小さな問い合わせであり、政府のサーバへ実際にデータを取りに行くわけではない。
   このプロジェクトで実害を出した経路(e-Gov法令APIの完全取得・
   rssystem.go.jpへの実GET)はいずれも「接続してデータを取る」段であり、
   `connect`を塞げば止まる。DNS解決だけを別途塞ぐ価値は現時点で無いと判断した。
   **実測で分かった副作用(2026-08-25)**: 名前解決そのものが失敗する宛先
   (例: RFC 2606の`example.invalid`)へ`httpx`で接続しようとすると、
   `connect()`に届く前に`getaddrinfo`が失敗し、`httpx.ConnectError`
   (`NetworkBlockedError`ではない)になる。つまり**「`NetworkBlockedError`が
   出ない」ことは「遮断が効いていない」ことの証明にはならない**――名前解決に
   失敗する宛先は、そもそも遮断を試す前に別の理由で失敗する。この遮断が
   実際に効いていることを確かめたいテストは、名前解決を経ない宛先
   (`tests/test_network_block.py`はRFC 5737のリテラルIP`192.0.2.1`を使う。
   当初は名前解決に成功する`example.com`を使ったが、オフライン環境では
   `example.com`自体も`getaddrinfo`で失敗して同じ問題が起きると指摘され、
   名前解決を要しないリテラルIPに変更した)を使うこと。
2. **UDP等、`connect()`を経由しない送信(`socket.sendto`によるconnectionless送信)
   は対象外。** 現在のコネクタ・スクリプトはいずれもTCP(HTTP/HTTPS)のみを使う。
3. **`subprocess`で外部コマンド(`curl`・`git fetch`等)を呼ぶテストは対象外**
   (Pythonの`socket`層を経由しないため)。2026-08-25時点で`tests/`配下に
   `subprocess`呼び出しは無い(grep確認済み。`test-a2-report.md`参照)。
4. **テスト自身が`monkeypatch`フィクスチャで`socket.socket.connect`を
   さらに上書きすれば、当然その回だけ迂回できる。** これは意図的な迂回経路の
   提供ではなく、Pythonのmonkeypatchの一般的な性質であり、既存テストで
   そのような上書きをしているものは無い(2026-08-25時点)。

**このフィクスチャ専用の`MonkeyPatch`を使う理由。** `monkeypatch`フィクスチャは
テスト関数と共有される1個のインスタンスであり、テスト側のコードが
(直接・間接に)`monkeypatch.undo()`を呼べば、共有インスタンスに乗っている
変更は全て――この遮断も含めて――一括で解除されてしまう。この遮断だけは
テスト側のどんな`monkeypatch`操作からも独立して生き続けるべきなので、
`pytest.MonkeyPatch.context()`で専用インスタンスを持つ。
"""
import socket
import sys
from collections.abc import Iterator
from typing import Never

import pytest


class NetworkBlockedError(RuntimeError):
    """テストから外向きネットワーク接続が試みられたときに投げる。

    多くの場合はコネクタをスタブ化し忘れている――A-1で実際に起きた事故と
    同じ形(`task-A1-report.md`参照)。意図的に実ネットワークへ接続する
    テストであれば `@pytest.mark.network` を付けること
    (仕様§10「外部APIへの実アクセスはテストに含めない」により、
    2026-08-25時点でこのマーカーを使うテストは存在しないはず)。
    """


def _blocked(*args: object, **kwargs: object) -> Never:
    raise NetworkBlockedError(
        "テストから外向きネットワークへの接続が試みられた"
        f"(socket.socket.connect{args!r}{kwargs!r})。"
        "仕様§10により、外部APIへの実アクセスはテストに含めない。"
        "多くの場合はコネクタ(httpx.Client等)をスタブ化し忘れている。"
        "実ネットワークへの接続を意図するテストなら @pytest.mark.network を付けること。"
    )


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """既定で外向き接続を`NetworkBlockedError`にする(オプトインは`@pytest.mark.network`)。"""
    if request.node.get_closest_marker("network") is not None:
        yield
        return

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket.socket, "connect", _blocked)
        mp.setattr(socket.socket, "connect_ex", _blocked)
        yield


# =============================================================================
# ASGIのTestClient用のループバック限定の抜け穴(Windows限定)
# =============================================================================

# **収集時点(上の`_block_network`がまだ効いていない時点)で本物のconnectを
# 捕捉する。** フィクスチャの中で`socket.socket.connect`を読んでも、その時点
# では既に`_blocked`へ書き換え済みなので本物が取れない。
_REAL_SOCKET_CONNECT = socket.socket.connect
_REAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@pytest.fixture
def allow_loopback_for_asgi_testclient(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """127.0.0.1/::1宛だけ本物のconnectを通す。他は従来通り`_blocked`。

    **`fastapi.testclient.TestClient`を使うテストが必要とする。**
    Starletteのportalがループバックのsocketpairを作るため。

    **autouseにしない。** autouseにすると全テストで遮断が緩む ——
    必要なファイルが明示的に要求する形にする(`test_api_app.py`と
    `test_api_graph.py`が各自のautouseフィクスチャからこれを要求している)。

    **定義をここに1本化した理由(D-4)**: 以前は`test_api_app.py`だけが持って
    いたが、D-4で`test_api_graph.py`も`TestClient`を使うようになった。
    **セキュリティに関わる緩和を2箇所に複製すると、片方だけが直される**
    (このプロジェクトの再発欠陥3: 部分適用)。

    **Windows限定。** Linux(`socket.socketpair()`がAF_UNIXで実装されており
    この摩擦がそもそも起きない)では何もパッチしない——CIの遮断挙動は
    このフィクスチャが無かった場合と完全に同じ。
    """
    if sys.platform != "win32":
        yield
        return

    def _connect(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK_HOSTS:
            return _REAL_SOCKET_CONNECT(sock, address, *args, **kwargs)
        return _blocked(sock, address, *args, **kwargs)

    def _connect_ex(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK_HOSTS:
            return _REAL_SOCKET_CONNECT_EX(sock, address, *args, **kwargs)
        return _blocked(sock, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex)
    yield
