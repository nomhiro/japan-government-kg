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
        name="府省名簿(RS実データの所管府省庁名+府省庁名の和集合 + 法令経路3機関より作成)",
        # 名簿の主要な出典はRS(37行)。法令経路3行(人事院・会計検査院・
        # 国家公安委員会)はe-Gov法令API実データの法令番号が示す発令機関であり、
        # 単一のurlフィールドでは表現できないため、主要な出典をurlに置きnoteで
        # 補う(裁定B12。judgment call。詳細はtask-5-report.md)
        url="https://rssystem.go.jp",
        # RSのライセンスは政府標準利用規約ではなく「公共データ利用規約
        # (第1.0版)」(rs-systemソースの note 参照)。名簿の37/40行はRS由来
        # なのでこちらを名簿全体の代表ライセンスとする。残り3行の出典
        # (e-Gov法令API)は政府標準利用規約(GOV_STANDARD_TERMS)
        license="公共データ利用規約(第1.0版)(PDL1.0)",
        license_url="https://www.digital.go.jp/resources/open_data/public_data_license_v1.0",
        frequency="ondemand",
        access="bulk",
        note="小規模で安定した名簿のため data/reference/ にコミットして管理する。"
             "37行はRS 2025年度分、列を確認した5本すべて(取得日2026-08-23)の"
             "[5]所管府省庁/政策所管府省庁列と[6]府省庁列のdistinctの和集合"
             "(裁定B15。[5]⊆[6]で、[6]のみに現れる14行は各府省の外局)。"
             "残り3行(人事院・会計検査院・国家公安委員会)はRSの[5][6]いずれの"
             "distinctにも現れないが、e-Gov法令APIの実在の法令番号"
             "(人事院規則一―四 等)が発令機関として指す現存機関(§7.3経路1に"
             "必要。裁定B7のOBSOLETE_ORGANIZATION誤分類の解消対象)。"
             "この3行はRSの年度更新に追従しない(レビュー指摘3。そもそもRSに"
             "実在しないため、将来年度が更新されても反映される予定が無い)。"
             "継続的な整合性はTask 11等の実データ再検証で別途確認すること。"
             "kensei_jun列はRS実データの[4]建制順(任意・裁定B15。府省コードの"
             "意味論と異なるため ministry_code には入れない)。ministry_code列は"
             "現行コードの一次資料が見つかっていないため全行空欄(裁定B12。"
             "旧来の013/017/020はGIF・統計局の利用機関コードいずれとも一致せず"
             "削除した)。上流(RS)には取得日があるが、名簿自体はコミット済み"
             "参照表として扱うため、他のコミット済み参照表と同じ規約で"
             "prov:generatedAtTime には"
             "『このリポジトリに記録した日』を入れる(取得日そのものではない)",
        local_path="data/reference/ministry-codes.csv",
        # git log --diff-filter=AM で確認した、この版(B15: [5][6]和集合40行+
        # kensei_jun列)をリポジトリに記録した日
        recorded_on=datetime.date(2026, 8, 23),
        sha256="5818790d921bc903cd121d4d7faf0f7c2d3b0d73212a01db62b7e835c0bee7b7",
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
