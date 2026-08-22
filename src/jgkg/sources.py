"""ソースレジストリ。ライセンスと更新頻度を機械可読で持つ(設計書§11.2)。

ライセンスが未記録のソースを登録してはならない。アプリはこのメタデータを
使って出典と規約を自動表示する。
"""
from dataclasses import dataclass

GOV_STANDARD_TERMS = "政府標準利用規約(第2.0版)"
GOV_STANDARD_TERMS_URL = "https://www.digital.go.jp/resources/terms_of_use"


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    license: str
    license_url: str
    frequency: str  # daily / monthly / annual / ondemand
    access: str     # api / bulk / scrape
    note: str = ""


SOURCES: dict[str, Source] = {
    "houjin-bangou": Source(
        id="houjin-bangou",
        name="国税庁 法人番号公表サイト 全件データ",
        url="https://www.houjin-bangou.nta.go.jp/download/zenken/",
        license=GOV_STANDARD_TERMS,
        license_url=GOV_STANDARD_TERMS_URL,
        frequency="monthly",
        access="bulk",
        note="全件データは月次(前月末時点)。差分は日次。商用・再配布可",
    ),
    "ministry-codes": Source(
        id="ministry-codes",
        name="府省コード参照表(GIFコードリストより作成)",
        url="https://github.com/JDA-DM/GIF",
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        frequency="ondemand",
        access="bulk",
        note="小規模で安定した参照表のため data/reference/ にコミットして管理する",
    ),
}


def get_source(source_id: str) -> Source:
    if source_id not in SOURCES:
        raise KeyError(f"未登録のソース: {source_id!r}。sources.py に登録してから使う")
    return SOURCES[source_id]
