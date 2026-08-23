"""RSシステム(行政事業レビュー見える化サイト)の実データコネクタ。

RSは単一のCSVではない。事業年度ごとに15本の関連CSV(それぞれzip配布)に
分かれており、全てが 予算事業ID(project_id) と 事業年度(fiscal_year) を
共有キーとして持つ(列対応・照合記録は transform/rs_columns.py)。このタスクで
実際にネットワークから取得し列を確認したのは5本(FETCHED_GROUPS)。
残り10本はファイル名テンプレートのみ確認済みで、実データは未取得
(rs_columns.py の RS_UNVERIFIED_GROUPS)。

配布URLの特定経緯(2026-08-23、Task 6 検証0):
    ダウンロードページ https://rssystem.go.jp/download-csv/<year> はSPA(React)
    で、専用の取得APIは無い。ページ本体のJSバンドル(main-Cyt4dzWq.js、
    2026-08-23取得。4,328,048 bytes)を解析し、各ファイルの実体が
    次の固定URLで直接GETできることを特定した(認証・トークン不要、実測):

        https://rssystem.go.jp/files/<year>/rs/<ファイル名を%エンコード>.zip

    ファイル名テンプレートはJSバンドル内の i18n キー
    "ps-csv-file-name-rs-*" の値("1-1_RS_{{year}}_基本情報_組織情報" 等)から
    採取した。**ファイル名テンプレートの一次情報源はこのモジュール
    (RS_GROUP_FILENAMES)に集約する。他のモジュール(rs_columns.py 等)は
    このモジュールのグループキーを参照するだけで、テンプレート文字列を
    複製しない**(Phase 0 C4: レイアウトの知識を1箇所に置く、という教訓)。

既知の罠(2026-08-23 実測。推測ではない):
    存在しない年度・ファイル名を指定すると、CloudFrontは HTTP 404 を返さず
    **HTTP 200 + text/html(SPAのindex.htmlシェル、1939 bytes)を返す**
    (実測URL: https://rssystem.go.jp/files/2025/rs/1-1_RS_2025_<誤エンコード>.zip
    → 200 OK, Content-Type: text/html, Content-Length: 1939, ETag が
    https://rssystem.go.jp/download-csv のindex.htmlと同一)。
    素朴に `raise_for_status()` だけを見て保存すると、間違ったHTMLをzip
    スナップショットとして記録してしまう(サイレントに壊れる)。
    そのため、応答本文の先頭バイトがzipのローカルファイルヘッダ署名
    (``PK\\x03\\x04`` 等、`PK` で始まる)であることを確認してから保存する。
"""
import datetime
import time
import urllib.parse

import httpx

from jgkg.connectors.base import FetchResult, fetch_to_lake

SOURCE_ID = "rs-system"
BASE_URL = "https://rssystem.go.jp/files"

TIMEOUT = httpx.Timeout(30.0, read=180.0)

# ファイル間の礼儀。1本ずつ静的ファイルを取るだけなのでegov-lawのページングより
# 軽量だが、複数ファイルを連続して取得するため間隔を空ける
# (このタスクのネットワーク特例が要求する礼儀。§egov_law.PAGE_INTERVAL_SECONDSと同じ考え方)
FILE_INTERVAL_SECONDS = 0.5

# zipのローカルファイルヘッダ署名(先頭2バイト)。空アーカイブの中央ディレクトリ
# 署名(PK\x05\x06)も"PK"で始まるため、この2バイトのみで十分区別できる
ZIP_MAGIC = b"PK"

# RSの公開CSVファイル名テンプレート({year}未展開、拡張子なし)。
# JSバンドル(main-Cyt4dzWq.js)内の i18n キー "ps-csv-file-name-rs-*" から
# 全15本を採取した(2026-08-23)。キー名はJSバンドルが内部で使っている
# camelCaseの識別子をsnake_caseにしたもの
RS_GROUP_FILENAMES: dict[str, str] = {
    "organization_information": "1-1_RS_{year}_基本情報_組織情報",
    "project_summary": "1-2_RS_{year}_基本情報_事業概要等",
    "policy_measure_laws_and_regulations": "1-3_RS_{year}_基本情報_政策・施策、法令等",
    "subsidy_rate": "1-4_RS_{year}_基本情報_補助率等",
    "related_projects": "1-5_RS_{year}_基本情報_関連事業",
    "budget_summary": "2-1_RS_{year}_予算・執行_サマリ",
    "budget_detail": "2-2_RS_{year}_予算・執行_予算種別・歳出予算項目",
    "purpose_result": "3-1_RS_{year}_効果発現経路_目標・実績",
    "purpose_connection": "3-2_RS_{year}_効果発現経路_目標のつながり",
    "inspection_evaluation": "4-1_RS_{year}_点検・評価",
    "payee_payment_information": "5-1_RS_{year}_支出先_支出情報",
    "payee_payment_block_connection": "5-2_RS_{year}_支出先_支出ブロックのつながり",
    "payee_payment_amount_breakdown": "5-3_RS_{year}_支出先_費目・使途",
    "payee_contract": "5-4_RS_{year}_支出先_国庫債務負担行為等による契約",
    "remark": "6-1_RS_{year}_その他備考",
}

# このタスクで実データを取得し列を確認した5本(rs_columns.RS_FILESに対応)。
# 論理名(project_id, project_name, ministry_name, fiscal_year, budget_amount,
# basis_law_text, recipient_name, recipient_houjin_bangou, expenditure_amount)
# を満たすのに必要な最小集合(検証0〜3の対象)
FETCHED_GROUPS: tuple[str, ...] = (
    "organization_information",
    "project_summary",
    "policy_measure_laws_and_regulations",
    "budget_summary",
    "payee_payment_information",
)


class UnexpectedResponseError(RuntimeError):
    """200 OKだが本文がzipではない(CloudFrontのSPAフォールバック等)。

    上記モジュールdocstringの「既知の罠」を参照。ステータスコードだけを
    見て保存すると、間違ったHTMLをCSVのスナップショットとして記録してしまう。
    """


def filename_for(group: str, year: int) -> str:
    """レイクに保存するローカルファイル名(zip、配布形態のまま)。"""
    return RS_GROUP_FILENAMES[group].format(year=year) + ".zip"


def url_for(group: str, year: int) -> str:
    """実体URL。ファイル名部分はUTF-8で%エンコードする(日本語ファイル名のため)。"""
    encoded = urllib.parse.quote(RS_GROUP_FILENAMES[group].format(year=year))
    return f"{BASE_URL}/{year}/rs/{encoded}.zip"


def fetch_group(
    group: str,
    year: int,
    fetched_on: datetime.date,
    client: httpx.Client | None = None,
) -> FetchResult:
    """1本のグループファイル(zip)を取得してレイクに保存する。

    配布形態(zip)を変えない。取得したバイト列をそのまま保存するので、
    sha256は配布物と一致する(出典として追跡できる)。
    """
    if group not in RS_GROUP_FILENAMES:
        raise KeyError(f"未知のグループ: {group!r}。RS_GROUP_FILENAMES に無い")

    owns_client = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    url = url_for(group, year)

    def _get() -> bytes:
        resp = c.get(url)
        resp.raise_for_status()
        content = resp.content
        if not content.startswith(ZIP_MAGIC):
            raise UnexpectedResponseError(
                f"{group}({year}年度)の応答がzipではない: {url} "
                f"(content-type={resp.headers.get('content-type')!r}, "
                f"先頭32バイト={content[:32]!r})。"
                "指定した年度・ファイル名が配布されていないため、"
                "CloudFrontがSPAのindex.htmlシェルをHTTP 200のまま"
                "返した可能性が高い(モジュールdocstring「既知の罠」参照)"
            )
        return content

    try:
        return fetch_to_lake(SOURCE_ID, fetched_on, filename_for(group, year), _get)
    finally:
        if owns_client:
            c.close()


def fetch_all(
    year: int,
    fetched_on: datetime.date,
    groups: tuple[str, ...] = FETCHED_GROUPS,
    client: httpx.Client | None = None,
) -> dict[str, FetchResult]:
    """複数のグループファイルを1本ずつ、間隔を空けて取得する。"""
    owns_client = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
    results: dict[str, FetchResult] = {}
    try:
        for i, group in enumerate(groups):
            if i > 0:
                time.sleep(FILE_INTERVAL_SECONDS)
            results[group] = fetch_group(group, year, fetched_on, client=c)
        return results
    finally:
        if owns_client:
            c.close()
