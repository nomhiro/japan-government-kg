"""国税庁 法人番号公表サイト 全件データのコネクタ。

全件データはWebフォーム経由で提供されるため、URLは引数で受ける。
実URLは .env の JGKG_HOUJIN_BANGOU_URL に設定する。
"""
import datetime

import httpx

from jgkg.connectors.base import FetchResult, fetch_to_lake

SOURCE_ID = "houjin-bangou"
FILENAME = "zenken.csv"
TIMEOUT = httpx.Timeout(60.0, read=600.0)  # 全件データは大きいので読み取りを長く取る


def fetch(url: str, fetched_on: datetime.date, client: httpx.Client | None = None) -> FetchResult:
    owns_client = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    def _get() -> bytes:
        resp = c.get(url)
        resp.raise_for_status()
        return resp.content

    try:
        return fetch_to_lake(SOURCE_ID, fetched_on, FILENAME, _get)
    finally:
        if owns_client:
            c.close()
