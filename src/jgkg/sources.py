"""ソースレジストリ。ライセンスと更新頻度を機械可読で持つ(設計書§11.2)。

ライセンスが未記録のソースを登録してはならない。アプリはこのメタデータを
使って出典と規約を自動表示する。
"""
import datetime
import hashlib
from dataclasses import dataclass

# **B-1修正(2026-08-26。一次資料調査で発見)**: 以前はここに
# `GOV_STANDARD_TERMS = "政府標準利用規約(第2.0版)"`
# `GOV_STANDARD_TERMS_URL = "https://www.digital.go.jp/resources/terms_of_use"`
# があり、`egov-law`・`houjin-bangou`の2ソースがこれを使っていた。**政府標準
# 利用規約は令和6年7月5日(2024-07-05)をもって「公共データ利用規約(第1.0版)」
# (PDL1.0)へ改訂され、廃止されている**(PDL1.0原文自身が「既に以前の政府標準
# 利用規約にしたがって…」と過去形で言及。`GOV_STANDARD_TERMS_URL`は
# 2026-08-26時点で実際に404)。egov-law・houjin-bangouいずれも、規約ページ
# 本文を一次資料で直接確認すると「公共データ利用規約(第1.0版)」を明記して
# おり、「政府標準利用規約」という語自体が出現しない(rs-systemは元々PDL1.0で
# 正しかった。詳細は
# `.superpowers/sdd/2026-08-23-phase1-vertical-slice-data-layer/source-terms-research.md`)。
# **KGのprovenanceグラフ(`dcterms:license`/`dcterms:rights`。rdf/provenance.py)
# はSourceのこの値をそのまま書くため、この訂正前に構築したリリースは
# 404のURLと廃止された規約名を「現在有効な出典」として主張していた。**
PUBLIC_DATA_LICENSE_1_0 = "公共データ利用規約(第1.0版)(PDL1.0)"
PUBLIC_DATA_LICENSE_1_0_URL = "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0"


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
    # 鮮度監視(Task 10。src/jgkg/freshness.py)が「最終取得日からこの日数を
    # 超えたら陳腐化」と判定する基準。**Noneは「無期限(監視対象外)」であって
    # 「毎日更新」ではない** — コミット済み参照表(ministry-codes)は手動更新
    # のみで、上流に定期的な取得元が存在しないため、鮮度の概念自体が適用でき
    # ない(Task 5の非追従3行の性質と整合。data/reference/ministry-codes.csv
    # の note 参照)。値を持つ3ソースはいずれも`frequency`と対応するが、
    # `frequency`自体は人間向けの分類でしきい値を持たないため、機械判定用に
    # 別フィールドとして持つ(houjin-bangou=frequency"monthly"→31日、
    # egov-law=frequency"monthly"→31日、rs-system=frequency"annual"→366日
    # (閏年を跨いでも「年1回」を陳腐化と誤検知しないよう365ではなく366))
    expected_cadence_days: int | None = None
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
        # 規約ページ(https://www.houjin-bangou.nta.go.jp/riyokiyaku/index.html)
        # を一次資料で確認(2026-08-26)。本文は「公共データ利用規約(第1.0版)」
        # に準拠すると明記し、「政府標準利用規約」という語は出現しない
        license=PUBLIC_DATA_LICENSE_1_0,
        license_url=PUBLIC_DATA_LICENSE_1_0_URL,
        frequency="monthly",
        access="bulk",
        encoding="utf-8",
        note="全件データは月次(前月末時点)。差分は日次。商用・再配布可"
             "(PDL1.0原文の「商用利用も可能です」の記載による——houjin-bangou"
             "自身の規約ページ本文にこの語自体は無い)。"
             "Shift_JIS版とUnicode版の両方が配布されているため、Unicode(UTF-8)版を取得すること",
        expected_cadence_days=31,
    ),
    "egov-law": Source(
        id="egov-law",
        name="e-Gov法令API v2 全法令メタデータ",
        url="https://laws.e-gov.go.jp/api/2/laws",
        # 規約ページ(https://laws.e-gov.go.jp/terms)を一次資料で確認
        # (2026-08-26。SPAのためPlaywrightでレンダリングして本文を取得)。
        # 本文は「公共データ利用規約(第1.0版)」に準拠すると明記し、
        # 「政府標準利用規約」という語は出現しない。法令API自体に固有の
        # 追加規約は見つからなかった(APIドキュメントページにあったのは
        # サンプルコードの免責事項のみ)
        license=PUBLIC_DATA_LICENSE_1_0,
        license_url=PUBLIC_DATA_LICENSE_1_0_URL,
        frequency="monthly",
        access="api",
        encoding="utf-8",
        note="limit/offsetのページングで全法令のメタデータ(law_info/revision_info等)を取得する。"
             "所管府省を示すフィールドは存在しない(実測済み)。条文本文(all_xml.zip)は対象外",
        expected_cadence_days=31,
    ),
    "ministry-codes": Source(
        id="ministry-codes",
        name="府省名簿(RS実データの所管府省庁名+府省庁名の和集合 + 法令経路3機関より作成)",
        # 名簿の主要な出典はRS(37行)。法令経路3行(人事院・会計検査院・
        # 国家公安委員会)はe-Gov法令API実データの法令番号が示す発令機関であり、
        # 単一のurlフィールドでは表現できないため、主要な出典をurlに置きnoteで
        # 補う(裁定B12。judgment call。詳細はtask-5-report.md)
        url="https://rssystem.go.jp",
        # **B-1修正(2026-08-26)**: 以前はここに「名簿37/40行はRS由来なので
        # PDL1.0を代表値とする。残り3行(e-Gov法令API由来)は政府標準利用規約」
        # という、規約が異なる前提のコメントがあった。**その前提は誤りだった**
        # ——e-Gov法令API側の規約ページを一次資料で確認すると、実際にはこちらも
        # PDL1.0だった(上記PUBLIC_DATA_LICENSE_1_0のコメント参照)。
        # **40行全てが同じPDL1.0の下にある**。「規約が異なる3行」という構造
        # 自体が存在しなかった
        license=PUBLIC_DATA_LICENSE_1_0,
        license_url=PUBLIC_DATA_LICENSE_1_0_URL,
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
        # expected_cadence_days は既定のNoneのまま(無期限。手動更新のみ)。
        # 上流の定期取得元が無い参照表に「陳腐化」の概念を適用すると、
        # 誰も更新していないだけの安定運用を誤って警報にする(Task 5が
        # 記録した、法令経路3行がRSの年度更新に自動追従しない性質とも整合する)
    ),
    "rs-system": Source(
        id="rs-system",
        name="行政事業レビュー見える化サイト RSシステム 一括CSVダウンロード",
        url="https://rssystem.go.jp/download-csv",
        # 政府標準利用規約(第2.0版)ではない。RSは「公共データ利用規約(第1.0版)」
        # (PDL1.0)に準拠する、と当サイトの利用規約ページ自体が明記している
        # (2026-08-23 実測・2026-08-26再確認。JSバンドル main-Cyt4dzWq.js の
        # i18n 文字列 "ps-terms-page-intro-text-2/3" より)。出典記載例
        # (同ページより): 「出典：行政事業レビュー見える化サイト」
        # **RS自身の規約ページは「法人番号列・根拠法令名列は提供元(国税庁の
        # 法人番号公表サイト/e-Gov法令検索)の利用条件に従う」と明記している**
        # ——このPDL1.0宣言はCSV内の全列を無条件にカバーするわけではない
        # (2026-08-26。source-terms-research.md参照)
        license=PUBLIC_DATA_LICENSE_1_0,
        license_url=PUBLIC_DATA_LICENSE_1_0_URL,
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
        # 年1回(事業年度ごと)。365ではなく366にするのは、閏年を跨ぐ実運用で
        # 「年1回の更新」を1日差で陳腐化と誤検知させないため
        expected_cadence_days=366,
    ),
}


def get_source(source_id: str) -> Source:
    if source_id not in SOURCES:
        raise KeyError(f"未登録のソース: {source_id!r}。sources.py に登録してから使う")
    return SOURCES[source_id]
