"""Task 11 必須項目7(Task 3 懸念3): e-Gov法令API v2 の `PAGE_LIMIT=100` が

実際に効いているかを1リクエストで確認する。

`egov_law.PAGE_LIMIT` は「APIが明示する上限は未確認」というコメント付きで
100 に置かれている(Task 3 時点の実測は3件・2件までしか行っていなかった)。
APIが limit を黙って切り下げていると、`fetch` のページングは「見かけ上成功
しながら1ページあたりの件数が想定と違う」状態で回る。**確認するのは、最初の
ページで `len(laws) == PAGE_LIMIT`(=切り下げられていない)であること**と、
`total_count` / `next_offset` の実値。

使い捨てにしない(裁定B25)。出力は docs/measurements-phase1.md に全量転記する。

使い方:
    uv run python scripts/probe_egov_paging.py
"""
import json

import httpx

from jgkg.connectors import egov_law


def main() -> None:
    url = egov_law.BASE_URL
    params = {"limit": egov_law.PAGE_LIMIT, "offset": 0}
    print(f"GET {url} params={params}")
    with httpx.Client(timeout=egov_law.TIMEOUT) as c:
        resp = c.get(url, params=params)
    print(f"status={resp.status_code}")
    print(f"content-type={resp.headers.get('content-type')!r}")
    print(f"実際に叩いたURL: {resp.request.url}")
    page = resp.json()
    laws = page["laws"]
    print(f"要求 limit           : {egov_law.PAGE_LIMIT}")
    print(f"返ってきた laws 件数 : {len(laws)}")
    print(f"total_count          : {page['total_count']}")
    print(f"next_offset          : {page['next_offset']}")
    print(f"応答のトップレベルkey : {sorted(page.keys())}")
    print(
        "判定: "
        + (
            f"PAGE_LIMIT={egov_law.PAGE_LIMIT} は効いている(切り下げられていない)"
            if len(laws) == egov_law.PAGE_LIMIT
            else f"**切り下げられている**(要求{egov_law.PAGE_LIMIT} → 実際{len(laws)})"
        )
    )
    expected_pages = -(-page["total_count"] // len(laws)) if laws else None
    print(f"全件取得に必要なページ数(概算): {expected_pages}")
    print("--- 1件目の法令オブジェクトのキー(生値の形の確認) ---")
    if laws:
        print(json.dumps(sorted(laws[0].keys()), ensure_ascii=False))


if __name__ == "__main__":
    main()
