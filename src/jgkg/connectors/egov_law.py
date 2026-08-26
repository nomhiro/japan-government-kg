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
                # 動いても再宣言は追わない — 取得開始時点の契約として扱う)。
                #
                # **これは単なる方針ではなく必須である**(2026-08-24 実測):
                # 範囲外の offset を渡すと API は `total_count: 0` を返す
                # (offset=9547 / 9600 のいずれも count=0, total_count=0)。
                # 各ページの total_count を採り直す実装は、最終ページの次で
                # 総数が 0 に化けて完全性チェックを無意味にする
                total_count = page["total_count"]

            # `count` はそのページの件数。API が宣言した件数と実際の配列長が
            # ずれたら黙って進まない(§11.1 の観測性。取得の欠落を
            # 「取れた分だけ保存」で通さないための、ページ単位の同じ検査)
            page_count = page.get("count")
            if page_count is not None and page_count != len(page["laws"]):
                raise IncompleteSnapshotError(
                    f"ページの宣言件数と実際の件数が一致しない(offset={offset}): "
                    f"count={page_count} だが laws は {len(page['laws'])} 件"
                )

            for law in page["laws"]:
                lines.append(json.dumps(law, ensure_ascii=False, sort_keys=True).encode("utf-8"))

            # **`page["next_offset"]` と書いてはならない。** 最終ページでは
            # このキー自体が**応答に存在しない**(null が入るのではなく欠落する)。
            # 2026-08-24、全件実取得(Task 11)で初めて判明した実測:
            #   offset=9400 → keys=['count','laws','next_offset','total_count']
            #   offset=9500 → keys=['count','laws','total_count']      ← 欠落
            # Task 3 のfixtureは最終ページを `next_offset: None` で作っていたため
            # (JSONのnullとして明示的に存在する形)、この差を検出できなかった。
            # 実データで初めて出る、Windows固有の罠と同じ類型(設計書§11.1の再現性)
            next_offset = page.get("next_offset")
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


# =============================================================================
# fetch_law_data: 特定の法令1件の本文を取得する経路(C-1)。
# `/api/2/laws`(上のfetch。全件メタデータ)とは別のエンドポイント。
# 全件ではなく、指定した law_id 1件だけを取る(政府サーバへの実アクセスを
# 必要最小限にする制約による)。テーブル抽出・解釈はここでは行わない
# (パースと取得の失敗を分離する。base.pyの責務分離と同じ理由)
#
# **`SOURCE_ID`(上のfetchが使う"egov-law")とは別の source_id を使う
# (C-2裁定)。** 同じsource_idの下に「全件メタデータ」と「法令1件の本文」
# という意味の異なるスナップショットを混在させると、`lake.latest`が返す
# 「最終取得日」が法令本文取得の日付に化け、`freshness`・`build.sh`の
# 既定出力先がメタデータの無い日付を掴む——C-1で実際にこの懸念が指摘された
# (部分的なものが完全なものを装う。設計書§11.1の観測性と同じ型)。
# =============================================================================

BASE_LAW_DATA_URL = "https://laws.e-gov.go.jp/api/2/law_data"
LAW_DATA_SOURCE_ID = "egov-law-data"


class UnexpectedLawDataResponseError(RuntimeError):
    """200 OKだが、期待した法令本文の応答ではない。

    `fetch`(上)のIncompleteSnapshotError、rs_system.UnexpectedResponseError
    (zipでない応答を弾く)と同型の防御。laws.e-gov.go.jpはSPAであり、
    本来のAPI応答ではないHTML(フォールバックシェル)や、存在しない
    law_idへのエラー応答をJSONとして読めても、`law_full_text`キーが
    無ければテーブル抽出が後段で意味不明な形で壊れる。無検査で
    スナップショットに保存しない。
    """


def law_data_filename(law_id: str) -> str:
    """レイクに保存するローカルファイル名。law_idごとに分ける。

    固定名にすると、同じ source_id + fetched_on で別の law_id を取得した
    とき、`connectors.base._existing`(ファイル名単位の冪等判定)が
    「既にある」と誤認し、2件目を1件目のスナップショットとして
    スキップしてしまう。
    """
    return f"law_data_{law_id}.json"


def fetch_law_data(
    law_id: str,
    fetched_on: datetime.date,
    client: httpx.Client | None = None,
) -> FetchResult:
    """1件の法令本文(law_full_text)を取得してレイクに保存する。

    取得したバイト列をそのまま保存する(sha256が配布物と一致し、出典として
    追跡できる)。保存前に「JSONとして読めるか」「law_full_textキーが
    あるか」だけを確かめる——構造の中身(Tableノードの位置など)は見ない
    (見た瞬間にそれはテーブル抽出の責務になる。ここは取得段)。
    """
    owns_client = client is None
    c = client or httpx.Client(timeout=TIMEOUT)
    url = f"{BASE_LAW_DATA_URL}/{law_id}"

    def _get() -> bytes:
        resp = c.get(url)
        resp.raise_for_status()
        content = resp.content
        try:
            parsed = json.loads(content)
        except ValueError as exc:
            raise UnexpectedLawDataResponseError(
                f"law_id={law_id!r} の応答がJSONとして読めない: {url} "
                f"(content-type={resp.headers.get('content-type')!r}, "
                f"先頭64バイト={content[:64]!r})。"
                "SPAのフォールバックHTMLを取得した可能性がある"
            ) from exc
        if not isinstance(parsed, dict) or "law_full_text" not in parsed:
            keys = sorted(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
            raise UnexpectedLawDataResponseError(
                f"law_id={law_id!r} の応答に law_full_text が無い: {url} "
                f"(応答のキー: {keys})。"
                "存在しない law_id へのエラー応答、またはAPIの仕様変更の可能性がある"
            )
        return content

    try:
        return fetch_to_lake(LAW_DATA_SOURCE_ID, fetched_on, law_data_filename(law_id), _get)
    finally:
        if owns_client:
            c.close()
