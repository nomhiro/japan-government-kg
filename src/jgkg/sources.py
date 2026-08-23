"""ソースレジストリ。ライセンスと更新頻度を機械可読で持つ(設計書§11.2)。

ライセンスが未記録のソースを登録してはならない。アプリはこのメタデータを
使って出典と規約を自動表示する。
"""
import datetime
import hashlib
from dataclasses import dataclass

GOV_STANDARD_TERMS = "政府標準利用規約(第2.0版)"
GOV_STANDARD_TERMS_URL = "https://www.digital.go.jp/resources/terms_of_use"


def content_digest(data: bytes) -> str:
    """参照表の内容ハッシュ。改行をLFに正規化してから取る。

    Gitの `core.autocrlf` で作業ツリーの改行が変わっても同じ値になるようにする。
    スナップショット(`lake.save`)は取得したバイト列そのものが同一性なので、
    そちらは正規化しない。
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    license: str
    license_url: str
    frequency: str  # daily / monthly / annual / ondemand
    access: str     # api / bulk / scrape
    encoding: str = "utf-8"
    note: str = ""
    # --- リポジトリにコミットして管理する参照表だけが持つ事実 ---
    # これらのソースには「取得日」が存在しない(レイクにスナップショットが無く、
    # 上流から取得した日付も記録されていない)。**分からない日付を書く代わりに、
    # 分かっている事実だけを書く。**
    local_path: str | None = None
    # このリポジトリに記録した日(git log で確認できる事実)
    recorded_on: datetime.date | None = None
    # 記録した内容の content_digest。実ファイルとの一致をテストが照合する
    sha256: str | None = None


SOURCES: dict[str, Source] = {
    "houjin-bangou": Source(
        id="houjin-bangou",
        name="国税庁 法人番号公表サイト 全件データ",
        url="https://www.houjin-bangou.nta.go.jp/download/zenken/",
        license=GOV_STANDARD_TERMS,
        license_url=GOV_STANDARD_TERMS_URL,
        frequency="monthly",
        access="bulk",
        encoding="utf-8",
        note="全件データは月次(前月末時点)。差分は日次。商用・再配布可。"
             "Shift_JIS版とUnicode版の両方が配布されているため、Unicode(UTF-8)版を取得すること",
    ),
    "egov-law": Source(
        id="egov-law",
        name="e-Gov法令API v2 全法令メタデータ",
        url="https://laws.e-gov.go.jp/api/2/laws",
        license=GOV_STANDARD_TERMS,
        license_url=GOV_STANDARD_TERMS_URL,
        frequency="monthly",
        access="api",
        encoding="utf-8",
        note="limit/offsetのページングで全法令のメタデータ(law_info/revision_info等)を取得する。"
             "所管府省を示すフィールドは存在しない(実測済み)。条文本文(all_xml.zip)は対象外",
    ),
    "ministry-codes": Source(
        id="ministry-codes",
        name="府省コード参照表(GIFコードリストより作成)",
        url="https://github.com/JDA-DM/GIF",
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        frequency="ondemand",
        access="bulk",
        note="小規模で安定した参照表のため data/reference/ にコミットして管理する。"
             "上流から取得した日付は記録されていないため、prov:generatedAtTime には"
             "『このリポジトリに記録した日』を入れる(取得日ではない)",
        local_path="data/reference/ministry-codes.csv",
        # git log --diff-filter=A で確認した、このファイルがリポジトリに入った日
        recorded_on=datetime.date(2026, 8, 22),
        sha256="d0c46d408bf3578a9b3fab221de1101540d1fdc4454e972869e9796d0ca5e094",
    ),
    "rs-system": Source(
        id="rs-system",
        name="行政事業レビュー見える化サイト RSシステム 一括CSVダウンロード",
        url="https://rssystem.go.jp/download-csv",
        # 政府標準利用規約(第2.0版)ではない。RSは「公共データ利用規約(第1.0版)」
        # (PDL1.0)に準拠する、と当サイトの利用規約ページ自体が明記している
        # (2026-08-23 実測。JSバンドル main-Cyt4dzWq.js の i18n 文字列
        # "ps-terms-page-intro-text-2/3" より)。出典記載例(同ページより):
        # 「出典：行政事業レビュー見える化サイト」
        license="公共データ利用規約(第1.0版)(PDL1.0)",
        license_url="https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
        frequency="annual",
        access="bulk",
        encoding="utf-8-sig",
        note="事業年度ごとに15本の関連CSV(zip配布、jgkg.connectors.rs_system."
             "RS_GROUP_FILENAMES参照)に分かれる。単一テーブルではない。"
             "当サイトは「更新型のデータベース」であり(利用規約ページの記載)、"
             "補正予算成立等に伴い同じ事業年度のCSVの内容が年内に更新されることが"
             "ある(取得日の記録が重要になる理由)。ダウンロードページはSPAで専用APIは"
             "無く、実体は https://rssystem.go.jp/files/<year>/rs/<ファイル名>.zip "
             "への直接GET(認証不要、2026-08-23実測)",
    ),
}


def get_source(source_id: str) -> Source:
    if source_id not in SOURCES:
        raise KeyError(f"未登録のソース: {source_id!r}。sources.py に登録してから使う")
    return SOURCES[source_id]
