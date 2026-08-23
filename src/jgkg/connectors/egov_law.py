"""e-Gov 法令API v2 のコネクタ(全法令メタデータのスナップショット)。

`GET /api/2/laws?limit=N&offset=M` を `next_offset` が尽きるまでページングし、
各法令の生オブジェクト(law_info/revision_info/...)を1行1法令のJSONLとして
そのまま保存する。**分類・解釈はしない**(base.pyの責務分離と同じ理由)。

law_num_type のようなAPI側のラベルは信用できない実例がある(太政官布告が
CabinetOrder に分類されている)。府省の導出やラベルの再分類は Task 4 の仕事で、
ここでは law_num の文字列も含めて生値をそのまま保持する。
"""
import datetime
import json
import time

import httpx

from jgkg.connectors.base import FetchResult, fetch_to_lake

SOURCE_ID = "egov-law"
# 保存形式はJSONL(1行=1法令)。sort_keys=True は決定性のため
# (キー順が不定だと同じデータでもsha256が毎回変わり、差分検出(Task 10)が
# 「毎回変更あり」になる)
FILENAME = "laws.jsonl"

BASE_URL = "https://laws.e-gov.go.jp/api/2/laws"

# 1ページあたりの取得件数。APIが明示する上限は未確認(このタスクで許された
# ネットワークはfixture収録目的の数回のみ — 実測は3件・2件までしか行っていない)。
# 全件実取得(Task 11)で拒否されるようならそちらで調整する
PAGE_LIMIT = 100

# ページ間の待機。公共APIへの礼儀(このタスクのネットワーク特例が要求する)
PAGE_INTERVAL_SECONDS = 0.5

TIMEOUT = httpx.Timeout(30.0)


class IncompleteSnapshotError(RuntimeError):
    """ページングを終えた時点の合計件数が total_count と一致しなかった。

    「next_offset の見落とし」や「途中で打ち切って取れた分だけ保存する」を
    許さないために存在する。黙って欠けたスナップショットは、差分検出
    (Task 10)を「毎回大量に削除された」ように見せて静かに壊す。
    """


def fetch(fetched_on: datetime.date, client: httpx.Client | None = None) -> FetchResult:
    owns_client = client is None
    c = client or httpx.Client(timeout=TIMEOUT)

    def _fetch_all_as_jsonl() -> bytes:
        lines: list[bytes] = []
        total_count: int | None = None
        offset = 0
        is_first_page = True

        while True:
            if not is_first_page:
                # ページ間の礼儀。1ページ目の前には挟まない
                time.sleep(PAGE_INTERVAL_SECONDS)
            is_first_page = False

            resp = c.get(BASE_URL, params={"limit": PAGE_LIMIT, "offset": offset})
            resp.raise_for_status()
            page = resp.json()

            if total_count is None:
                # 最初のページが宣言した総数を正とする(以降のページで
                # 動いても再宣言は追わない — 取得開始時点の契約として扱う)
                total_count = page["total_count"]

            for law in page["laws"]:
                lines.append(json.dumps(law, ensure_ascii=False, sort_keys=True).encode("utf-8"))

            next_offset = page["next_offset"]
            if next_offset is None:
                break
            offset = next_offset

        if len(lines) != total_count:
            raise IncompleteSnapshotError(
                f"法令の総数と一致しない: 取得できたのは {len(lines)} 件、"
                f"total_count は {total_count} 件。"
                "next_offset の見落としか、ページが途中で打ち切られた"
            )

        return b"\n".join(lines) + b"\n" if lines else b""

    try:
        return fetch_to_lake(SOURCE_ID, fetched_on, FILENAME, _fetch_all_as_jsonl)
    finally:
        if owns_client:
            c.close()
