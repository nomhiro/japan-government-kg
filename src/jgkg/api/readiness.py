"""起動時、トリプルストアが問い合わせに応答するまで待つ(上限付き)。

**なぜ要るか(裁定B103追記3。`docs/decision-log.md`「配備条件で測ったら、
`/overview`が永久に503になる設計欠陥が出た」参照。team-lead実測)。**
`deploy/aca.json`のContainer Appは`serve-fuseki`/`serve-api`をsidecarとして
同じレプリカに並べるが、**ACAには同一レプリカ内のコンテナの起動順序を
指定する仕組みが無い**(`containers`は列挙であって順序ではない)。
Fusekiが接続を受ける前にAPIの`lifespan`が`warm_up`/`build_overview`を
走らせると、両方とも接続エラー(実測ログ: `httpx.ConnectError: [Errno 111]
Connection refused`)で失敗し、**再試行が無いので`/overview`はAPIを
再起動するまで永久に503**になる——検索・エンティティ表示は毎リクエストで
問い合わせるので生き続けるため、**トップページの第1層だけが静かに死ぬ**
(裁定B84の族: 「まだ準備できていない」と「集約が失敗した」を混ぜない
ため、ここでは例外を投げず、後続の`warm_up`/`build_overview`が今まで
どおり自分の`try`/`except`で503に落とす形に任せる——このモジュールは
「待つ」だけをする)。

**ローカルの`docker-compose.serve.yml`が`depends_on: serve-fuseki:
condition: service_healthy`でこの順序をAPI起動前に強制しており、
ローカルのテストはこの欠陥を検出できなかった**——裁定B102(リポジトリに
あるファイルがイメージに無い)と同型の「ローカルに配備先に無い性質がある」
再発欠陥(B102裁定が言う再発欠陥26の3例目)。

**軽い問い合わせで待つ。重いクエリで待たない。**
`warm_up`・`build_overview`と同じ`KGClient.query()`を1本呼ぶだけにする。

**`ASK {}`にしなかった理由(team-leadの提案からの変更。実際に検証した)。**
`RdflibKGClient.query()`(`kgclient.py`)は`result.vars`を
`[str(v) for v in result.vars]`で読むが、ASKクエリの`result.vars`は
`None`であり**これは`TypeError`になる**(rdflibで実際に確認済み:
`Dataset().query("ASK {}").vars is None`)。`RemoteKGClient.query()`も
JSON応答の`head["vars"]`を読むため、SPARQL 1.1 Query Results JSON Format
のASK応答(`{"head": {}, "boolean": true}`。`vars`キーが無い)で同様に
`KeyError`になるはずである。**`KGClient.query()`の契約(SELECT形式の行を
返す)を変えずに済む`SELECT * WHERE {} LIMIT 1`(0列。rdflibでは0行になる
ことも実測確認済み)に変えた**——どちらのバックエンドの`query()`実装も
崩さない最小の形。
"""
from __future__ import annotations

import logging
import time

from jgkg.api.kgclient import KGClient

logger = logging.getLogger(__name__)

#: 軽い問い合わせ。モジュールdocstring「`ASK {}`にしなかった理由」参照。
_READINESS_PROBE_QUERY = "SELECT * WHERE {} LIMIT 1"


def wait_for_triplestore_ready(
    client: KGClient,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.5,
) -> float | None:
    """`client.query()`が例外を投げずに応答するまで、軽い問い合わせで待つ。

    成功時は所要秒数を返す。**`timeout_seconds`に達したら諦めて`None`を
    返す**——例外を外に投げない(呼び出し側の`lifespan`を落とさない。
    `warm_up`と同じ作法)。`timeout_seconds`が0以下でも最低1回は試す
    (無限ループにはならないことを`tests/test_api_readiness.py`が縛る)。
    """
    started = time.monotonic()
    deadline = started + max(timeout_seconds, 0.0)
    attempts = 0
    while True:
        attempts += 1
        try:
            client.query(_READINESS_PROBE_QUERY)
        except Exception:
            now = time.monotonic()
            if now >= deadline:
                # **`exc_info=True`にする(`warmup.py`の`logger.warning`と
                # 同じ作法)。** これがあると`except Exception`(この関数が
                # 意図的に拾う唯一の例外集合)の全情報がログに残る——
                # 諦めた理由を人間が事後に追跡できる
                logger.warning(
                    "トリプルストアの応答待ちが上限(%.1f秒・%d回試行)に達した。"
                    "諦めて起動を続ける(裁定B103追記3。warm_up/build_overviewは"
                    "今までどおり失敗して503に落ちる)。",
                    timeout_seconds,
                    attempts,
                    exc_info=True,
                )
                return None
            time.sleep(min(poll_interval_seconds, max(deadline - now, 0.0)))
            continue
        elapsed = time.monotonic() - started
        logger.info(
            "トリプルストアの応答を確認した(%.3f秒・%d回試行。裁定B103追記3)。",
            elapsed,
            attempts,
        )
        return elapsed
