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

[organization_information] project_id=4の行(全列。レビュー指摘4により追記):
  レビューシート,2025,4,情報システムの整備（情報通信技術調達等適正・効率化推進費）,
  13,デジタル庁,デジタル庁,戦略・組織,,統括監理担当,,,,1,デジタル庁,戦略・組織,,
  会計担当,,,,
  → [4]建制順='13'(project_summary等と同じ値。検証0参照)。[13]-[20]は
     「その他担当組織」(この事業を共同で担当する、もう1つの組織・担当者の
     情報。会計担当課室等)。project_id=1の行は[21]作成責任者に実在の
     担当者個人名を含むため、個人名を含まないproject_id=4の行を引用に使う

  **RS_COLがこのファイルの列を使わない理由**: fiscal_year/project_id/
  project_name/ministry_nameの4論理名は、このファイルとproject_summaryで
  **同じインデックス・同じ値**(実測、project_id=1/4双方で確認済み)。
  RS_COLはproject_summaryを正準の出典として選んだ(事業の説明的な内容
  (事業の目的・概要等)を持つ方をTask 7が最初に触る可能性が高いという
  判断。functional な差は無い)。organization_informationは検証0の
  最初の候補として取得し(「組織情報」という名前が最も府省コードに近そうに
  見えたため)、[13]-[21]の「その他担当組織・作成責任者」構造は
  将来別の論理名(共同担当組織・担当者)として使う余地を残すために
  取得を続けている(このタスクでは未使用)

[project_summary] ヘッダ:
  シート種別,事業年度,予算事業ID,事業名,府省庁の建制順,政策所管府省庁,府省庁,
  局・庁,部,課,室,班,係,事業の目的,現状・課題,事業の概要,事業概要URL,事業区分,
  事業開始年度,開始年度不明,事業終了（予定）年度,終了予定なし,主要経費,備考,
  実施方法ー直接実施,実施方法ー補助,実施方法ー負担,実施方法ー交付,
  実施方法ー分担金・拠出金,実施方法ーその他,旧事業番号,整理表表示順
[project_summary] project_id=4の行(冒頭のみ):
  レビューシート,2025,4,情報システムの整備（情報通信技術調達等適正・効率化推進費）,
  13,デジタル庁,デジタル庁,戦略・組織,,統括監理担当,...
  → **[4]府省庁の建制順='13'。この列が検証0で訂正した数値識別子(kensei_jun)**
     (訂正の経緯は下記「検証0」参照。他の4ファイルでも同じ位置に同じ値で現れる)

[policy_measure_laws_and_regulations] project_id=4の行(冒頭のみ):
  ...,1,デジタル庁,情報通信技術等の適正・効率化に関する施策の推進,
  情報通信技術等の適正・効率化に関する施策,https://www.digital.go.jp/policies/assessment/,
  1,デジタル庁設置法,令和三年法律第三十六号,503AC0000000036,第四条,2,第17号,...
  → [19]法令名='デジタル庁設置法' [21]法令ID='503AC0000000036'
     **法令IDは e-Gov の law_id と同一形式**(jgkg.connectors.egov_law の
     取得物と文字列一致で結合できる。名寄せではなく構造化IDでの結合が可能)

[budget_summary] 行構造(レビュー指摘2により追記。**1事業=1行ではない**):

  budget_summaryは1事業年度分のレビューシートの中に、直近5年度分
  (2021〜2025)の予算履歴を格納する。project_idだけでは行を一意に
  特定できず、**(project_id, 予算年度[列13])の複合キーが必要**。
  さらに、この複合キーごとに複数の物理行が束になっている:

    - 「集計行」: [14]当初予算（合計）が非空。1つの(project_id,予算年度)に
      **例外なく必ず1件**存在する(2026-08-23取得の全データ47,100行・
      23,036ペアで検算。0件・2件以上は無かった)
    - 「明細行」(会計区分[25]・会計[26]・勘定[27]が入り、[28]以降に
      同じ額が会計別に再掲される): 1〜5件(会計区分が複数に分かれる
      事業ほど多い。project_summary/organization_informationの
      重複project_id行と同種の「1事業=複数行」構造。下記参照)

  project_id=1の行(冒頭のみ。集計行→明細行の順):
    レビューシート,2025,1,内閣人事局経費（研修事業）,1,内閣官房,内閣官房,内閣人事局,
    ,,,,,2025,34482000,0,0,0,34482000,0,,0,50617000.0,予算単価額の増減による増減,...
    レビューシート,2025,1,内閣人事局経費（研修事業）,1,内閣官房,内閣官房,内閣人事局,
    ,,,,,2025,,,,,,,,,,,,一般会計,一般会計,,34482000,0,0,0,0,0,0,0,0,0,0,
    34482000,0,50617000,15689000,
    → [14]当初予算（合計）='34482000'。**同じ論理値が集計行の
      [22]翌年度要求額（合計）='50617000.0' のように小数点付き文字列で
      現れる列がある一方、明細行の同義列(41列目、翌年度要求額)は
      '50617000' と整数文字列(実測。数値パース時に注意)**

  project_id=828(総務省/消防庁。列5≠列6の実例)fy=2025の行(集計→明細):
    ...,15,総務省,消防庁,消防庁,,予防課,危険物保安室,,,2025,95667000,
    40150000,7594000,0,143411000,0,,0,136095000.0,,...
    ...,15,総務省,消防庁,消防庁,,予防課,危険物保安室,,,2025,,,,,,,,,,,,
    一般会計,一般会計,,95667000,40150000,0,0,0,0,7594000,0,0,0,0,
    143411000,0,136095000,0,

  project_id=159(明細行が3件になる実例。特別会計が複数の勘定に分かれる)
  fy=2023の行(集計→明細×2):
    ...,内閣府,内閣府,政策統括官（原子力防災担当）,,参事官（総括担当）,,,,2023,
    10041533000,0,750269289,0,10791802289,9130510658,0.84606,594791890,
    14809751000.0,"重要政策推進枠：3,010",...
    ...,2023,,,,,,,,,,,,特別会計,エネルギー対策,電源開発促進勘定,
    10041533000,0,0,0,0,0,750269289,...
    ...,2023,,,,,,,,,,,,特別会計,エネルギー対策特別会計電源開発促進勘定,
    ,0,0,0,0,0,0,0,...(備考に「事業単位整理表に金額を表示する為に必要な
    会計明細となりますので、消去しないよう、お願いいたします」という
    RS運用側の内部注記が実データにそのまま残っている)

  project_id=5551(ゼロ予算の実例。「集計行の当初予算（合計)='0'」という
  文字列は空文字ではないので、下記の判定規則で正しく集計行と判定される)
  fy=2025の行(集計→明細):
    ...,13,デジタル庁,デジタル庁,国民向けサービス,,,ＧＥＰＳ／ＧＥＣＳ班,,,2025,
    0,0,0,0,0,0,,0,0.0,...
    ...,2025,,,,,,,,,,,,,,,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    (**明細行の会計区分[25]・会計[26]も空になる**。通常の明細行は
    会計区分が populated だが、ゼロ予算の場合はそれも空という実データの
    もう1つの実例)

  **「ある事業のある年度の当初予算」を一意に特定する規則**(この4例
  (project 1/828/159/5551)全部、および23,036ペア全件の検算で確認済み。
  Task 7 はこの規則だけを頼りに実装してよい):

    1. budget_summaryの行を (project_id, 予算年度[列13]) でフィルタする
    2. その中で [14]当初予算（合計）が**非空**(strip後に空文字でない。
       '0'という文字列は非空なので条件を満たす)の行を選ぶ
    3. その行が**必ず1件だけ**存在する(0件・2件以上は実データの範囲では
       発生しない。発生したらColumnLayoutError。下記find_budget_aggregate_row)
    4. 明細行(手順2で選ばれなかった行)は1〜5件と可変で、無視してよい
       (合計を再計算する必要はない。集計行の値がすでに合計済み)

  **project_summary / organization_information にも同種の複数行構造が
  ある(レビュー指摘5。budget_summaryほど深刻ではないが記録する)**:

    - project_summary: project_id=46「情報収集衛星の研究・開発」は
      2行持つ。project_name/ministry_name/fiscal_yearはどちらの行でも
      同一で、[22]主要経費のみ違う('その他の事項経費' と '科学技術振興費')。
      **1事業が複数の主要経費区分を持つ場合に行が増える**
    - organization_information: project_id=18「政府共通ネットワーク
      （情報通信技術調達等適正・効率化推進費）」は2行持つ。
      project_name/ministry_name/fiscal_yearは同一で、[13]その他担当組織_
      作成責任者_no([1,2])と[21]作成責任者(人名2件)のみ違う。
      **1事業に複数の作成責任者(担当者)がいる場合に行が増える**
    - 両ファイルとも、project_id別に集計した全重複行(project_summary
      241/5,794事業、organization_information 1,012/5,794事業)で
      project_name/ministry_name/fiscal_yearの不一致は**0件**だった
      (2026-08-24実測)。budget_amountのように値そのものが行によって
      食い違う心配は無いが、「project_idで1行取得すればよい」という
      前提はここでも成立しない(先頭行だけ読めば足りるが、複数行の
      存在自体は認識しておくこと)

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

検証0(裁定B11・最優先): **訂正(task-6-review.md 指摘1により訂正。
  当初「数値・記号コードは無い」と結論したが、報告書自身が引用する
  実データと矛盾する誤りだった)。**

  列4(organization_informationでは「建制順」、他4ファイルでは
  「府省庁の建制順」)に、[5]所管府省庁/政策所管府省庁の値と
  **完全な1対1対応(全単射)を成す数値識別子が実在する。**
  取得した5ファイル・約271,000行全件で検算済み: distinct値23、
  「1つの名称が複数の建制順を持つ」「1つの建制順が複数の名称を持つ」の
  いずれも0件(詳細な集計はtask-6-review.md指摘1)。値の例(23件全部の
  対応は data/reference/ministry-codes.csv の kensei_jun 列、または
  下記RS_FILESのcolを参照): 1=内閣官房, 13=デジタル庁, 15=総務省,
  18=財務省, 23=国土交通省, 26=防衛省。**人事院・会計検査院は
  この23件に含まれない**(RSの実データの範囲に、両機関が所管府省庁と
  なる事業が存在しないため)。

  **ただし、裁定B15により建制順は「府省コード」として扱わない。**
  建制順は儀典上の府省の設置順序(組織の設置順)であり、法人番号のような
  恒久的な登録識別子ではない。`org:ministryCode` のような結合キー用途への
  使用は禁止する(013/017/020のときと同じ「実在しそうに見える偽の対応」の
  再発を避けるため)。また、**このタスクが取得したのは2025年度1本のみで
  あり、建制順が省庁再編を挟んで年度をまたいで安定するかは未検証**
  (不安定だと分かったわけではなく、単に確認していないという意味)。

  → RSとの結合(所管府省庁の判定)は、名称マッチ(houjin-bangou由来の
    Organization.nameとの突合)で行う。建制順(`kensei_jun`。下記RS_COL)は
    識別子としてではなく、**府省庁名の粒度([5]と[6]のどちらを採るか)を
    選ぶ根拠**として使う(列5・列6の選定理由は下記「列5(ministry_name)を
    列6より優先する理由」を参照)

列5(ministry_name)を列6より優先する理由(レビュー指摘3により記録):

  列4(建制順)の直後に、隣接する2つの「府省庁」列がある: 列5
  (organization_informationでは「所管府省庁」、他4ファイルでは
  「政策所管府省庁」)と列6(全5ファイル共通で「府省庁」)。**この2列は
  同じ値ではない**(実測、5ファイルとも7.1%〜11.1%の行で不一致。
  detailはtask-6-review.md指摘3)。

  distinct値の数: 列5は23件(建制順と完全に1対1、検証0参照)。
  **列6は37件**(外局まで区別する、より細かい粒度)。列6にのみ現れる
  14件はいずれかの府省の外局: スポーツ庁・文化庁・国税庁・林野庁・
  水産庁・特許庁・消防庁・公害等調整委員会・中央労働委員会・公安調査庁・
  気象庁・海上保安庁・観光庁・運輸安全委員会。

  不一致の実例(project_id=828「危険物事故防止対策の推進」。budget_summaryの
  fixture `tests/fixtures/rs_budget_sample.csv` に実データのまま収録済み):
    [5]政策所管府省庁='総務省'  [6]府省庁='消防庁'  [7]局・庁='消防庁'
    (消防庁は総務省の外局。列6・列7はその実施機関そのものを指すが、
    列5は政策上の所管([建制順]と対応する23分類)を指す)

  `ministry_name`(RS_COL)には**列5を採用する**。理由: 列5の23分類が、
  建制順(kensei_jun、検証0)・data/reference/ministry-codes.csvが
  想定する「府省」の粒度と一致する。列6(37分類)を採用すると、
  外局(消防庁・気象庁等)が本省(総務省・国土交通省等)と同格の
  独立した「府省」として扱われてしまい、ministry-codes.csvの粒度と
  食い違う。

  **列選択を6に書き換えても、既存のpayee/lawのfixtureは検知できない**
  (どちらも列5=列6の行しか含んでいなかったため。budget fixtureの
  project 828行が、この不一致を検査できる最初のfixture行)

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


class ColumnLayoutError(ValueError):
    """実データのヘッダが照合記録(full_header)と一致しない。

    列がずれた・RS側の配布フォーマットが変わったことを示す。organization.py の
    ColumnLayoutError(`src/jgkg/transform/organization.py`、ValueErrorを継承)
    と同じ考え方(円環の外の守衛)・**同じ基底クラス**にしている: fixtureがCOL
    から逆算されていても、実データに対する検査であれば検出できる。RSにはヘッダ
    行があるため、列数の一致だけでなく**ヘッダ文字列そのものの一致**まで検査
    できる(zenken全件データにはヘッダが無く、列数と値の形でしか検査できなかった)。
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
        col={
            "fiscal_year": 1, "project_id": 2, "project_name": 3, "ministry_name": 5,
            "kensei_jun": 4,
        },
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
        col={
            "fiscal_year": 1, "project_id": 2, "project_name": 3, "ministry_name": 5,
            "kensei_jun": 4,
        },
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
            "kensei_jun": 4,
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
            "kensei_jun": 4,
            # 列13(予算年度)。列1(事業年度。レビューシート自体の年度=常に2025)
            # とは別物。budget_summaryは1シートに直近5年度分の予算履歴を
            # 束ねて持つため、この列でのフィルタが必須(下記find_budget_aggregate_row)
            "budget_fiscal_year": 13,
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
            "kensei_jun": 4,
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
    # 建制順。**識別子(府省コード)としては使わない**(裁定B15。検証0の
    # 訂正を参照)。data/reference/ministry-codes.csv の kensei_jun 列と
    # 同じ実データ由来の値(2026-08-23取得)なので一致するはず
    "kensei_jun": ("project_summary", 4),
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


def find_budget_aggregate_row(
    rows: list[list[str]] | list[tuple[str, ...]],
    fiscal_year: str,
) -> list[str] | tuple[str, ...]:
    """budget_summaryの実データ行群(1事業分。project_idを揃えて渡すこと)から、
    指定した予算年度(`fiscal_year`。例 '2025')の「集計行」を一意に返す。

    **budget_summaryは1事業=1行ではない**(上記モジュールdocstring
    「[budget_summary] 行構造」を参照)。集計行は「当初予算（合計）」
    (col["budget_amount"])が非空の行として一意に定まる(2026-08-23実測、
    47,100行・23,036の(project_id,予算年度)ペア全件で例外0件。ゼロ予算の
    17ペアも列14='0'という非空文字列を持つため正しく拾える)。

    予算年度が一致し当初予算（合計）が非空の行が1件でなければ
    ColumnLayoutError にする(実データでは起きないはずの状態。列がずれた・
    別の事業の行が混ざった等を示す)。
    """
    spec = RS_FILES["budget_summary"]
    idx_fy = spec.col["budget_fiscal_year"]
    idx_amount = spec.col["budget_amount"]

    matches = [
        row for row in rows
        if row[idx_fy] == fiscal_year and row[idx_amount].strip() != ""
    ]
    if len(matches) != 1:
        raise ColumnLayoutError(
            f"budget_summary: 予算年度={fiscal_year!r} の集計行が"
            f"{len(matches)}件見つかった(常に1件のはず)。列がずれた、"
            "複数事業の行が混在した等の可能性がある"
        )
    return matches[0]
