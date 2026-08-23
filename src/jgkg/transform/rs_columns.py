"""RSシステム(行政事業レビュー見える化サイト)実データの列対応。

**ブリーフが要求した `RS_COL: dict[str, str|int]`(論理名→単一テーブルの物理列)
という形は、実データの構造に合わない(このタスクの分岐。報告書に明記)。**
RSは単一のCSVではなく、事業年度ごとに15本の関連CSV(zip配布、テンプレートは
`jgkg.connectors.rs_system.RS_GROUP_FILENAMES` に集約。ここでは複製しない)
に分かれており、全ファイルが 予算事業ID(project_id) と 事業年度(fiscal_year)
を共有キーとして持つ。そのため `RS_COL` は論理名→(ファイルグループ, 列インデックス)
の対応として実装する。

======================================================================
照合記録(2026-08-23)

一次資料: https://rssystem.go.jp (RSシステム。行政事業レビュー見える化サイト)
取得元URL(実際に叩いたURLの詳細・エンコード誤りを含む経緯は
  task-6-report.md を参照): https://rssystem.go.jp/files/2025/rs/<ファイル名>.zip
取得年度: 2025(サイト表示の基準時点 2026年1月19日)
取得日: 2026-08-23
配布形態: zip(内部にCSVが1本のみ)。**取得したバイト列をそのまま保存する**
  (sha256が配布物と一致=出典として追跡できる。connectors/rs_system.py参照)
エンコーディング: UTF-8(BOM付き)。strictデコードで確認済み、cp932では
  1バイト目から失敗(デコード不能)。改行はCRLFのみ(LFのみの行は0件)。
  **BOMは論理値に含めない(呼び出し側は utf-8-sig でデコードするか、
  先頭列からBOM(﻿)を除いてから below の full_header と比較すること)**

このタスクで実データを取得・列を確認した5本(残り10本は
RS_UNVERIFIED_GROUPS。ファイル名のみ判明・列は未照合):

  organization_information            (1-1_基本情報_組織情報, 22列)
  project_summary                     (1-2_基本情報_事業概要等, 32列)
  policy_measure_laws_and_regulations (1-3_基本情報_政策・施策、法令等, 28列)
  budget_summary                      (2-1_予算・執行_サマリ, 44列)
  payee_payment_information           (5-1_支出先_支出情報, 32列)

**5本すべてで、共通ヘッダ([0]シート種別 [1]事業年度 [2]予算事業ID [3]事業名
...[5]府省庁名の列)が同じインデックスに現れる。**偶然ではなく、RS側が
共通ヘッダテンプレートを15本のファイルに使っている設計だと分かる
(実データで確認済み)。

実データの先頭2行の引用(BOM除去済み。project_id=4・デジタル庁の行を使う。
project_id=1の行は実在の担当者個人名を含むため、列検証の証拠価値が同じ
project_id=4の行を引用に使う):

[project_summary] ヘッダ:
  シート種別,事業年度,予算事業ID,事業名,府省庁の建制順,政策所管府省庁,府省庁,
  局・庁,部,課,室,班,係,事業の目的,現状・課題,事業の概要,事業概要URL,事業区分,
  事業開始年度,開始年度不明,事業終了（予定）年度,終了予定なし,主要経費,備考,
  実施方法ー直接実施,実施方法ー補助,実施方法ー負担,実施方法ー交付,
  実施方法ー分担金・拠出金,実施方法ーその他,旧事業番号,整理表表示順
[project_summary] project_id=4の行(冒頭のみ):
  レビューシート,2025,4,情報システムの整備（情報通信技術調達等適正・効率化推進費）,
  13,デジタル庁,デジタル庁,戦略・組織,,統括監理担当,...

[policy_measure_laws_and_regulations] project_id=4の行(冒頭のみ):
  ...,1,デジタル庁,情報通信技術等の適正・効率化に関する施策の推進,
  情報通信技術等の適正・効率化に関する施策,https://www.digital.go.jp/policies/assessment/,
  1,デジタル庁設置法,令和三年法律第三十六号,503AC0000000036,第四条,2,第17号,...
  → [19]法令名='デジタル庁設置法' [21]法令ID='503AC0000000036'
     **法令IDは e-Gov の law_id と同一形式**(jgkg.connectors.egov_law の
     取得物と文字列一致で結合できる。名寄せではなく構造化IDでの結合が可能)

[budget_summary] project_id=1の行(冒頭のみ。集計行):
  レビューシート,2025,1,内閣人事局経費（研修事業）,1,内閣官房,内閣官房,内閣人事局,
  ,,,,,2025,34482000,0,0,0,34482000,0,,0,50617000.0,予算単価額の増減による増減,...
  → [14]当初予算（合計）='34482000'。**同じ論理値が会計区分ごとの明細行では
     [22]翌年度要求額（合計）='50617000.0' のように小数点付き文字列で
     現れる列がある一方、明細側の同義列(41列目)は '50617000' と整数文字列
     (実測。数値パース時に注意)**

[payee_payment_information] project_id=1のブロック行→支出先行(2行1組):
  レビューシート,2025,1,内閣人事局経費（研修事業）,...,A,株式会社ウルフスタイル,1,
  ウェブ会議システムを利用した研修の運営支援に関する業務,3025000 ,,,,,,,,,,,,,,
  レビューシート,2025,1,内閣人事局経費（研修事業）,...,A,,,,,株式会社ウルフスタイル,
  3010001137944 ,東京都中央区築地１丁目９番１１号,301,FALSE,3025000 ,,,,,,,,
  → **1ブロック=1行ではない。「ブロック行」([14]支出先ブロック名のみ埋まり
     [18]支出先名等は空)と「支出先行」([18]支出先名以降が埋まる)が別の物理行**。
     [19]法人番号の実測値には末尾に半角スペースが付く('3010001137944 ')。
     将来のhoujin-bangouとの突合は必ず `.strip()` してから比較すること
======================================================================

検証0(裁定B11・最優先): **府省コード列は無い。**
  確認した5本すべてで、府省庁を表す列は名称文字列のみ
  (所管府省庁 / 政策所管府省庁 / 政策所管府省庁_P / 府省庁)。
  数値・記号のコード列は存在しない。
  → RSとの結合は名称マッチ(houjin-bangou由来のOrganization.nameとの突合)
    に拠るしかない。府省コード参照表(Task 5)がこの結合そのものに必要かは
    別問題(RS側は名称しか持たないため、Task 5の参照表を経由しなくても
    houjin-bangouのOrganization.nameと直接突合できる)

検証1: 根拠法令列は「ある」。
  policy_measure_laws_and_regulations の [19]法令名 と [21]法令ID。
  法令IDはe-Govのlaw_idと同一形式(例 503AC0000000036)であり、文字列一致で
  構造化結合できる。→ §7.3 経路1が完了条件として成立する

検証2: 支出先の法人番号列は「ある」。
  payee_payment_information の [19]法人番号。ただし「ブロック行」には
  構造上入らず(空欄)、実データには**構造的な空欄ではなく実質的に欠落する
  ケースも存在する**: [22]その他支出先='TRUE' かつ [18]支出先名='その他' の行
  (少額・多数の支出先を個別開示せず束ねる、RS側の正規の表現。実データで確認)

検証3: 支出先の住所列は「ある」。
  payee_payment_information の [20]所在地(実測値の例:
  '東京都中央区築地１丁目９番１１号')。
  → B-4により abr-geocoder 導入を起案(住所文字列からの地理識別子解決)
======================================================================
"""

from dataclasses import dataclass, field


class ColumnLayoutError(RuntimeError):
    """実データのヘッダが照合記録(full_header)と一致しない。

    列がずれた・RS側の配布フォーマットが変わったことを示す。organization.py の
    ColumnLayoutError と同じ考え方(円環の外の守衛): fixtureがCOLから逆算されて
    いても、実データに対する検査であれば検出できる。RSにはヘッダ行があるため、
    列数の一致だけでなく**ヘッダ文字列そのものの一致**まで検査できる
    (zenken全件データにはヘッダが無く、列数と値の形でしか検査できなかった)。
    """


@dataclass(frozen=True)
class RSFileSpec:
    """RSの1つの配布CSV(zip内、ヘッダ付き)について確認済みの列対応。"""

    group_key: str  # jgkg.connectors.rs_system.RS_GROUP_FILENAMES のキー
    expected_columns: int
    full_header: tuple[str, ...]  # 実データのヘッダ全列(BOM除去済み)を引用として保持
    col: dict[str, int] = field(default_factory=dict)  # 論理名 -> 列インデックス(0起点)


RS_FILES: dict[str, RSFileSpec] = {
    "organization_information": RSFileSpec(
        group_key="organization_information",
        expected_columns=22,
        full_header=(
            "シート種別", "事業年度", "予算事業ID", "事業名", "建制順", "所管府省庁",
            "府省庁", "局・庁", "部", "課", "室", "班", "係",
            "その他担当組織_作成責任者_no", "府省庁（その他担当組織）",
            "局・庁（その他担当組織）", "部（その他担当組織）", "課（その他担当組織）",
            "室（その他担当組織）", "班（その他担当組織）", "係（その他担当組織）",
            "作成責任者",
        ),
        col={"fiscal_year": 1, "project_id": 2, "project_name": 3, "ministry_name": 5},
    ),
    "project_summary": RSFileSpec(
        group_key="project_summary",
        expected_columns=32,
        full_header=(
            "シート種別", "事業年度", "予算事業ID", "事業名", "府省庁の建制順",
            "政策所管府省庁", "府省庁", "局・庁", "部", "課", "室", "班", "係",
            "事業の目的", "現状・課題", "事業の概要", "事業概要URL", "事業区分",
            "事業開始年度", "開始年度不明", "事業終了（予定）年度", "終了予定なし",
            "主要経費", "備考", "実施方法ー直接実施", "実施方法ー補助",
            "実施方法ー負担", "実施方法ー交付", "実施方法ー分担金・拠出金",
            "実施方法ーその他", "旧事業番号", "整理表表示順",
        ),
        col={"fiscal_year": 1, "project_id": 2, "project_name": 3, "ministry_name": 5},
    ),
    "policy_measure_laws_and_regulations": RSFileSpec(
        group_key="policy_measure_laws_and_regulations",
        expected_columns=28,
        full_header=(
            "シート種別", "事業年度", "予算事業ID", "事業名", "府省庁の建制順",
            "政策所管府省庁", "府省庁", "局・庁", "部", "課", "室", "班", "係",
            "番号（政策・施策）", "政策所管府省庁_P", "政策", "施策", "政策・施策URL",
            "番号（根拠法令）", "法令名", "法令番号", "法令ID", "条", "項",
            "号・号の細分", "番号（関係する計画・通知等）", "計画通知名", "計画通知等URL",
        ),
        col={
            "fiscal_year": 1, "project_id": 2, "project_name": 3, "ministry_name": 5,
            "basis_law_text": 19, "basis_law_number": 20, "basis_law_id": 21,
        },
    ),
    "budget_summary": RSFileSpec(
        group_key="budget_summary",
        expected_columns=44,
        full_header=(
            "シート種別", "事業年度", "予算事業ID", "事業名", "府省庁の建制順",
            "政策所管府省庁", "府省庁", "局・庁", "部", "課", "室", "班", "係",
            "予算年度", "当初予算（合計）", "補正予算（合計）",
            "前年度からの繰越し（合計）", "予備費等（合計）", "計（歳出予算現額合計）",
            "執行額（合計）", "執行率", "翌年度への繰越し(合計）",
            "翌年度要求額（合計）", "主な増減理由", "その他特記事項", "会計区分",
            "会計", "勘定", "当初予算", "第1次補正予算", "第2次補正予算",
            "第3次補正予算", "第4次補正予算", "第5次補正予算", "前年度から繰越し",
            "予備費等1", "予備費等2", "予備費等3", "予備費等4", "歳出予算現額",
            "執行額", "翌年度要求額", "要望額", "備考",
        ),
        col={
            "fiscal_year": 1, "project_id": 2, "project_name": 3, "ministry_name": 5,
            "budget_amount": 14, "executed_amount": 19,
        },
    ),
    "payee_payment_information": RSFileSpec(
        group_key="payee_payment_information",
        expected_columns=32,
        full_header=(
            "シート種別", "事業年度", "予算事業ID", "事業名", "府省庁の建制順",
            "政策所管府省庁", "府省庁", "局・庁", "部", "課", "室", "班", "係",
            "支出先ブロック番号", "支出先ブロック名", "支出先の数", "事業を行う上での役割",
            "ブロックの合計支出額", "支出先名", "法人番号", "所在地", "法人種別",
            "その他支出先", "支出先の合計支出額", "契約概要", "金額", "契約方式等",
            "具体的な契約方式等", "入札者数", "落札率",
            "一者応札・一者応募又は競争性のない随意契約となった理由及び改善策（支出額10億円以上）",
            "その他の契約",
        ),
        col={
            "fiscal_year": 1, "project_id": 2, "project_name": 3, "ministry_name": 5,
            "recipient_name": 18, "recipient_houjin_bangou": 19,
            "recipient_address": 20, "recipient_kind_code": 21,
            "expenditure_amount": 23,
        },
    ),
}

# 論理名 -> (ファイルグループ, 列インデックス)。
# ブリーフが要求した `RS_COL: dict[str, str|int]`(単一テーブル前提)から、
# ファイルの次元を持つ形へ変更した(このタスクの分岐。report参照)
RS_COL: dict[str, tuple[str, int]] = {
    "project_id": ("project_summary", 2),
    "project_name": ("project_summary", 3),
    "ministry_name": ("project_summary", 5),
    "fiscal_year": ("project_summary", 1),
    "budget_amount": ("budget_summary", 14),
    "basis_law_text": ("policy_measure_laws_and_regulations", 19),
    "recipient_name": ("payee_payment_information", 18),
    "recipient_houjin_bangou": ("payee_payment_information", 19),
    "expenditure_amount": ("payee_payment_information", 23),
}

# ファイル名テンプレートは判明しているが、このタスクでは実データを取得しておらず
# 列は未照合(jgkg.connectors.rs_system.RS_GROUP_FILENAMES にテンプレートがある)。
# 将来必要になれば、このタスクと同じ手順(取得→ヘッダ引用→照合記録)で埋める
RS_UNVERIFIED_GROUPS: tuple[str, ...] = (
    "subsidy_rate",
    "related_projects",
    "budget_detail",
    "purpose_result",
    "purpose_connection",
    "inspection_evaluation",
    "payee_payment_block_connection",
    "payee_payment_amount_breakdown",
    "payee_contract",
    "remark",
)


def verify_header(group_key: str, header_row: list[str] | tuple[str, ...]) -> None:
    """実データのヘッダ行を照合記録(full_header)と照合する。

    呼び出し側は utf-8-sig でデコードするか、先頭列のBOM(\\ufeff)を除いてから
    渡すこと(full_header はBOMを含まない)。列数だけでなく、ヘッダの文字列
    そのものが1列でも違えば ColumnLayoutError にする(推測で通さない)。
    """
    spec = RS_FILES[group_key]
    header_row = tuple(header_row)

    if len(header_row) != spec.expected_columns:
        raise ColumnLayoutError(
            f"{group_key}: 列数が照合記録と違う"
            f"(想定{spec.expected_columns}列、実際{len(header_row)}列)。"
            "RSの配布フォーマットが変わった可能性がある。"
            "rs_columns.py の照合記録を実データで更新すること"
        )

    if header_row != spec.full_header:
        mismatches = [
            (i, expected, actual)
            for i, (expected, actual) in enumerate(zip(spec.full_header, header_row))
            if expected != actual
        ]
        raise ColumnLayoutError(
            f"{group_key}: ヘッダの文字列が照合記録と違う: {mismatches}。"
            "RSの配布フォーマットが変わった可能性がある。"
            "rs_columns.py の照合記録を実データで更新すること"
        )
