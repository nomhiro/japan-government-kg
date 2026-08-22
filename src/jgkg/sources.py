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
}


def get_source(source_id: str) -> Source:
    if source_id not in SOURCES:
        raise KeyError(f"未登録のソース: {source_id!r}。sources.py に登録してから使う")
    return SOURCES[source_id]
