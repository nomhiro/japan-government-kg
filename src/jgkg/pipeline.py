"""パイプラインの結線。取得済みスナップショットからN-Quadsまでを1本にする。

各段の件数を PipelineReport として返す。観測性は設計書§11.1の要件。

CLI(Task 11 / B28。`scripts/build.sh` から呼ぶ唯一の入口):

    uv run python -m jgkg.pipeline \
        --source houjin-bangou=2026-08-23 --source egov-law=2026-08-24 \
        --source rs-system=2026-08-23 \
        --out-dir data/artifact/2026-08-24-payees \
        --previous-release 2026-08-23 --include-all-corporations \
        --corporations-scope payees

**`python -c` にシェル変数を埋め込む形をやめてここに置いた理由**: 以前の
build.sh は `fetched_on` を `{'houjin-bangou': date.fromisoformat('$1')}` と
Pythonソースへ文字列展開しており、(a) houjin-bangou 以外のソースを渡す
方法が無く、(b) 引数の検査がシェルの外に無かった。ソースごとに取得日が
違うことは `run()` の第一の設計前提(§6.4の更新頻度表)なので、その前提を
そのまま渡せるCLIをコードとして持ち、テストで固定する。
"""
import argparse
import datetime
import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from rdflib import RDF, Dataset, Graph, URIRef

from jgkg import build, lake, sources, uris, validate
from jgkg.config import get_settings
from jgkg.connectors import egov_law, houjin_bangou, rs_system
from jgkg.rdf import emit, stream_emit
from jgkg.rdf.provenance import provenance_graph
from jgkg.transform import law as law_mod
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import ministry_succession as succession_mod
from jgkg.transform import old_ministries
from jgkg.transform import organization as org_mod
from jgkg.transform import rs as rs_mod

# 全法人の別グラフ(Task 8)のグラフID部分。「houjin-bangou」と同じ取得済み
# スナップショットから作る別グラフなので、sources.pyに新しいソースを登録する
# 必要はない — 出典(provenance_graph)は"houjin-bangou"のsource_idのまま、
# グラフURIだけをこの名前にする(同じ一次資料から2つの異なる粒度のグラフを
# 作っている、という事実をそのまま記録する)
ALL_CORPORATIONS_GRAPH_ID = "houjin-bangou-all"
# Ruling B30(Task 11修正ラウンド。progress.md実測): 全法人(約581万件)は
# TDB2実サイズ13.8GiBで§6.3の8GiB上限を超える。Phase 1のCQがどれも参照
# しないデータのために全法人を積む理由が無い(「消費者のいない取込みを
# 作らない」— B-1/B-2と同じ原則)。支出先(budget:recipientの参照先)として
# 実際に登場し、かつ実在が確認できた法人番号(corporations_all相当・
# distinct 18,941件)だけに絞った別グラフ(実測: docs/measurements-phase1.md
# §2)。**支出先として名指しされた番号の総数(payee_houjin_bangou。
# distinct 18,995件。センチネル1件を含む)とは別の数**——実在しない53件・
# センチネル1件は法人として解決できないため、このグラフには入らない
# (修正ラウンド2 要修正4で「18,994件」という古い記載がこの区別を欠いていた
# ことが判明。docs/measurements-phase1.md「恒等式」節参照)。
# **「全法人」と誤読されないグラフ名にする**(fix-brief指示。manifestと
# CQの読み手がhoujin-bangou-allと混同しないため)
PAYEE_CORPORATIONS_GRAPH_ID = "houjin-bangou-payees"

MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")
SHAPES_DIR = Path("schema/generated")

# D-2裁定: cq06の新クエリ(budget:recipientMatchCategoryを直接読む)と
# 旧クエリ(recipient/payeeLabel/UnresolvedReferenceの有無から推論する。
# クエリ本体はもう使わないが、独立オラクルとしてこのファイルに残す —
# queries/cq/legacy-cq06-optional-inference.rqのヘッダコメント参照)が
# 同じ結果を返すことをビルド時に突き合わせるための2ファイル
_CQ06_NEW_QUERY_PATH = Path("queries/cq/cq06-unresolved-recipients-per-project.rq")
_CQ06_LEGACY_QUERY_PATH = Path("queries/cq/legacy-cq06-optional-inference.rq")

# =============================================================================
# Task 10: 更新の一巡(差分検出・carry-over)
#
# 各ソース固有グラフが実際に依存する入力ソースの集合(自分自身を含む)。
# carry-over(据え置き)は、そのグラフを作るのに使う**全ての**依存元が前
# リリースから不変であることを要求する。houjin-bangou自体のバイト列が
# 不変でも、egov-law(jurisdiction解決)・rs-system(ministry/recipient解決)
# のグラフ内容はhoujin-bangou由来のministriesに依存するため、自ソースの
# sha256だけを見る判定は不健全(advisorレビュー指摘。実測はしていないが、
# houjin-bangouが変わればministriesの突合結果が変わりうるという構造上の
# 事実から導かれる)。
#
# ministry-codesはここに登場しない — 40行規模で毎回再計算する前提
# (下記 run() 参照。再計算コストが自明に軽いため、carry-overの対象に
# する理由が無い)だが、他ソースの依存集合には含める(そのグラフが
# ministry-codesの内容にも依存するため)。
#
# egov-law-data(C-3。ministry_succession/C-1・C-2が解決するAbolishedGovern
# mentOrganの元)も58行規模で毎回再計算する前提——egov-law-data自身の
# グラフはcarry-overの対象にしない(下記run()参照。常に再emitする)。
#
# **ただしこれはministry-codesと同型ではない。** egov-lawの依存集合には
# egov-law-dataを含めており(egov-lawのjurisdictionがAbolishedGovernment
# Organを指す〔裁定2〕ようになったため)、かつ_carry_over_source_date側は
# egov-law-dataについて**通常の日付比較を行う**(ministry-codesだけを
# skipし、egov-law-dataはskipしない)。理由: ministry-codesは「内容が
# 毎回同じなら結果も同じ」という前提が成り立つ決定的な40行だが、
# egov-law-dataは**その有無自体**がegov-lawのjurisdiction解決結果を
# 左右する(abolished_ministriesが空か18件かで、同じ法令番号が同じ
# 府省名を指していてもOLD_MINISTRY/resolved_abolishedのどちらになるかが
# 変わる)。ここをministry-codesと同じskip対象にしていた実装は、
# egov-law-dataを初めて含めたリリースで旧リリース(egov-law-data無し)の
# egov-lawグラフをそのまま据え置いてしまい、pipeline-report.jsonの
# law_jurisdiction_resolved_abolishedだけが正しく更新され、kg.nq自身には
# 反映されないという内部矛盾を実際に発生させた(2026-08-27、C-4のリリース
# 再構築で発見。docs/measurements-phase1.md参照)
# =============================================================================
_GRAPH_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "houjin-bangou": ("houjin-bangou",),
    "egov-law": ("houjin-bangou", "ministry-codes", "egov-law", "egov-law-data"),
    "rs-system": ("houjin-bangou", "ministry-codes", "egov-law", "rs-system"),
}

# Task 10修正ラウンド1(観察3): 単一ファイルソースの正しいファイル名。
# 同じ日付ディレクトリに別ファイルが増えた場合、ファイル名で絞らないと
# ソート順で先に来た方のsha256を黙って拾ってしまう(このモジュール内の
# houjin-bangouスナップショット取得(`run()`内、houjin_snapshot探索部)が
# 既に同じ罠に対して`s.path.name == houjin_bangou.FILENAME`の絞り込みを
# 持っているのと同じ理由。rs-systemは`_rs_system_file_digests`が既に
# 「その日付の全ファイル」を集めるので対象外)
#
# **egov-law-data(C-3)**: `egov_law.LAW_DATA_SOURCE_ID`のファイル名は
# 本来`f"law_data_{law_id}.json"`とlaw_id可変(同じ日に複数law_idのファイル
# が共存しうる。`fetch.py`のコメント参照)。**このパイプラインが実際に
# 読むのは`ministry_succession.SUCCESSION_LAW_ID`(412CO0000000315)1件
# だけ**なので、その1件に固定する——一般のegov-law-data全体の同一性では
# なく、このパイプラインが依存する対象そのものの同一性を見る
_SINGLE_FILE_SOURCE_FILENAMES: dict[str, str] = {
    "houjin-bangou": houjin_bangou.FILENAME,
    "egov-law": egov_law.FILENAME,
    "egov-law-data": egov_law.law_data_filename(succession_mod.SUCCESSION_LAW_ID),
}


class PipelineReport(BaseModel):
    release: str
    # 入力スナップショットの非空行数。**破損や欠落の検知に使うのはこれと
    # organizations の差(rows_rejected)である**
    rows_seen: int
    # 法人番号が13桁でないなどの理由で取り込まなかった行数。
    # 列レイアウトの誤りは _assert_layout_plausible が例外にするが、しきい値
    # (50%)の下では黙って消えるため、件数をここに出す(設計書§11.1の観測性)
    rows_rejected: int
    # COL が要求する列数に足りなかった行数。住所などが空文字になっている
    rows_short: int
    # **取り込んだ**件数(以前のコメントは「全件数」と書いていたが事実と違った。
    # 全件数は rows_seen で、その差が捨てた数である)
    organizations: int
    # そのうちKGに入れた件数(国の機関のみ)。organizations との差が
    # 「絞り込みで除外された数」になる。両方を出さないと、レポートを読んだ人が
    # 「解析した件数がKGに入っている」と誤解する
    government_organs: int
    ministries: int
    unmatched_ministries: int
    graphs_validated: int
    graphs_quarantined: int
    # 検証を通ったグラフのURI一覧。manifest に渡すため正確な値をここで持つ
    # (N-Quadsのテキストから推測すると、リテラルに含まれる `>` や3項行の
    #  オブジェクトIRIを誤認する。実測で確認済み)。**Task 10以降はcarry-over
    # で引き継いだグラフのURIも含む**(clean.graphs()から導出するため自然に含まれる)
    graphs: list[str]
    # ソースIDごとの「いつ時点か」。**単一の取得日でリリース全体を語らない。**
    # 設計書§6.4の更新頻度表は monthly/annual/ondemand とソースごとに異なる。
    # manifest はこれをそのまま使う(build.sh で手書きしない)。
    # **KGに実際に残ったソースだけを載せる。** 隔離されたソースの日付を書くと
    # 「この日付のデータを含む」という嘘になる(I2 で直した捏造と同族)。
    # **Task 10: 据え置き(carried over)したソースは、今回の取得日ではなく
    # 前リリース時点の日付を載せる**(「実際に入っているもの」原則。同じ理由)
    sources: dict[str, str]
    # 隔離されて成果物に入らなかったソース。**落ちたことを黙って消さない**ため、
    # sources から外す代わりにここに出す(設計書§8.2「未解決を無かったことにしない」)
    quarantined_sources: list[str]
    # 参照整合ゲート(裁定B4)の違反。グラフを跨ぐ参照(law:jurisdiction等)の
    # 型制約はグラフ単位のSHACLでは検証できないため、`validate.
    # check_reference_integrity` が和集合Dataset(検証を通ったグラフのみ。
    # `clean`)に対して別途検査する。空でなければ enforce_release_gate が
    # quarantine と同じ扱いで止める
    reference_violations: list[str]
    # 裁定B54(2026-08-27): 本レポートの集計(常にjurisdictionsから独立に
    # 計算する)が、実際に出力された`clean`(=kg.nq)と食い違わないこと。
    # carry-overがegov-lawを意図せず据え置くと、resolved_abolishedだけが
    # 正しい値を報告し、kg.nq自身には反映されないという「レポートが嘘を
    # つく」状態が実際に発生した(C-4のリリース再構築で発見。
    # docs/measurements-phase1.md参照)。参照整合ゲート(型は合っている)
    # では検出できない(数が食い違うだけ)ため別枠にする。空でなければ
    # enforce_release_gate が reference_violations と同じ扱いで止める
    #
    # D-2裁定(2026-08-28): 2つ目の不変条件をここに合流させた(新しい欄は
    # 増やさない——ゲートの配線・constructorの引き渡しを二重化しても
    # 止める力は増えない)。`budget:recipientMatchCategory`(emit時に明示した
    # 4分類)と、cq06の旧クエリ(recipient/payeeLabel/UnresolvedReferenceの
    # 有無から推論する。`queries/cq/legacy-cq06-optional-inference.rq`)を
    # 同じ`clean`に対して突き合わせ、(project, category)ごとの件数が
    # 食い違えばここに追加される(`_expenditure_category_mismatches`)
    report_graph_mismatches: list[str]
    # Task 8: `--include-all-corporations`(相当のフラグ)が指定されたときだけ
    # 意味を持つ。フラグ未指定なら3つとも既定値0のまま(全法人ストリームに
    # 触れていないことがそのまま分かる)
    #
    # houjin-bangou-all(またはhoujin-bangou-payees)グラフに実際に書き出した
    # エンティティ数(dedup後)。「全法人約581万件」または「支出先限定
    # 約19,000件」の実測値がここに載る(どちらかは corporations_scope で分かる)
    corporations_all: int = 0
    # 法人番号の重複により上流でdedupして弾いた行数。**消したことを黙らない**
    # (stream_emit.StreamStats.dedup_removedがそのまま渡る)
    corporations_all_dedup_removed: int = 0
    # バッチSHACL検証(validate_stream)で不合格だったバッチ数。0でなければ
    # 法人グラフ(all/payeesのいずれか)はkg.nqに追記されない(検証前に本体へ
    # 混ぜない)。enforce_release_gateがこれも見て止める
    corporations_all_quarantined: int = 0
    # Ruling B30(Task 11修正ラウンド): include_all_corporations=True のとき、
    # 実際にどちらの範囲で法人グラフを作ったか。**Noneはinclude_all_corporations
    # =False(法人グラフ自体を作っていない)と区別する**(stream_emit.
    # StreamStats.houjin_bangou_seenと同じ「None≠既定値」の作法)。
    # manifest・報告書の読み手が「全法人」と「支出先限定」を取り違えないための
    # 唯一の出典(fix-brief「どちらを使ったかをPipelineReportに記録する」)
    corporations_scope: Literal["all", "payees"] | None = None

    # =========================================================================
    # Task 10: 更新の一巡(差分検出・carry-over)
    # =========================================================================
    # 据え置き(前リリースからバイト単位で不変と判定し、再生成をスキップして
    # 前リリースのグラフをそのまま引き継いだ)グラフのURI一覧。**引き継いだ
    # 元のグラフのURI**(このリリースの取得日ではなく、前リリースでの実際の
    # 日付)を載せる — 「この取得日のデータを含む」という嘘を作らないため
    carried_over: list[str] = []

    # =========================================================================
    # Task 10: egov-law結線(観測性。§11.1)。derive_jurisdictionの3値分類の
    # うち、pipeline.pyが実際に集計できるようになった件数(law.py
    # ExtractionFailed のdocstringが「結線タスクが行う」と申し送っていた計数)
    #
    # **Task 10修正ラウンド1(要修正2): 「未実行」は`None`、「実行して0件」は
    # `0`。** egov-lawは自身が据え置き対象でも解析(parse_laws/
    # derive_jurisdiction)そのものは省略しない(rs-systemの根拠法令解決が
    # law_recordsを必要とするため)ので、この4項目が`0`のまま(=未実行)に
    # なるのは`"egov-law" not in fetched_on`(このリリースにegov-lawを
    # 含めていない)場合だけ。このコードベース自身が`0`と`None`を区別する
    # 作法を既に持っている(`stream_emit.StreamStats.houjin_bangou_seen`/
    # `freshness.StaleSource.days_since_last_fetch`)ため、同じ規則に従う
    # (task-10-review.md要修正2)。
    # =========================================================================
    law_records: int | None = None
    law_jurisdiction_resolved: int | None = None    # JurisdictionResult.resolved の延べ数
    # C-3: JurisdictionResult.resolved_abolished の延べ数(旧省庁名を当時の
    # 組織=AbolishedGovernmentOrganへ解決できた件数。現存府省への
    # resolvedとは別に数える——型が違う値を1つの数字に混ぜない)
    law_jurisdiction_resolved_abolished: int | None = None
    law_jurisdiction_unresolved: int | None = None  # JurisdictionResult.unresolved の延べ数
    # 最終レビュー要修正5(完了条件「未解決の件数がpipeline-reportとCQ9の
    # 両方から見える」の未達への対応): 理由別(law_mod.UNRESOLVED_REASONSの
    # 4値。OLD_MINISTRY/OBSOLETE_ORGANIZATION/NO_CANDIDATE/AMBIGUOUS)の内訳。
    # **0件の理由もキーとして持つ**(4キー全部を出す) — 例えば
    # NO_CANDIDATE(「抽出そのものを疑うべき警報」)が3→503に増えても、
    # law_jurisdiction_unresolvedの一括値だけでは変化がリリース記録に
    # 現れない(実測。修正前の欠陥そのもの)。キー自体は`law_mod`の
    # `Literal`型から導出する(手書きの列挙をここに複製しない)。
    law_jurisdiction_unresolved_by_reason: dict[str, int] | None = None
    # 府省令・規則の形をしているのに名称を抽出できなかった件数
    # (law.EXTRACTION_FAILED。件数を「経路1の欠陥」と読むと過大評価になる
    # ことに注意 — 皇室令など非府省令の法形式もここに拾われる。task-4-report.md
    # Task 11への申し送り参照)
    law_jurisdiction_extraction_failed: int | None = None

    # =========================================================================
    # Task 10: rs-system結線。rs.BuildStatsを結線後に初めてPipelineReportへ
    # 搭載する(rs.py docstring「PipelineReportに載せることは結線を担うタスク
    # の作業」)。
    #
    # **Task 10修正ラウンド1(要修正2): 「未実行」は`None`、「実行して0件」は
    # `0`。** `"rs-system" not in fetched_on`(このリリースにrs-systemを
    # 含めていない)場合、または含めているがそのグラフが据え置き
    # (carried_over)された場合(据え置きは解決処理そのものを走らせない
    # ——carry-overの実際の計算コスト削減がここ)は`None`になる。元implementerは
    # 「フラグOFF時に0のままであるcorporations_all系と同じ形」と説明していたが、
    # corporations_all自身も同じ非対称を抱えている既存の債務であり、正しい
    # 規則の方(0とNoneの区別)を新規フィールドには最初から適用する
    # (task-10-review.md要修正2。corporations_all側の修正はTask 11以降に
    # 委ねる——今回の差分で新規に増えたのはこちらの21フィールドが本題)。
    # 据え置き元の実際の値は前リリースのreportを参照する。
    # =========================================================================
    budget_projects: int | None = None
    budget_expenditures: int | None = None
    budget_expenditures_bundled: int | None = None
    budget_recipients_sentinel: int | None = None
    # Ruling B27(Task 10修正ラウンド1): 形式は法人番号だが実在しない
    # (法人番号公表サイトの全件データに存在しない)ため直結しなかった件数。
    # 実データで全法人フラグONでも60件・distinct53件が残ることが確定している
    budget_recipients_nonexistent_houjin_bangou: int | None = None
    budget_recipients_resolved_by_houjin_bangou: int | None = None
    budget_recipients_resolved_by_name: int | None = None
    budget_recipients_unresolved: int | None = None
    budget_ministries_resolved: int | None = None
    budget_ministries_unresolved: int | None = None
    budget_basis_law_resolved: int | None = None
    budget_basis_law_unresolved: int | None = None

    # 裁定B24(6): 「合計≒執行額」はゲートにしない(正しい事業でも一致は
    # 32.0%のみ、と確定済み。task-9-report.md)。事業ごとのΣ(Expenditure.
    # amount) ÷ 直前年度の執行額(合計)の比を、ゲートにせず**観測**として
    # 件数だけ載せる。分母が無い(prior_year_executed_amountがNoneまたは
    # 0以下)事業は budget_ratio_no_denominator に分けて数え、「その他」
    # (1.0/2.0/3.0のいずれでもない)と混同しない。
    # **合計(Σ)が0の事業も別枠にする**(budget_ratio_total_zero)。
    # task-9-report.mdの実測(「exact 1.0 = 1,488 / それ他 = 2,877 /
    # Σ[23]==0 = 36」。分母>0の4,646事業に対する集計)がこの3者を
    # 別々に数えており、その他へ合流させると突き合わせ時に36件分ずれる
    # (advisor2回目レビュー指摘)。**budget_*と同じ理由でNone/0を区別する**
    # (rs-system未実行/据え置きなら`None`)
    budget_ratio_exact_1_0: int | None = None
    budget_ratio_exact_2_0: int | None = None
    budget_ratio_exact_3_0: int | None = None
    budget_ratio_total_zero: int | None = None
    budget_ratio_other: int | None = None
    budget_ratio_no_denominator: int | None = None


class QuarantineNotEmptyError(RuntimeError):
    """隔離が発生した状態でリリースしようとした。"""


def enforce_release_gate(report: PipelineReport, *, allow_partial: bool = False) -> None:
    """隔離・参照整合違反のいずれかが起きていたらリリース処理を止める(設計書§6.3)。

    グラフ単位で隔離するため、**5百万行のうち1行の違反でそのソースのグラフ全体が
    落ちる。** そのとき残るのは出典グラフだけなので、KGは「2026-08-01時点の法人番号
    データを含む」と答え続けるのに中身が無い、という状態になる。設計書§6.3は
    「CIで検証を通った成果物だけが本番に出るという構造を強制する」と書いているが、
    この判定を行う場所がどのタスクにも割り当てられていなかった。

    **参照整合ゲート(裁定B4)の違反も同じ扱いで止める。** グラフを跨ぐ参照の
    型制約はSHACLの隔離では検出できない(グラフ単位でしか検証しないため)。
    どちらのグラフが「悪い」かを一意に決められない違反(参照元と参照先が別の
    グラフにある)なので、特定のグラフを隔離するのではなく、リリース全体を
    同じゲートで止める。

    **既定は止まる側。** 部分的なリリースが必要な運用は、呼び出し側が
    `allow_partial=True`(build.sh では `--allow-partial`)を明示的に渡す。
    「気づかずに出荷される」経路を無くすことが目的なので、既定を緩めてはならない。
    """
    if (
        report.graphs_quarantined == 0
        and not report.reference_violations
        and not report.report_graph_mismatches
        and report.corporations_all_quarantined == 0
    ):
        return
    parts = []
    if report.graphs_quarantined:
        parts.append(
            f"SHACL検証で {report.graphs_quarantined} グラフが隔離された"
            f"(検証したグラフ数 {report.graphs_validated}、"
            f"残ったグラフ {report.graphs})。"
            f" 隔離内容は quarantine ディレクトリを見る"
        )
    if report.reference_violations:
        parts.append(
            f"参照整合ゲートで {len(report.reference_violations)} 件の違反"
            f"(例: {report.reference_violations[0]})"
        )
    if report.report_graph_mismatches:
        # 裁定B54: レポートの主張とkg.nq自身の食い違い(PipelineReport.
        # report_graph_mismatchesのdocstring参照)。型は合っているため
        # 参照整合ゲートでは検出できない——別枠で同じ扱いで止める
        parts.append(
            f"レポートと出力グラフの不整合が {len(report.report_graph_mismatches)} 件"
            f"(例: {report.report_graph_mismatches[0]})"
        )
    if report.corporations_all_quarantined:
        parts.append(
            f"全法人のバッチSHACL検証で {report.corporations_all_quarantined} "
            "バッチが不合格になった(houjin-bangou-allグラフはkg.nqに未反映)"
        )
    message = "。".join(parts) + (
        "。このままリリースすると、中身が無いか参照が壊れたKGが出荷される"
    )
    if allow_partial:
        print(f"警告: {message} — allow_partial が指定されているので続行する")
        return
    raise QuarantineNotEmptyError(
        f"{message}。意図的に部分リリースするなら allow_partial を指定する"
    )


def _merge(target: Dataset, source: Dataset) -> None:
    for ctx in source.graphs():
        if len(ctx) == 0:
            continue
        g = target.graph(ctx.identifier)
        for triple in ctx:
            g.add(triple)


def _source_date(
    source_id: str, fetched_on: Mapping[str, datetime.date]
) -> datetime.date:
    """そのソースが「いつ時点」かを決める。

    呼び出し側が渡した取得日が最優先。渡されていない場合、リポジトリにコミット
    された参照表なら「記録した日」を使う(それが分かっている唯一の事実)。
    どちらも無ければ**推測せずに失敗する**。以前は法人番号スナップショットの
    取得日を府省参照表に流用しており、CQ P0-4 が根拠のない日付を答えていた。
    """
    if source_id in fetched_on:
        return fetched_on[source_id]
    src = sources.get_source(source_id)
    if src.recorded_on is not None:
        return src.recorded_on
    raise KeyError(
        f"ソース {source_id!r} の取得日が渡されていない。"
        " 取得して来るソースは呼び出し側が日付を渡す(pipeline.run の fetched_on)。"
        " リポジトリにコミットする参照表なら sources.py に recorded_on を記録する"
    )


# =============================================================================
# Task 10: 差分検出(carry-over判定)のヘルパー
# =============================================================================


def _rs_system_file_digests(fetched_on: datetime.date) -> dict[str, str]:
    """指定日のrs-systemスナップショット全ファイルの(ファイル名 -> sha256)。"""
    return {
        s.path.name: s.sha256
        for s in lake.list_snapshots("rs-system")
        if s.fetched_on == fetched_on
    }


def _previous_date_if_unchanged(
    source_id: str, current_date: datetime.date, previous_fetched_on: datetime.date
) -> datetime.date | None:
    """`source_id`が前リリース時点からバイト単位で不変なら、`previous_fetched_on`

    (前リリースのmanifest.sourcesに記録された、そのソースの実際の取得日)を
    そのまま返す。変化していれば`None`。

    rs-systemは事業年度ごと15本の関連ファイルに分かれるため、単一の
    sha256では比較できない — ファイル名の集合ごと突き合わせる(1本でも
    増減・変化していれば不変ではない)。

    **houjin-bangou/egov-law(単一ファイルソース)はファイル名で絞り込む**
    (task-10-review.md観察3)。同じ日付ディレクトリに別ファイル(サイドカー等)
    が増えても、`list_snapshots`をファイル名で絞り込んで比較するため、
    無関係なファイルの増減が判定を汚染しない。

    **Ruling B31修正ラウンド3(項目1)**: 以前はここで`lake.latest_before(
    source_id, previous_release)`を呼び、「前リリースの日付以前の直近
    スナップショット」を**探索**していた。これには2つの問題があった:
    (1) `previous_release`が成果物ディレクトリのbasename(日付である保証が
    ない)になったため、この探索はそもそも成立しない。(2) 探索であること
    自体が別の欠陥だった——`lake.latest_before`の「直近」は、後から鮮度の
    異なるスナップショットが増えると答えが変わりうる(裁定B33の
    `scripts/compare_releases.py`docstringが指摘した「RS-2024取得により
    `lake.latest_before`の直近判定が変わり、以後は同じ入力でリリースBの
    carry-over判定が再現できない」不安定性そのもの)。`previous_fetched_on`は
    前リリースのmanifest.sourcesに**そのリリースが実際に使った値として
    既に記録されている**ため、探索は不要であり、直接その日付のスナップショット
    を見ればよい(探索より正確——前リリースが実際に使った値そのものだから。
    副次的にこの不安定性も解消する)。
    """
    if source_id == "rs-system":
        current_digests = _rs_system_file_digests(current_date)
        prev_digests = _rs_system_file_digests(previous_fetched_on)
        if not prev_digests:
            return None
        return previous_fetched_on if prev_digests == current_digests else None

    filename = _SINGLE_FILE_SOURCE_FILENAMES[source_id]
    prev_snapshot = next(
        (
            s
            for s in lake.list_snapshots(source_id)
            if s.fetched_on == previous_fetched_on and s.path.name == filename
        ),
        None,
    )
    if prev_snapshot is None:
        return None
    current_snapshot = next(
        (
            s
            for s in lake.list_snapshots(source_id)
            if s.fetched_on == current_date and s.path.name == filename
        ),
        None,
    )
    if current_snapshot is None or current_snapshot.sha256 != prev_snapshot.sha256:
        return None
    return prev_snapshot.fetched_on


def _carry_over_source_date(
    own_source_id: str,
    fetched_on: Mapping[str, datetime.date],
    previous_sources: Mapping[str, datetime.date] | None,
) -> datetime.date | None:
    """`own_source_id`のグラフを据え置ける場合、その前リリース時点の

    fetched_onを返す。**依存元(`_GRAPH_DEPENDENCIES`)のいずれか1つでも
    変化していれば`None`**(このグラフ自身は再生成する) — `own_source_id`
    自身のバイト列が不変でも、egov-law/rs-systemはhoujin-bangou由来の
    ministriesの解決結果に依存するため、自ソースだけを見る判定は不健全
    (このモジュールのコメント「Task 10: 更新の一巡」参照)。

    `previous_sources`: 前リリースのmanifest.sourcesを日付にパースしたもの
    (`_previous_release_sources`)。**Ruling B31修正ラウンド3(項目1)**:
    以前はこの関数自体が`previous_release`(前リリースの識別子)を受け取り、
    それを日付として`_previous_date_if_unchanged`に渡していた。B31で
    `previous_release`が成果物ディレクトリのbasename(日付である保証がない)
    になったため、この関数はもう「前リリースの識別子」ではなく「前リリースが
    各ソースについて実際に使った取得日の一覧」を受け取る形に変えた
    (呼び出し側`run()`が`previous_release is None`なら`previous_sources`も
    `None`を渡す規約——このチェックは変わらず有効)。
    """
    if previous_sources is None or own_source_id not in fetched_on:
        return None
    result: datetime.date | None = None
    for dep in _GRAPH_DEPENDENCIES[own_source_id]:
        if dep == "ministry-codes":
            continue  # 常に再計算する前提。依存判定には数えない
        # **C-3実測で発見した回帰(2026-08-27)**: ここに"egov-law-data"も
        # ministry-codesと同じ理由でスキップに加えていたが、それは誤りだった。
        # ministry-codesは「内容が毎回同じなら結果も同じ」という前提が成立する
        # (40行規模で決定的)。egov-law-dataは違う——**その「有無」自体**が
        # egov-lawのjurisdiction解決結果を左右する(裁定2: abolished_ministries
        # が空か18件かで、同じ法令が同じ府省名を指していてもOLD_MINISTRY/
        # resolved_abolishedのどちらになるかが変わる)。このスキップにより、
        # egov-law-dataを初めて含めたリリースでも旧リリース(egov-law-data無し)
        # のegov-lawグラフがそのまま据え置かれ、pipeline-report.jsonには
        # 新しいresolved_abolishedの値が出るのにkg.nq自身には反映されない、
        # という内部矛盾を実際に踏んだ(law_records等の集計はcarry-over判定と
        # 独立に常に計算されるため、レポートだけが「先に」正しくなっていた)。
        # egov-law-data自身がcarry-over対象にならないこと(下記run()の
        # 常時再emit)とは別の問題であり、他の依存元と同じ通常の日付比較に戻す
        dep_date = fetched_on.get(dep)
        if dep_date is None:
            # 依存元ソースが今回の実行対象に含まれていない。保守的に
            # 「不変と確認できない」として据え置きを諦める
            return None
        prev_fetched_on = previous_sources.get(dep)
        if prev_fetched_on is None:
            # 前リリースがこの依存元ソースを含んでいなかった。保守的に
            # 「不変と確認できない」として据え置きを諦める
            return None
        prev_date = _previous_date_if_unchanged(dep, dep_date, prev_fetched_on)
        if prev_date is None:
            return None
        if dep == own_source_id:
            result = prev_date
    return result


def _previous_release_manifest(previous_release: str) -> build.Manifest:
    """前リリース(成果物ディレクトリのbasename)のmanifest.jsonを読む。

    **manifest.jsonの存在を出荷済みの証拠とする**(Task 10修正ラウンド1。
    Ruling B26)。以前は`kg.nq`の存在だけを「前リリースが実在する」証拠に
    していたが、`build.sh`は`run()`がkg.nqを書いた**後**に
    `enforce_release_gate`を呼び、ゲートで落ちれば`set -e`によりtdb2構築・
    manifest作成に進まない(`scripts/build.sh`参照)。つまり「**kg.nqは
    あるがmanifest.jsonは無い**」=**出荷を拒否されたリリース**という状態が
    実運用で必ず生じる(task-10-review.md要修正1の実測[a])。`lake.save`が
    `meta.json`の存在を「コミット済み」の印にしている先例(`lake.py`の
    docstring: 「データ本体だけが残った中途半端な状態は未コミットとみなす」)
    と、リリースにも同じ印(manifest.json)を要求することで揃える。

    **Ruling B31修正ラウンド3(項目1)**: `previous_release`は成果物
    ディレクトリのbasename(日付である保証がない)。以前は`.isoformat()`を
    呼んでパスを組んでいたが、basenameはそのまま文字列としてパスに使う。
    """
    if "/" in previous_release or "\\" in previous_release or ":" in previous_release:
        # 最終レビュー観察O11: `/`・`\`だけでは、Windowsのドライブ相対パス
        # (`"C:foo"`)を弾けない。`artifact_dir`の既定値`"data/artifact"`
        # (相対パス。config.py)を使う実運用の構成では、
        # `Path("data/artifact") / "C:foo"`は結合を無視して
        # `WindowsPath('C:foo')`になり(`is_absolute()`もFalseのまま)、
        # `artifact_dir`の外(カレントドライブの相対位置)を指す
        # (実行して確認済み)。**`artifact_dir`が既に絶対パスの場合は
        # 同一ドライブなら結合先が`artifact_dir`配下に留まる**(pathlibの
        # 挙動。テストのtmp_pathベースのartifact_dirがこちらに当たるため、
        # テスト側の壊し確認は「素通りしてFileNotFoundErrorになる」形で
        # 現れる——本来のエスケープを再現するものではない。実運用の相対
        # パス構成に対する脆弱性そのものは変わらないため、設定に関わらず
        # `:`を区切り文字として拒否する。
        raise ValueError(
            f"previous_release にはディレクトリの区切り文字を含めない"
            f"(成果物ディレクトリのbasenameだけを渡す): {previous_release!r}"
        )
    release_dir = Path(get_settings().artifact_dir) / previous_release
    manifest_path = release_dir / build.MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"前リリース({previous_release})のmanifest.jsonが"
            f"見つからない: {manifest_path}。kg.nqの存在だけは出荷済みの証拠に"
            "ならない(build.shはenforce_release_gateを通過した後にだけ"
            "manifest.jsonを書くため、出荷を拒否されたリリースにもkg.nqは"
            "存在しうる)。previous_release を渡す呼び出しは、そのリリースが"
            "実際に出荷されたことを前提にする(basename自体が正しいかも確認する)"
        )
    return build.read_manifest(manifest_path)


def _previous_release_sources(manifest: build.Manifest) -> dict[str, datetime.date]:
    """前リリースのmanifest.sourcesを`{source_id: 取得日}`にパースする。

    **Ruling B31修正ラウンド3(項目1)**: carry-over判定
    (`_carry_over_source_date`/`_previous_date_if_unchanged`)が「前リリース
    時点で各ソースが何の日付だったか」を知る手段を、`lake.latest_before`に
    よる探索(`previous_release`が日付であることに依存し、しかも探索である
    こと自体がレイクへの新規取得で答えが変わる不安定性を持つ)から、前リリース
    自身が実際に使った値をmanifest.sourcesから直接読み取る方式に変える。
    """
    parsed: dict[str, datetime.date] = {}
    for source_id, value in manifest.sources.items():
        try:
            parsed[source_id] = datetime.date.fromisoformat(value)
        except ValueError as e:
            raise ValueError(
                f"前リリース({manifest.release})のmanifest.sourcesの"
                f"'{source_id}'の値が日付として読めない: {value!r}"
            ) from e
    return parsed


def _previous_release_kg_nq_path(previous_release: str, manifest: build.Manifest) -> Path:
    """前リリースのkg.nqのパスを返す。**kg.nqのsha256をmanifestと照合する**

    (Task 10修正ラウンド1。Ruling B26)。manifest.json自体の存在確認は
    呼び出し側が`_previous_release_manifest`で既に行っている前提——ここでは
    manifestを受け取り、kg.nq本体の実在と完全性だけを見る。

    manifestの`nquads_sha256`が記録されていれば(manifest_version>=3)、
    実際のkg.nqのsha256と照合する。**内容の照合が無いと、保管中に
    書き換えられたkg.nqを黙って受理してしまう**(要修正1の実測[b]。
    B22/F-3が禁じた全角13桁の法人番号を前リリースのkg.nqに書き込んでも
    ゲートを素通りする実測を確認済み)。旧形式のmanifest(`nquads_sha256`が
    無い)は照合できないため、同じ「既定は止まる側」で拒否する。

    この検査は、呼び出し側が`previous_release`を渡した時点での「前リリースが
    実在し、出荷された」という明示の主張の検査であり、carry-over候補が
    結果的に1件も無い呼び出しでも行う(既存の設計方針を維持——黙って
    据え置きを諦めるのではなく矛盾として止める)。
    """
    release_dir = Path(get_settings().artifact_dir) / previous_release
    kg_nq_path = release_dir / "kg.nq"
    if not kg_nq_path.exists():
        raise FileNotFoundError(
            f"前リリース({previous_release})の成果物が見つからない: "
            f"{kg_nq_path}。previous_release を渡す呼び出しは、そのリリースの"
            "kg.nqが実在することを前提にする"
        )
    if manifest.nquads_sha256 is None:
        raise ValueError(
            f"前リリース({previous_release})のmanifest.jsonに"
            "kg.nqのsha256が記録されていない(manifest_versionが3未満の旧形式)。"
            " 完全性を照合できないリリースをcarry-overの供給元にはできない。"
            " scripts/build.sh で再ビルドする"
        )
    actual_sha256 = build.file_sha256(kg_nq_path)
    if actual_sha256 != manifest.nquads_sha256:
        raise ValueError(
            f"前リリース({previous_release})のkg.nqがmanifestの"
            f"sha256と一致しない(manifest={manifest.nquads_sha256} "
            f"actual={actual_sha256})。保管中に壊れたか書き換えられた疑いがある。"
            " carry-overの供給元には使えない"
        )
    return kg_nq_path


def _validate_carried_graphs(
    graphs: dict[str, Graph], shapes_dir: Path
) -> tuple[dict[str, Graph], list[validate.ValidationResult]]:
    """据え置き候補のグラフを`clean`へ合流させる前にSHACLで再検証する

    (Task 10修正ラウンド1。Ruling B26(b))。**carry-overは「再生成の省略」で
    あって「検証の省略」ではない** — §6.3/§6.4の「検証を通った成果物だけが
    公開される」は据え置き分にも掛かる。manifestのsha256照合(tier 1。
    `_previous_release_kg_nq_path`)は「前リリース全体が出荷時の内容から
    変わっていないか」しか見ないため、(a) 前リリースが出荷された**時点で
    既に**壊れていた場合(スキーマ進化等でハッシュだけでは検出できない
    劣化の代理)や、(b) 現行のSHACLシェイプが前リリース当時より厳しくなった
    場合を検出できない。SHACL再検証はこの独立の防御を担う。

    不合格のグラフは戻り値の辞書から除く——呼び出し側(`run()`)は「前リリース
    にそのグラフが無かった」場合と同じ経路(黙って据え置きを諦め、通常どおり
    再生成する)で扱う。**再生成された内容は必ず主ゲート(`validate_dataset`→
    `enforce_release_gate`)を通るので、このフォールバックが検証省略になる
    経路は無い。**

    2番目の戻り値(`ValidationResult`一覧。合否を問わず全候補分)は、
    呼び出し側が`graphs_validated`/`graphs_quarantined`に合算するために
    ある(task-10-review.md観察4: 据え置きグラフはvalidate_datasetを通らない
    ためgraphs_validatedに数えられないがgraphsには載る、というズレの解消)。
    **合格した候補だけを合算する**(不合格分は「規制の失敗」ではなく
    「据え置きを諦めて正常に再生成した」という別の結末になるため、
    `enforce_release_gate`が見るgraphs_quarantinedには混ぜない——呼び出し側が
    合算する際の判断)。

    `_extract_graphs_from_kg_nq`が返す辞書をそのまま受け取るだけで、抽出
    そのもの(R19/R21を守る行単位ストリーム)は変えない——ここで検証する
    グラフは常に小さい(houjin-bangou/egov-law/rs-systemの縦スライス。
    houjin-bangou-allはwantedに入り得ない)。
    """
    if not graphs:
        return graphs, []
    probe = Dataset(default_union=True)
    for uri, g in graphs.items():
        target = probe.graph(URIRef(uri))
        for triple in g:
            target.add(triple)
    results = validate.validate_dataset(probe, shapes_dir)
    failing = {r.graph_uri for r in results if not r.conforms}
    for uri in failing:
        print(
            f"警告: 前リリースの据え置き候補グラフ {uri} がSHACL再検証に"
            "失敗した。carry-overを諦めて再生成する(Ruling B26)"
        )
    passing = {uri: g for uri, g in graphs.items() if uri not in failing}
    return passing, results


def _split_nquads_line_lenient(line: str) -> tuple[str, str] | None:
    """1行のN-Quadsを`(N-Triples本体, グラフURI文字列(角括弧を外した生の値))`に分ける。

    `validate._split_nquads_line`と同じ論証(グラフ項はIRIで生の空白を
    含まないため、末尾から`rsplit(" ", 2)`で安全に切り出せる)を使うが、
    **想定外の行(空行・終端が`.`でない行)では例外にせず`None`を返す**。
    `validate._split_nquads_line`は「stream_emit_organizations以外が書いた
    ファイルの疑いがある」という前提の逸脱を例外にする設計だが、この関数は
    kg.nq全体(`emit.write_nquads`のrdflibシリアライザ出力+
    `stream_emit_organizations`の手書き出力が**同じファイルに混在する**
    ——`run()`のhoujin-bangou-all追記処理参照)を、対象行だけを拾う
    ための走査に使うので、想定外の行(ファイル末尾の空行など。rdflibの
    `NQuadsSerializer`は末尾に空行を1つ書く)は無視して先に進めばよい。
    """
    body = line.rstrip("\n").rstrip("\r")
    if not body.strip():
        return None
    try:
        nt_body, graph_term, dot = body.rsplit(" ", 2)
    except ValueError:
        return None
    if dot != ".":
        return None
    graph_uri_str = graph_term[1:-1] if graph_term.startswith("<") else graph_term
    return nt_body, graph_uri_str


def _extract_graphs_from_kg_nq(path: Path, wanted: set[str]) -> dict[str, Graph]:
    """`path`(前リリースのkg.nq)から、`wanted`に含まれるグラフURIの内容だけを

    1回のストリーム走査で取り出す。**ファイル全体をrdflibの`Dataset`に
    ロードしない。** RS入りの前リリースのkg.nqには、houjin-bangou-allの
    約3,500万行が末尾に追記されている(`run()`の`include_all_corporations`
    処理を参照)。それを`Dataset.parse()`で丸ごと読むと、rdflibが全法人
    規模のterm/tripleオブジェクトをメモリに構築してしまい、
    stream_emit.py/validate.pyのモジュールdocstringが明示的に禁じている
    規模のメモリ使用になる(R19/R21)。carry-over候補は縦スライスグラフ
    (houjin-bangou/egov-law/rs-system)最大3件なので、`wanted`は常に小さく、
    蓄積される行数もそれらのグラフの実サイズに収まる(houjin-bangou-allの
    グラフURIは`wanted`に入り得ない——`run()`のcarry-over対象は
    `_GRAPH_DEPENDENCIES`の3ソースのみで、houjin-bangou-allはそこに含まれない)。

    戻り値に無いURIは「前リリースに存在しない(隔離されていた等)」を意味する。
    **呼び出し側はこれを「据え置きを諦めて通常どおり再生成する」契機にする**
    (黙って空のグラフを引き継がない。task-10-brief.md「踏みやすい欠陥の型」2番)。
    """
    buffers: dict[str, list[str]] = {w: [] for w in wanted}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            parsed = _split_nquads_line_lenient(line)
            if parsed is None:
                continue
            nt_body, graph_uri_str = parsed
            buf = buffers.get(graph_uri_str)
            if buf is not None:
                buf.append(nt_body + " .\n")
    graphs: dict[str, Graph] = {}
    for uri, lines in buffers.items():
        if not lines:
            continue
        g = Graph()
        g.parse(data="".join(lines), format="nt")
        graphs[uri] = g
    return graphs


def _append_carried_graph(
    clean: Dataset,
    carried_over: list[str],
    *,
    source_id: str,
    graph_uri_str: str,
    date: datetime.date,
    sha256: str | Iterable[str] | None,
    graph: Graph,
    base_uri: str,
) -> None:
    """据え置きグラフ(前リリースからそのまま引き継ぐグラフ)を`clean`に合流させる。

    **`clean`(SHACL検証後)に足す — `ds`(検証前)ではない。** このグラフの
    内容は前リリースで既にSHACL検証を通っている、かつバイト単位で不変で
    あることが確定しているため、同じ検証をもう一度やり直す必要が無い。
    これが「グラフ再生成をスキップする」carry-overの実体である
    (advisorレビュー指摘: `ds`に足すとcheck_reference_integrityより前の
    SHACL検証を再度受けるだけで、参照整合ゲートに型情報を渡す目的は
    `clean`に足すだけで十分に果たせる)。
    """
    target = clean.graph(URIRef(graph_uri_str))
    for triple in graph:
        target.add(triple)
    meta = clean.graph(URIRef(f"{base_uri}/graph/provenance"))
    for triple in provenance_graph(graph_uri_str, source_id, date, sha256=sha256):
        meta.add(triple)
    carried_over.append(graph_uri_str)


def _rs_group_paths(fetched_on: datetime.date) -> dict[str, Path]:
    """指定日のrs-systemスナップショット群を、ファイル名からグループキーへ逆引きする。

    **年(`{year}`)をファイル名から推測しない**(rs-systemの`fetched_on`は
    「取得した日」であり、ファイル名に埋め込まれた事業年度とは無関係の
    概念 — advisorレビュー指摘)。`rs_system.RS_GROUP_FILENAMES`のテンプレート
    と文字列としてパターン照合するだけで、年の値そのものは使わない。
    """
    snapshots = [s for s in lake.list_snapshots("rs-system") if s.fetched_on == fetched_on]
    if not snapshots:
        raise FileNotFoundError(
            f"rs-systemのスナップショットが無い(取得日 {fetched_on.isoformat()})。"
            " 先にコネクタで取得する"
        )
    paths: dict[str, Path] = {}
    for snap in snapshots:
        stem = snap.path.name.removesuffix(".zip")
        for group, template in rs_system.RS_GROUP_FILENAMES.items():
            if group in paths:
                continue
            prefix, marker, suffix = template.partition("{year}")
            if not marker:
                continue  # テンプレートに{year}が無い(実データには存在しない形)
            if not (stem.startswith(prefix) and stem.endswith(suffix)):
                continue
            year_part = stem[len(prefix): len(stem) - len(suffix)]
            if year_part.isdigit():
                paths[group] = snap.path
                break
    missing = [g for g in rs_mod.REQUIRED_GROUPS if g not in paths]
    if missing:
        raise FileNotFoundError(
            f"rs-systemの必須ファイルが無い(取得日 {fetched_on.isoformat()}): {missing}。"
            f" 検出したファイル: {sorted(s.path.name for s in snapshots)}"
        )
    return paths


def _all_corporations_membership_test(
    base_uri: str, houjin_bangou_set: set[int]
) -> Callable[[URIRef], bool]:
    """`houjin_bangou_set`(全法人ストリームが実際に認識した法人番号の集合)に

    対する`org:Organization`のmembership_test(裁定B21)。org URIから法人
    番号部分を取り出して集合に照会する — houjin-bangou-allグラフの実データ
    (581万件規模のURI文字列)をそのまま保持するとメモリが破綻するため、
    int化した法人番号の集合だけを持ち、判定のたびにURIから逆算する
    (`stream_emit.dedup_organizations`の`stats.houjin_bangou_seen`と同じ
    「int化して軽量に保つ」考え方)。
    """
    prefix = f"{base_uri}/id/org/"

    def _test(uri: URIRef) -> bool:
        s = str(uri)
        if not s.startswith(prefix):
            return False
        suffix = s[len(prefix):]
        return suffix.isdigit() and int(suffix) in houjin_bangou_set

    return _test


def _houjin_bangou_exists_test(houjin_bangou_set: set[int]) -> Callable[[str], bool]:
    """`houjin_bangou_set`に対する、RS支出先の生の法人番号文字列版

    membership_test(Task 10修正ラウンド1。Ruling B27)。
    `_all_corporations_membership_test`と対になるが、対象がorg URIではなく
    `rs.ExpenditureLine.recipient_houjin_bangou`(13桁の生文字列)であるため
    別関数にする——`rs.build_projects`の`houjin_bangou_exists`引数にそのまま渡す。
    """

    def _test(value: str) -> bool:
        return value.isdigit() and int(value) in houjin_bangou_set

    return _test


def _expenditure_category_mismatches(clean: Dataset) -> list[str]:
    """D-2裁定: `budget:recipientMatchCategory`(新。emit時にパイプライン自身の

    判定をそのまま書いたもの)と、旧クエリ(recipient/payeeLabel/
    UnresolvedReferenceの有無からOPTIONALで推論する。
    `legacy-cq06-optional-inference.rq`)が、同じ`clean`(=kg.nq)に対して
    同じ(project, category)ごとの件数を返すことを突き合わせる。

    **裁定B54(report_graph_mismatches)と同じ思想。** 明示した値を明示した値
    自身で検査すると循環検証になるため、独立した推論経路(旧クエリ)を
    オラクルにする。旧クエリは73,919件相当の入力では149.875秒かかったが、
    ビルド時の検査としては許容される(実行時のcq06はもう新クエリしか使わない)。

    返り値が空でなければ`report_graph_mismatches`に合流させ、
    `enforce_release_gate`が同じゲートで止める。
    """
    new_query = _CQ06_NEW_QUERY_PATH.read_text(encoding="utf-8")
    legacy_query = _CQ06_LEGACY_QUERY_PATH.read_text(encoding="utf-8")

    def _counts(query: str) -> dict[tuple[str, str], int]:
        # **`row.count`ではなくタプル分解で読む。** SELECTの変数名`count`は
        # rdflibのResultRow(tupleのサブクラス)が既に持つメソッド名
        # `count()`と衝突し、`row.count`は変数の値ではなく組み込みメソッドを
        # 返してしまう(実測)。SELECT句の並び順(?project ?category ?count)
        # に依存するタプル分解にすれば衝突しない
        return {
            (str(project), str(category)): int(count)
            for project, category, count in clean.query(query)
        }

    new_counts = _counts(new_query)
    legacy_counts = _counts(legacy_query)

    mismatches: list[str] = []
    for key in sorted(set(new_counts) | set(legacy_counts)):
        new_count = new_counts.get(key, 0)
        legacy_count = legacy_counts.get(key, 0)
        if new_count != legacy_count:
            project, category = key
            mismatches.append(
                f"budget:recipientMatchCategoryが{project}の{category}を"
                f"{new_count}件と報告しているが、旧クエリ(OPTIONAL推論)では"
                f"{legacy_count}件(cq06の新旧クエリが食い違っている)"
            )
    return mismatches


def run(
    fetched_on: Mapping[str, datetime.date],
    out_dir: Path,
    *,
    include_all_corporations: bool = False,
    corporations_scope: Literal["all", "payees"] = "all",
    previous_release: str | None = None,
) -> PipelineReport:
    """ソースIDごとの「いつ時点か」を受け取ってKGを1本作る。

    **単一の取得日を全ソースに仮定しない。** 設計書§6.4の更新頻度表は
    monthly/annual/ondemand とソースごとに異なるため、単一日付の仮定は
    Phase 1(e-Gov 月次 / 予算 年次)で必ず破綻する。

    `include_all_corporations`(Task 8。`--include-all-corporations`相当の
    フラグ): 指定すると、法人(国の機関だけでなく民間企業も含む)を
    `corporations_scope`が決める範囲で別グラフとしてkg.nqに追記する。
    **既存の国の機関グラフ(848件規模の縦スライス)は変えない**(task-8-brief.md)。
    既定はFalse(触らない) — この規模のストリーミング投入・バッチ検証は
    コストが軽くないため、必要なリリース(RS/支出データを含むもの)でだけ
    明示的に有効にする。

    `corporations_scope`(Ruling B30。Task 11修正ラウンド。実測: progress.md
    「発見7の定量的裏付け」「§6.3の8GiB判定」): `include_all_corporations=True`
    のときにどの範囲の法人を対象にするか。
    - `"all"`(既定): 全法人(約581万件)を`graph/houjin-bangou-all/{取得日}`
      に書く。TDB2実サイズ**13.8GiB**(§6.3の8GiB上限を超える)・構築17分16秒。
      能力としては維持する(サーバーレス以外の構成なら選べる)。
    - `"payees"`: budget:recipientの参照先として**実際に登場する法人番号**
      (rs-systemの生データのdistinct recipient_houjin_bangou。全法人の0.33%)
      に絞り、`graph/houjin-bangou-payees/{取得日}`に書く。TDB2実サイズ
      **429MiB**(修正ラウンド2で実測。旧「232MiB」は別の見積り〔選択肢A、
      未使用〕からの混入だった——docs/measurements-phase1.md参照)・
      構築6.3秒。Phase 1のCQ1〜10はどれも支出先以外の法人を
      参照しないため、消費者のいない581万件を積まない(B-1/B-2と同じ原則)。
      **`"rs-system"`が`fetched_on`に無ければ使えない**(絞り込む対象の集合が
      rs-systemのデータから決まるため)。既定にはしない(全法人モードを
      捨てないため、明示のフラグで選ぶ——fix-brief指示)。

    **`fetched_on`に`rs-system`を含めるなら`include_all_corporations=True`が
    必須**(裁定B17懸念2/B18。task-7-report.md)。`budget:recipient`が指す
    支出先の多くは民間企業で、848件規模の国の機関グラフには存在しない。
    法人グラフ(all/payeesのいずれか)を投入しないと参照整合ゲートが必ず
    違反で止まる — それ自体はゲートが正しく機能している証拠だが、「意図せず
    RSだけを結線してゲートに阻まれる」を避けるため、ここで先に明示的に
    エラーにする(黙って通さない)。

    `previous_release`(Task 10。更新の一巡): **前リリースの識別子
    (成果物ディレクトリのbasename。Ruling B31)**を渡すと、ソースの内容が
    前リリース時点からバイト単位で不変なグラフについては再生成(emit+SHACL
    検証)をスキップし、前リリースのグラフをそのまま`clean`(検証後の
    Dataset)へ引き継ぐ(carry-over)。**依存関係を考慮する**: houjin-bangou
    自体が不変でも、そのグラフに依存するegov-law/rs-systemのグラフは、
    依存元(houjin-bangou・ministry-codes・egov-law)のいずれかが変化して
    いれば据え置かない(`_GRAPH_DEPENDENCIES`参照)。既定は`None`
    (=carry-over を一切使わない。既存の全呼び出し元と後方互換)。
    **houjin-bangou-all/houjin-bangou-payeesはcarry-overの対象外**
    (Task 10レビュー観察。`_GRAPH_DEPENDENCIES`に無い——既知の繰り越し課題で
    あり、このリリースが法人グラフを要求すれば毎回再計算する)。

    **Ruling B31修正ラウンド3(項目1。B31の部分適用の解消)**: 以前は
    `previous_release`が`datetime.date`型のみで、ISO日付形式の
    basenameしか前リリースとして参照できなかった。B31が「リリースの
    同一性=成果物ディレクトリのbasename」に決めた以上、参照側がまだ日付
    前提のままでは、区別できる名前(`2026-08-26b`等)を付けても
    carry-overには使えない「部分適用」になる。**このリリースの各ソースが
    実際に何の日付だったかは、この文字列を日付として解釈するのではなく、
    前リリース自身のmanifest.sourcesから読む**(`_previous_release_sources`)
    ——探索(`lake.latest_before`)に頼らないぶん、後から取得したスナップ
    ショットで判定結果が変わる不安定性も同時に解消する
    (`_previous_date_if_unchanged`のdocstring参照)。
    """
    settings = get_settings()
    if not fetched_on:
        raise ValueError(
            "取得日が1件も渡されていない。例: {'houjin-bangou': date(2026, 8, 1)}"
        )
    if "egov-law" in fetched_on and "egov-law-data" not in fetched_on:
        raise ValueError(
            "egov-law を含むリリースは egov-law-data も必須である(C-3)。"
            "law:jurisdiction が旧省庁名をAbolishedGovernmentOrganへ解決する際に"
            "ministry_succession(412CO0000000315の対応表)が必要であり、無いと"
            "全て従来通りOLD_MINISTRYへ黙って後退する——それ自体は動作するが、"
            "意図せず後退したことに気づけない。egov-law-data を明示的に含めるか、"
            "先に `uv run python -m jgkg.fetch --law-id "
            f"{succession_mod.SUCCESSION_LAW_ID}` を実行する"
        )
    if "rs-system" in fetched_on and not include_all_corporations:
        raise ValueError(
            "rs-system を含むリリースは include_all_corporations=True が必須である"
            "(裁定B17懸念2/B18)。budget:recipient が指す支出先の多くは民間企業"
            "であり、848件規模の国の機関グラフには存在しない。全法人グラフを"
            "投入しないと参照整合ゲートが必ず違反で止まる。意図的にrs-systemを"
            "含めるなら include_all_corporations=True を明示する"
        )
    if corporations_scope == "payees":
        if not include_all_corporations:
            raise ValueError(
                "corporations_scope='payees' は include_all_corporations=True が"
                "必須である(Ruling B30)。法人グラフ自体を作らないなら範囲を"
                "選ぶ意味が無い——タイプミスで絞り込みだけが指定され、法人グラフが"
                "一切無いリリースが黙って成立することを避ける"
            )
        if "rs-system" not in fetched_on:
            raise ValueError(
                "corporations_scope='payees' は rs-system をこのリリースに含む"
                "ことが必須である(Ruling B30)。支出先として登場する法人番号の"
                "集合はrs-systemの生データから決まるため、rs-systemが無いと"
                "絞り込む対象そのものが定義できない"
            )

    houjin_date = _source_date("houjin-bangou", fetched_on)
    ministry_date = _source_date("ministry-codes", fetched_on)

    # ファイルパスを渡してストリームで解析する。bytes で読むと実データ(約1GB)で
    # メモリが破綻する(§Task 6 の説明を参照)
    snapshot_path = lake.path_of("houjin-bangou", houjin_date, houjin_bangou.FILENAME)
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"スナップショットが無い: {snapshot_path}。先にコネクタで取得する"
        )
    # **1パスで「全件数」と「国の機関のみのリスト」を分離する。**
    # 全法人(約500万件)を list() すると pydantic オブジェクトで数GB、さらに emit が
    # rdflib に 3000万トリプルを載せるため破綻する。Phase 0 の目的は基盤の確立であり、
    # 任意の法人が必要になるのは Phase 1 の縦スライス(支出先法人)。設計書§6.2.3の
    # 「規模の問題は分割で対処し、1つを大きくするな」に従う。
    # 非空行数と取り込み数の両方を数えるのは、破損や欠落を検知するため(§11.1の観測性)
    #
    # **Task 10: houjin-bangou自身のグラフが据え置き対象でも、この解析は
    # 省略しない。** orgs はministry-codes/egov-law/rs-systemの解決にも
    # 使われるため、自グラフの据え置きとは独立に常に必要
    total_organizations = 0
    orgs: list[org_mod.Organization] = []
    stats = org_mod.ParseStats()
    for o in org_mod.parse_source(snapshot_path, stats=stats):
        total_organizations += 1
        if o.is_government_organ:
            orgs.append(o)

    # 棄却があれば黙って進まない。レポートにも出すが、実行ログでも見えるようにする
    if stats.rows_rejected:
        print(
            f"警告: {stats.rows_rejected} 行を取り込まなかった"
            f"(非空行 {stats.rows_seen} / 取り込み {stats.rows_accepted} /"
            f" 列数不足 {stats.rows_short})。{snapshot_path}"
        )

    # **0件を正常終了として返さない。** 列位置が違えば `_cell` は空文字を返し、
    # 法人番号が13桁でない行は黙って捨てられるため、以前は organizations=0 /
    # government_organs=0 で「成功」を報告し、空のKGが exit 0 で出荷された。
    # 列レイアウト自体の検査は org_mod._parse_reader が行う(この手前で例外になる)
    if total_organizations == 0:
        raise ValueError(
            f"スナップショットから1件も解析できなかった: {snapshot_path}。"
            " ファイルが空か、列レイアウトが想定と違う"
        )
    if not orgs:
        raise ValueError(
            f"国の機関(法人種別 {org_mod.GOVERNMENT_ORGAN_KIND})が1件も無い"
            f"(解析した全件数 {total_organizations})。"
            " 法人種別の列位置がずれている疑いがある。Phase 0 の対象は国の機関なので、"
            " 0件のKGを成功として出荷してはならない"
        )

    reference = ministry_mod.load_reference(MINISTRY_REFERENCE)
    ministries, unmatched = ministry_mod.build(orgs, reference)
    # egov-law(jurisdiction解決)・rs-system(ministry解決)の両方が同じ形
    # (dict[name, list[Ministry]])を必要とするため、ここで1回だけ作って共有する
    ministry_reference_by_name = law_mod.to_ministry_reference(ministries)
    # **実際に読んだファイルのハッシュ**を出典に入れる。参照表にはレイクの
    # スナップショットが無いので、内容ハッシュが「どの版を使ったか」の唯一の証拠
    reference_digest = sources.content_digest(MINISTRY_REFERENCE.read_bytes())
    ministry_recorded_on = sources.get_source("ministry-codes").recorded_on

    # 法人番号スナップショットの sha256 はレイクの実メタデータから取る(レビューI1)。
    # `snapshot_path.exists()` はデータ本体の存在しか見ないため、メタデータ
    # (`.meta.json`)自体が欠けている(中断された取得)場合はここで別途落とす。
    # **日付だけで絞らない。** 同じ日付のディレクトリに別ファイルが増えたら、
    # ソート順で先に来た方のsha256を黙って拾ってしまう(sha256の真正性という
    # このタスクの主旨そのものに関わる)。ファイル名も houjin_bangou.FILENAME に
    # 一致させ、実際にパースした対象と紐づけを固定する
    houjin_snapshot = next(
        (
            s
            for s in lake.list_snapshots("houjin-bangou")
            if s.fetched_on == houjin_date and s.path.name == houjin_bangou.FILENAME
        ),
        None,
    )
    if houjin_snapshot is None:
        raise FileNotFoundError(
            f"スナップショットのメタデータが無い: {snapshot_path}.meta.json。"
            " lake.save() がメタデータを書く前に中断された疑いがある(未コミット)"
        )

    # Task 10: 3ソースの据え置き候補日をまとめて先に確定する(いずれも
    # fetched_on/前リリースのmanifest.sourcesだけで判定できるため、
    # egov-law/rs-systemの実ファイル解析より前に決められる——
    # `_carry_over_source_date`は`own_source_id`が`fetched_on`に無ければ
    # `None`を返すので、無条件に呼んでよい)。**前リリースのmanifest読み取り
    # と実在確認はここで1回だけ行う**(advisorレビュー指摘: ソースごとに
    # 前リリースのkg.nqを何度も読むと、RS入りの前リリースでは
    # houjin-bangou-allの約3,500万行を含むため、`rs_carry_date`の判定を
    # 後段(rs-systemブロック内)まで遅らせたまま`Dataset`へ丸ごとパースする
    # 実装はR19/R21に反する規模のメモリを使う。3件の据え置き候補のうち
    # rs-systemだけは後段の「解析そのものを省略する」分岐(後述)がこの値を
    # 直接使うため、その分岐より前に確定させる必要がある)。
    #
    # **Ruling B31修正ラウンド3(項目1)**: `previous_release`(basename)
    # 自体はもう日付ではないため、`previous_sources`(前リリースの
    # manifest.sourcesを日付にパースしたもの)を先に読み、各ソースの
    # 据え置き判定にはそちらを渡す
    previous_manifest: build.Manifest | None = None
    previous_sources: dict[str, datetime.date] | None = None
    if previous_release is not None:
        previous_manifest = _previous_release_manifest(previous_release)
        previous_sources = _previous_release_sources(previous_manifest)

    houjin_carry_date = _carry_over_source_date("houjin-bangou", fetched_on, previous_sources)
    egov_carry_date = _carry_over_source_date("egov-law", fetched_on, previous_sources)
    rs_carry_date = _carry_over_source_date("rs-system", fetched_on, previous_sources)

    carried_graphs: dict[str, Graph] = {}
    # Task 10修正ラウンド1(観察4): 据え置き候補のSHACL再検証結果(合否問わず)。
    # graphs_validated/graphs_quarantinedへの合算に使う(後述)
    carried_validation_results: list[validate.ValidationResult] = []
    if previous_release is not None:
        assert previous_manifest is not None  # 上のブロックで必ず設定済み
        # wanted_urisが空でも存在確認だけは行う(「前リリースが実在する」
        # という呼び出し側の明示の主張は、carry-over候補の有無と無関係)
        previous_kg_path = _previous_release_kg_nq_path(previous_release, previous_manifest)
        wanted_uris: set[str] = set()
        if houjin_carry_date is not None:
            wanted_uris.add(uris.graph_uri("houjin-bangou", houjin_carry_date))
        if egov_carry_date is not None:
            wanted_uris.add(uris.graph_uri("egov-law", egov_carry_date))
        if rs_carry_date is not None:
            wanted_uris.add(uris.graph_uri("rs-system", rs_carry_date))
        if wanted_uris:
            extracted = _extract_graphs_from_kg_nq(previous_kg_path, wanted_uris)
            # Ruling B26(b): clean へ合流させる前にSHACL再検証する
            # (carry-overは再生成の省略であって検証の省略ではない)
            carried_graphs, carried_validation_results = _validate_carried_graphs(
                extracted, SHAPES_DIR
            )

    # Task 10: 前リリースに該当グラフが無ければ(隔離されていた等)、
    # 黙って空にせず据え置きを諦める(task-10-brief.md「踏みやすい欠陥の型」2番)
    carried_houjin_graph: Graph | None = None
    if houjin_carry_date is not None:
        carried_houjin_graph = carried_graphs.get(
            uris.graph_uri("houjin-bangou", houjin_carry_date)
        )
        if carried_houjin_graph is None:
            houjin_carry_date = None

    carried_egov_graph: Graph | None = None
    if egov_carry_date is not None:
        carried_egov_graph = carried_graphs.get(uris.graph_uri("egov-law", egov_carry_date))
        if carried_egov_graph is None:
            egov_carry_date = None

    carried_rs_graph: Graph | None = None
    if rs_carry_date is not None:
        carried_rs_graph = carried_graphs.get(uris.graph_uri("rs-system", rs_carry_date))
        if carried_rs_graph is None:
            rs_carry_date = None

    # =========================================================================
    # Task 10: egov-law結線(任意ソース)。
    #
    # **`egov-law`自身のグラフが据え置き対象でも、この解析は省略しない。**
    # rs-systemの根拠法令解決(basis_law)がlaw_records(law_by_id/by_title)を
    # 必要とするため — houjin-bangouのorgsと同じ理由(egov-lawだけが不変で
    # rs-systemが変化した場合に、rs-system側の解決に必要なデータが欠ける)
    # =========================================================================
    law_records: list[law_mod.LawRecord] = []
    jurisdictions: dict[str, law_mod.JurisdictionResult] = {}
    law_jurisdiction_resolved = 0
    law_jurisdiction_unresolved = 0
    # 4キー全部を0で初期化する(law_mod.UNRESOLVED_REASONSから導出。
    # 0件のまま出すことに意味がある — 上のフィールドのコメント参照)
    law_jurisdiction_unresolved_by_reason: dict[str, int] = {
        reason: 0 for reason in law_mod.UNRESOLVED_REASONS
    }
    law_jurisdiction_extraction_failed = 0
    law_jurisdiction_resolved_abolished = 0
    egov_date: datetime.date | None = None
    egov_snapshot = None

    # =========================================================================
    # C-3: egov-law-data結線。旧省庁名→AbolishedGovernmentOrganの解決
    # (ministry_succession/C-1・C-2)を、egov-lawのjurisdiction分類より
    # 前に済ませる(3a分岐がabolished_ministry_namesを必要とするため)。
    # **carry-overの対象にしない**(58行規模で毎回再計算する前提。
    # ministry-codesと同じ理由。_GRAPH_DEPENDENCIES/_carry_over_source_date
    # 参照)——常にfetched_onにあれば再計算・再emitする
    # =========================================================================
    egov_law_data_date: datetime.date | None = None
    abolished_ministry_records: list[succession_mod.AbolishedMinistryRecord] = []
    abolished_ministry_names: frozenset[str] = frozenset()
    egov_law_data_snapshot = None

    if "egov-law-data" in fetched_on:
        egov_law_data_date = _source_date("egov-law-data", fetched_on)
        law_data_filename = egov_law.law_data_filename(succession_mod.SUCCESSION_LAW_ID)
        egov_law_data_snapshot = next(
            (
                s
                for s in lake.list_snapshots(egov_law.LAW_DATA_SOURCE_ID)
                if s.fetched_on == egov_law_data_date and s.path.name == law_data_filename
            ),
            None,
        )
        if egov_law_data_snapshot is None:
            raise FileNotFoundError(
                f"{succession_mod.SUCCESSION_LAW_ID} のレイクスナップショットが無い"
                f"(取得日 {egov_law_data_date})。先に `uv run python -m jgkg.fetch"
                f" --law-id {succession_mod.SUCCESSION_LAW_ID}` を実行する"
            )
        law_data = json.loads(egov_law_data_snapshot.path.read_bytes())
        extraction = succession_mod.extract_succession_rows(
            law_data["law_full_text"], source_law_id=succession_mod.SUCCESSION_LAW_ID
        )
        old_ministry_names_for_succession = old_ministries.load_old_ministries()
        coverage = succession_mod.resolve_old_ministries(
            extraction.rows, frozenset(old_ministry_names_for_succession)
        )
        # 現存府省・外局等の名称集合はministries(houjin-bangou×ministry-codes.csv
        # の突合が成功した行だけ)を使う——build_abolished_ministriesの
        # houjin_bangou解決と同じ集合を使わないと、分解できても法人番号が
        # 引けない、という食い違いが起きうる
        current_ministry_names = frozenset(m.name for m in ministries)
        successors = succession_mod.resolve_successor_names(
            coverage.resolved, current_ministry_names
        )
        abolition_date = succession_mod.derive_abolition_date(law_data["revision_info"])
        ministry_houjin_bangou_by_name = {m.name: m.houjin_bangou for m in ministries}
        abolished_ministry_records = succession_mod.build_abolished_ministries(
            successors, ministry_houjin_bangou_by_name, abolition_date
        )
        abolished_ministry_names = frozenset(r.name for r in abolished_ministry_records)

    if "egov-law" in fetched_on:
        egov_date = _source_date("egov-law", fetched_on)
        egov_snapshot_path = lake.path_of("egov-law", egov_date, egov_law.FILENAME)
        if not egov_snapshot_path.exists():
            raise FileNotFoundError(
                f"egov-lawのスナップショットが無い: {egov_snapshot_path}。"
                " 先にコネクタで取得する"
            )
        egov_snapshot = next(
            (
                s
                for s in lake.list_snapshots("egov-law")
                if s.fetched_on == egov_date and s.path.name == egov_law.FILENAME
            ),
            None,
        )
        if egov_snapshot is None:
            raise FileNotFoundError(
                f"egov-lawのスナップショットのメタデータが無い: {egov_snapshot_path}.meta.json。"
                " lake.save() がメタデータを書く前に中断された疑いがある(未コミット)"
            )

        old_ministry_names = old_ministries.load_old_ministries()
        for record in law_mod.parse_laws(egov_snapshot_path):
            law_records.append(record)
            jr = law_mod.derive_jurisdiction(
                record, ministry_reference_by_name, old_ministry_names, abolished_ministry_names
            )
            if jr is None or jr is law_mod.EXTRACTION_FAILED:
                if jr is law_mod.EXTRACTION_FAILED:
                    law_jurisdiction_extraction_failed += 1
                continue
            jurisdictions[record.law_id] = jr
            law_jurisdiction_resolved += len(jr.resolved)
            law_jurisdiction_resolved_abolished += len(jr.resolved_abolished)
            law_jurisdiction_unresolved += len(jr.unresolved)
            for ur in jr.unresolved:
                law_jurisdiction_unresolved_by_reason[ur.reason] += 1

    # =========================================================================
    # Ruling B30(Task 11修正ラウンド): rs-systemのファイル位置・sha256は
    # 解決処理(build_projects)より前に確定できる(ファイルシステムの
    # メタデータだけで決まり、他の状態に依存しない)。ここに繰り上げたのは、
    # `corporations_scope=="payees"`のとき、次の法人ストリームブロックが
    # フィルタ対象(支出先として登場する法人番号の集合)を必要とするため。
    #
    # **advisorレビュー指摘(裁定の訂正): carry-over(rs_carry_date is not
    # None)でもこの生データ読み取りは省略しない。** 当初は「carry-over時は
    # payeesスコープを使えない」という制約にする案だったが、それだと2件目の
    # リリース(Task 10懸念2の初通し。rs-systemが不変でcarry-overされる
    # 検証)でpayeesスコープが使えなくなる。フィルタ対象の抽出は
    # `houjin_bangou_exists`(全法人ストリーム側の結果)を必要としない
    # ——`rs.RsRow.expenditures[*].recipient_houjin_bangou`という生の列を
    # 集計するだけであり、「解決処理」ではない。carry-over ⟺ バイト単位で
    # 不変 ⟺ 今回のこの生読み取りが導く集合は、据え置かれるグラフが実際に
    # 張っているbudget:recipientエッジの集合と一致する(正しさはここから
    # 導かれる)。RS本体(~74,000件の支出行)は5.8M件規模の法人マスタとは
    # 桁が違うため、この読み取りを毎回行うコストは小さい。
    # =========================================================================
    rs_date: datetime.date | None = None
    rs_paths: dict[str, Path] | None = None
    rs_snapshot_sha256s: list[str] = []
    # scope=="payees"のときだけ埋める。build_projects呼び出し側(後段)が
    # 存在すれば再利用し、二重にRSファイルを読まない
    rs_rows_prefetched: list[rs_mod.RsRow] | None = None
    rs_parse_stats = rs_mod.RsParseStats()
    # Ruling B30: 支出先として登場する法人番号(int化)の集合。
    # corporations_scope=="all"または"rs-system"が無ければ`None`のまま
    # (=絞り込まない。stream_emit.StreamStats.houjin_bangou_seenと同じ
    # 「None≠空集合」の作法)
    payee_houjin_bangou: set[int] | None = None

    if "rs-system" in fetched_on:
        rs_date = _source_date("rs-system", fetched_on)
        rs_paths = _rs_group_paths(rs_date)
        rs_snapshot_sha256s = [
            s.sha256
            for s in lake.list_snapshots("rs-system")
            if s.fetched_on == rs_date and s.path in rs_paths.values()
        ]
        if corporations_scope == "payees":
            rs_rows_prefetched = list(rs_mod.parse_rs(rs_paths, stats=rs_parse_stats))
            payee_houjin_bangou = {
                int(v)
                for row in rs_rows_prefetched
                for line in row.expenditures
                if (v := line.recipient_houjin_bangou) and v.isdigit()
            }

    # =========================================================================
    # Task 8: 全法人のストリーミング投入(フラグON時のみ)。
    #
    # rdflib の Dataset には載せない(全法人約3,500万トリプル規模はメモリが
    # 破綻する — stream_emit.py モジュールdocstring参照)。国の機関グラフとは
    # 完全に独立した経路で、別ファイルへストリーミングで書き、バッチSHACLで
    # 検証してから**検証を通った場合だけ**kg.nqへ追記する(検証前に本体へ
    # 混ぜない。enforce_release_gate の「既定は止まる側」をここでも守る)。
    #
    # **Task 10修正ラウンド1(Ruling B27): このブロックをrs-system結線より
    # 前に移動した。** rs-systemの支出先解決(`resolve_recipient`)が
    # 「実在しない法人番号」を第5分類として弾くには、全法人ストリームが
    # 実際に認識した法人番号の集合(`stream_stats.houjin_bangou_seen`)が
    # 必要——これはこのブロックの実行が終わるまで確定しない。rs-system
    # 結線は`include_all_corporations=True`が必須(B17懸念2)なので、この
    # ブロックは常にrs-system結線より前に(無条件で)実行される。egov-law
    # 結線(法令解決)・B24(6)の比の分布計算(rs-system結線の結果に依存)との
    # 依存関係は無いため、順序を入れ替えても両者に影響しない。
    # =========================================================================
    corporations_all = 0
    corporations_all_dedup_removed = 0
    corporations_all_quarantined = 0
    all_corporations_graph_uri: str | None = None
    all_corporations_nq_path: Path | None = None
    # Task 10(B21): 全法人ストリームが実際に認識した法人番号の集合。
    # 参照整合ゲートの外部知識(externally_typed)に使う。フラグOFF時は
    # `None`(=この知識が存在しない。空集合`set()`とは意味的に区別する)
    stream_stats: stream_emit.StreamStats | None = None

    if include_all_corporations:
        # Ruling B30: グラフIDそのものが「全法人」と「支出先限定」を区別する
        # (fix-brief指示。manifest・CQの読み手が誤読しないように)
        graph_id = (
            PAYEE_CORPORATIONS_GRAPH_ID if corporations_scope == "payees" else ALL_CORPORATIONS_GRAPH_ID
        )
        all_corporations_graph_uri = uris.graph_uri(graph_id, houjin_date)
        out_dir.mkdir(parents=True, exist_ok=True)
        all_corporations_nq_path = out_dir / f"{graph_id}.nq"

        def _all_corporations_source() -> Iterator[org_mod.Organization]:
            # **ParseStatsを渡さない。** dedup_organizationsはこの関数(source)を
            # 2回呼ぶ(2パス方式。stream_emit.dedup_organizationsのdocstring
            # 参照)。同じParseStatsオブジェクトをここで束縛して2回分蓄積させると、
            # rows_seen等の集計が二重になる(dedup_organizations側が注意している
            # 罠と対になる、呼び出し側の責務)。列レイアウトの妥当性検査
            # (_assert_layout_plausible)はstats無しでも内部で自動的に走るので、
            # 渡さなくても安全装置は落ちない
            #
            # **Ruling B30(payeesスコープ): dedupより前にフィルタする。**
            # `payee_houjin_bangou`は`source()`が呼ばれる時点で既に確定して
            # いる(前段のRS早期パース参照)ので、2回の呼び出しは常に同じ内容を
            # 返す(dedup_organizationsのF-4(b)不変条件を保つ)。ここで絞ると
            # `stream_stats.houjin_bangou_seen`(dedup1パス目の副産物)は
            # 「フィルタ対象のうち実在するもの」になり、B21の
            # externally_typed・B27のhoujin_bangou_existsはどちらも
            # 変更なしで正しく動く(実在確認の対象はいずれもrs-systemの
            # 支出先=フィルタ対象の部分集合だから)
            for o in org_mod.parse_source(snapshot_path):
                if payee_houjin_bangou is not None and int(o.houjin_bangou) not in payee_houjin_bangou:
                    continue
                yield o

        stream_stats = stream_emit.StreamStats()
        deduped = stream_emit.dedup_organizations(_all_corporations_source, stream_stats)
        # newline="\n"を明示する: Windowsの既定テキストモードは書き込み時に
        # \nを\r\nへ変換するため、指定しないとstream_emit_organizationsが
        # 保証する「1行=1トリプル」の物理行がずれ、validate_streamの行単位
        # バッチ分割の前提を壊す
        with all_corporations_nq_path.open("w", encoding="utf-8", newline="\n") as f:
            stream_emit.stream_emit_organizations(
                deduped, all_corporations_graph_uri, f, stats=stream_stats
            )

        batch_results = validate.validate_stream(
            all_corporations_nq_path, SHAPES_DIR, Path(settings.quarantine_dir)
        )
        corporations_all = stream_stats.entities
        corporations_all_dedup_removed = stream_stats.dedup_removed
        failing_batches = [r for r in batch_results if not r.conforms]
        corporations_all_quarantined = len(failing_batches)
        if failing_batches:
            # batch_indexの読み手その1(もう1つは隔離レポートのファイル名)。
            # 581万件規模で「どのバッチが」「何件」落ちたかが分からないと、
            # quarantine_dirを手探りで漁ることになる(B-1/裁定B23)
            total_violations = sum(r.violation_count for r in failing_batches)
            print(
                f"警告: {graph_id}のバッチ検証で"
                f"{corporations_all_quarantined}バッチが不合格"
                f"(違反合計{total_violations}件)。"
                f" バッチ番号: {[r.batch_index for r in failing_batches]}"
                f" 詳細レポート: {[r.report_path for r in failing_batches]}"
            )

    # =========================================================================
    # Task 10: rs-system結線(任意ソース)。
    #
    # **据え置き(carry-over)対象なら、解決処理(build_projects)そのものを
    # 省略する**(houjin-bangou/egov-lawと異なり、rs-systemの解決結果を
    # 必要とする下流の消費者がpipeline内に無いため、省略しても他の処理に
    # 影響しない — これがcarry-overの実際の計算コスト削減になる部分)。
    # **ファイル位置・sha256・(corporations_scope=="payees"時の)生データ
    # 読み取りは既にファイル冒頭(Ruling B30の節)で確定・実行済みなので、
    # ここでは再計算しない**(`rs_date`/`rs_paths`/`rs_snapshot_sha256s`/
    # `rs_carry_date`はすべてこのブロックより前で確定済み)
    # =========================================================================
    budget_projects_all: tuple[rs_mod.BudgetProjectRecord, ...] = ()
    budget_expenditures_all: tuple[rs_mod.ExpenditureRecord, ...] = ()
    budget_unresolved_all: tuple[rs_mod.UnresolvedBudgetReference, ...] = ()
    budget_stats = rs_mod.BuildStats()

    if "rs-system" in fetched_on:
        assert rs_paths is not None  # 前段で"rs-system" in fetched_on 時に必ず設定済み

        if rs_carry_date is None:
            laws_by_id = {r.law_id: r for r in law_records}
            laws_by_title = rs_mod.laws_index_by_title(law_records)
            # B14: 名称正規化による支出先解決(name_index)は導入しない。
            # 実データでの解決件数が0件と確定済み(task-7-report.md:
            # recipients_resolved_by_name=0/56,667)であり、この索引を
            # 構築するには全法人(約581万件)をもう1パス走査する必要がある
            # (build_recipient_name_index)。「計測してから導入する」
            # (裁定B14)を字義通り守り、実測0件のまま追加のコストを払わない
            # という判断(Task 11への申し送り: 将来データでこの前提が崩れたら
            # 再検討する)
            #
            # Task 10修正ラウンド1(Ruling B27): 実在しない法人番号(全法人
            # フラグONでも60件・distinct53件が残ることが確定している)を
            # 第5分類として弾くための実在確認関数を渡す。B21の
            # `_all_corporations_membership_test`と同じ集合
            # (`stream_stats.houjin_bangou_seen`)を再利用する——rs-system結線
            # は`include_all_corporations=True`が必須(B17懸念2)なので、
            # このブロックに到達した時点で`stream_stats`は必ず構築済み。
            # `corporations_all_quarantined == 0`のガードはB21の
            # `externally_typed`構築時と同じ判断(全法人グラフのバッチ検証が
            # 不合格なら、その集合は参照整合ゲートの外部知識としても
            # rs.build_projectsの実在確認としても信用しない)
            #
            # **Ruling B30(payeesスコープ): `stream_stats.houjin_bangou_seen`は
            # 「フィルタ対象のうち実在するもの」に縮小されているが、
            # `rs.build_projects`が実在確認する対象
            # (`recipient_houjin_bangou`)は常にそのフィルタ対象の部分集合な
            # ので、この縮小後の集合でも実在確認の正しさは変わらない**
            # (org-streamブロック・このモジュール冒頭のRuling B30コメント参照)
            houjin_bangou_exists = None
            if (
                stream_stats is not None
                and stream_stats.houjin_bangou_seen is not None
                and corporations_all_quarantined == 0
            ):
                houjin_bangou_exists = _houjin_bangou_exists_test(
                    stream_stats.houjin_bangou_seen
                )
            # Ruling B30: corporations_scope=="payees"のときは、フィルタ対象を
            # 決めるために既にRSファイルを読んでいる(このモジュール冒頭)。
            # **二重に読まない** — 同じ`rs_rows_prefetched`を再利用する。
            # そうでなければ(scope=="all"または法人グラフを作らないリリース)、
            # ここで初めて読む(既存の挙動のまま)
            rs_rows = (
                rs_rows_prefetched
                if rs_rows_prefetched is not None
                else list(rs_mod.parse_rs(rs_paths, stats=rs_parse_stats))
            )
            budget_result = rs_mod.build_projects(
                rs_rows, ministry_reference_by_name, laws_by_id, laws_by_title,
                name_index={}, houjin_bangou_exists=houjin_bangou_exists,
            )
            budget_projects_all = budget_result.projects
            budget_expenditures_all = budget_result.expenditures
            budget_unresolved_all = budget_result.unresolved
            budget_stats = budget_result.stats

    # 裁定B24(6): 「合計≒執行額」の比の分布を観測として計算する(ゲートには
    # 使わない。budget_projects_all/budget_expenditures_allが空(rs-system
    # 未結線・据え置き)ならループは走らず全て既定値0のまま)
    budget_ratio_exact_1_0 = 0
    budget_ratio_exact_2_0 = 0
    budget_ratio_exact_3_0 = 0
    budget_ratio_total_zero = 0
    budget_ratio_other = 0
    budget_ratio_no_denominator = 0
    if budget_projects_all:
        totals_by_project: dict[tuple[str, str], int] = {}
        for exp in budget_expenditures_all:
            key = (exp.fiscal_year, exp.project_id)
            totals_by_project[key] = totals_by_project.get(key, 0) + exp.amount
        for project in budget_projects_all:
            key = (project.fiscal_year, project.project_id)
            total = totals_by_project.get(key, 0)
            denom = project.prior_year_executed_amount
            if denom is None or denom <= 0:
                budget_ratio_no_denominator += 1
            elif total == 0:
                # task-9-report.mdの「Σ[23]==0」と同じ枠。分母>0だが合計が
                # 文字通り0の事業を「その他」に混ぜない(advisor指摘)
                budget_ratio_total_zero += 1
            elif total == denom:
                budget_ratio_exact_1_0 += 1
            elif total == 2 * denom:
                budget_ratio_exact_2_0 += 1
            elif total == 3 * denom:
                budget_ratio_exact_3_0 += 1
            else:
                budget_ratio_other += 1

    ds = Dataset(default_union=True)

    if houjin_carry_date is None:
        _merge(
            ds,
            emit.emit_organizations(
                orgs, "houjin-bangou", houjin_date, sha256=houjin_snapshot.sha256
            ),
        )
    _merge(
        ds,
        emit.emit_ministries(
            ministries,
            unmatched,
            "ministry-codes",
            ministry_date,
            sha256=reference_digest,
            recorded_on=ministry_recorded_on,
        ),
    )
    if "egov-law" in fetched_on and egov_carry_date is None:
        _merge(
            ds,
            emit.emit_laws(
                law_records, jurisdictions, "egov-law", egov_date, sha256=egov_snapshot.sha256
            ),
        )
    # C-3: carry-overの対象にしない(上のコメント参照)。egov-law-dataが
    # fetched_onにあれば常に再emitする
    if "egov-law-data" in fetched_on:
        _merge(
            ds,
            emit.emit_abolished_ministries(
                abolished_ministry_records,
                "egov-law-data",
                egov_law_data_date,
                sha256=egov_law_data_snapshot.sha256,
            ),
        )
    if "rs-system" in fetched_on and rs_carry_date is None:
        _merge(
            ds,
            emit.emit_budget(
                budget_projects_all,
                budget_expenditures_all,
                budget_unresolved_all,
                "rs-system",
                rs_date,
                sha256=rs_snapshot_sha256s,
            ),
        )

    # Task 8: バッチ検証を通った全法人グラフの出典をここで記録する(原則7:
    # 出典を持たない事実をKGに入れない)。**検証に失敗していれば記録しない**
    # — このグラフは実際にはkg.nqへ追記されないので、記録すると「出典だけ
    # 存在するが本体が無い」という嘘になる。「houjin-bangou」と同じ
    # 取得済みスナップショットから作る別グラフなので、source_idは新規登録
    # せず既存の"houjin-bangou"のままにする(同じ一次資料から2つの異なる
    # 粒度のグラフを作っている、という事実をそのまま記録する)。
    #
    # **`ds`に足す(`clean`ではない)。SHACLゲートより前にする(F-5)。**
    # 以前は`passing_dataset`が返した`clean`に後から足していたため、この
    # 出典グラフ自身が一度もSHACL検証を通らずにkg.nqへ出て行っていた
    # (`validate_dataset`は`ds`をこの時点でしか見ないため、後から`clean`
    # に足した内容はゲートの対象に一度も入らない)。`ds`に足せば、他の
    # グラフと同じ扱いで`validate_dataset`→`passing_dataset`を通り、ゲートが
    # 実際に見た内容だけが`clean`に残るという一貫性が保てる(出典グラフは
    # `rdf:type`を持たないため`_assert_shapes_cover`の対象外になり実質的には
    # 素通りするが、その素通りも含めてゲートの通り道に乗せておく)
    if include_all_corporations and corporations_all_quarantined == 0:
        meta = ds.graph(URIRef(f"{settings.base_uri}/graph/provenance"))
        for triple in provenance_graph(
            all_corporations_graph_uri,
            "houjin-bangou",
            houjin_date,
            sha256=houjin_snapshot.sha256,
        ):
            meta.add(triple)

    results = validate.validate_dataset(ds, SHAPES_DIR)
    quarantined = [r for r in results if not r.conforms]
    if quarantined:
        validate.quarantine(ds, results, Path(settings.quarantine_dir))

    clean = validate.passing_dataset(ds, results)

    # Task 10: 据え置き(carry-over)したグラフを`clean`に合流させる。
    # SHACL検証を再び受けさせない(前リリースで既に通っている、かつ
    # バイト単位で不変であることが確定しているため)
    carried_over: list[str] = []
    if houjin_carry_date is not None:
        assert carried_houjin_graph is not None
        _append_carried_graph(
            clean, carried_over,
            source_id="houjin-bangou",
            graph_uri_str=uris.graph_uri("houjin-bangou", houjin_carry_date),
            date=houjin_carry_date,
            sha256=houjin_snapshot.sha256,
            graph=carried_houjin_graph,
            base_uri=settings.base_uri,
        )
    if egov_carry_date is not None:
        assert carried_egov_graph is not None and egov_snapshot is not None
        _append_carried_graph(
            clean, carried_over,
            source_id="egov-law",
            graph_uri_str=uris.graph_uri("egov-law", egov_carry_date),
            date=egov_carry_date,
            sha256=egov_snapshot.sha256,
            graph=carried_egov_graph,
            base_uri=settings.base_uri,
        )
    if rs_carry_date is not None:
        assert carried_rs_graph is not None
        _append_carried_graph(
            clean, carried_over,
            source_id="rs-system",
            graph_uri_str=uris.graph_uri("rs-system", rs_carry_date),
            date=rs_carry_date,
            sha256=rs_snapshot_sha256s,
            graph=carried_rs_graph,
            base_uri=settings.base_uri,
        )

    # Task 10(裁定B21): houjin-bangou-allは`clean`に載らない(rdflibに載る
    # 規模ではないため、意図的に別経路。stream_emit.py/validate.pyの
    # モジュールdocstring参照)。その代わり、実際に投入した法人番号の集合を
    # 「外部知識」として参照整合ゲートに渡す — budget:recipient等が指す
    # 民間企業への参照を、和集合に型情報を実体化させずに検査できるようにする。
    # **除外(Task 8のexclude)ではない**: 除外は「検査しない」ことになり
    # 54.9k件規模の実参照の検査放棄になる(裁定B21)ため、この方式に置き換えた
    externally_typed: dict[URIRef, Callable[[URIRef], bool]] | None = None
    if (
        include_all_corporations
        and corporations_all_quarantined == 0
        and stream_stats is not None
        and stream_stats.houjin_bangou_seen is not None
    ):
        org_organization_class = URIRef(f"{settings.base_uri}/def/org#Organization")
        externally_typed = {
            org_organization_class: _all_corporations_membership_test(
                settings.base_uri, stream_stats.houjin_bangou_seen
            )
        }

    # **隔離を通過した `clean` に対して検査する(`ds` ではない)。** SHACLで
    # 隔離されたグラフへの参照は「壊れて当然」なのでここでも違反として拾って
    # しまうと、原因(SHACL側の隔離)と結果(参照切れ)が両方報告されて
    # ノイズになる。`clean` は`--allow-partial`時に実際に出荷される内容と
    # 一致するので、そこでの参照切れこそがこのゲートが守るべきものである。
    reference_violations = validate.check_reference_integrity(
        clean, SHAPES_DIR, externally_typed=externally_typed
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    emit.write_nquads(clean, out_dir / "kg.nq")

    if include_all_corporations and corporations_all_quarantined == 0:
        # 検証を通った場合だけ、別ファイルに書いたN-QuadsをそのままKg.nqへ
        # 追記する(rdflibのDatasetを経由しない — 全法人規模を一度でも
        # メモリに載せると破綻する、という制約をここでも一貫させる)
        with (
            all_corporations_nq_path.open("r", encoding="utf-8") as src,
            (out_dir / "kg.nq").open("a", encoding="utf-8", newline="\n") as dst,
        ):
            for line in src:
                dst.write(line)
        # O-10: 合格時は中間ファイル(houjin-bangou-all.nqまたは
        # houjin-bangou-payees.nq)を削除する。内容はkg.nqへ追記済みで
        # 二重に持つ理由が無く、全法人スコープ(581万件規模・約1GB)を毎回
        # 残すと成果物ディレクトリが肥大する。**不合格時はここに来ない**ため、
        # 中間ファイルは事実上の隔離物として残る(バッチ単位の違反レポートとは
        # 別に、入力全体を再現できる状態を保つ意味がある)
        all_corporations_nq_path.unlink()

    surviving_graphs = sorted(str(c.identifier) for c in clean.graphs() if len(c) > 0)
    if include_all_corporations and corporations_all_quarantined == 0:
        # `clean`(rdflib Dataset)には載っていないが、kg.nqには実際に
        # 追記されたグラフなので、manifestが渡す一覧に手動で足す
        surviving_graphs = sorted(surviving_graphs + [all_corporations_graph_uri])
    # **成果物に残ったソースだけを sources に載せる。** グラフが隔離されたのに
    # 「このソースはこの日付のデータを含む」と書くと、manifest が嘘をつく
    # (`--allow-partial` で出荷したときに実際に起きる)。落ちたことは
    # quarantined_sources に出して、黙って消さない。
    # **Task 10: 据え置きしたソースは、今回の取得日ではなく引き継いだ元の
    # 日付を載せる**(「実際に入っているもの」原則。同じ理由でI2と同族)
    effective_source_dates: dict[str, datetime.date] = {
        "houjin-bangou": houjin_carry_date if houjin_carry_date is not None else houjin_date,
        "ministry-codes": ministry_date,
    }
    if "egov-law" in fetched_on:
        effective_source_dates["egov-law"] = (
            egov_carry_date if egov_carry_date is not None else egov_date
        )
    if "egov-law-data" in fetched_on:
        # carry-overの対象にしないため、常に今回の取得日そのもの(上の
        # コメント「Task 10: 据え置きしたソースは…」の対象外)
        effective_source_dates["egov-law-data"] = egov_law_data_date
    if "rs-system" in fetched_on:
        effective_source_dates["rs-system"] = (
            rs_carry_date if rs_carry_date is not None else rs_date
        )
    surviving_sources = {
        sid: d.isoformat()
        for sid, d in effective_source_dates.items()
        if uris.graph_uri(sid, d) in surviving_graphs
    }
    quarantined_sources = sorted(set(effective_source_dates) - set(surviving_sources))

    # Task 10修正ラウンド1(要修正2): law_*/budget_*系フィールドの0/None判定。
    # **この時点(関数末尾。carry-over declineのフォールバックが全て解決した
    # 後)で評価しなければならない** — `rs_carry_date`はSHACL再検証
    # (`_validate_carried_graphs`)が不合格と判定した場合にここより前で`None`
    # へ戻される(=解決処理が実際に走る)ため、早い時点で評価すると「解決処理は
    # 実際に走ったのにNoneを報告する」という逆方向の事故になる
    egov_law_ran = "egov-law" in fetched_on
    rs_resolution_ran = "rs-system" in fetched_on and rs_carry_date is None

    # 裁定B54(2026-08-27。PipelineReport.report_graph_mismatchesの
    # docstring参照): law_jurisdiction_resolved_abolishedの主張が、実際に
    # 出力される`clean`(=kg.nq)と食い違わないことを検査する。**導出
    # (レポートの数値をclean自身から計算する形に置き換える)ではなく
    # 突き合わせにした**——houjin-bangou-all/payeesはclean(rdflib
    # Dataset)に載らない設計(裁定B21。全法人規模はメモリに載せられない)
    # のため、レポート全体をclean由来で導出する経路はこの構造と両立しない。
    # carry-overでegov-lawが意図せず据え置かれると、この集計(常に
    # jurisdictionsから独立に計算する)だけが正しい値を報告し、kg.nq自身
    # には反映されないという「レポートが嘘をつく」状態が実際に発生した
    # (C-4のリリース再構築で発見。docs/measurements-phase1.md参照)。
    # 参照整合ゲート(型は合っている)では検出できない(数が食い違うだけ)
    report_graph_mismatches: list[str] = []
    if egov_law_ran:
        law_jurisdiction_pred = URIRef(f"{settings.base_uri}/def/law#jurisdiction")
        abolished_organ_class = URIRef(f"{settings.base_uri}/def/org#AbolishedGovernmentOrgan")
        actual_resolved_abolished = sum(
            1
            for _, _, o in clean.triples((None, law_jurisdiction_pred, None))
            if (o, RDF.type, abolished_organ_class) in clean
        )
        if actual_resolved_abolished != law_jurisdiction_resolved_abolished:
            report_graph_mismatches.append(
                f"law_jurisdiction_resolved_abolished={law_jurisdiction_resolved_abolished}"
                "と報告しているが、kg.nq自身でAbolishedGovernmentOrganを指す"
                f"jurisdictionトリプルは{actual_resolved_abolished}件"
                "(carry-overでegov-lawが意図せず据え置かれた疑いがある)"
            )

    # D-2裁定: budget:recipientMatchCategory(新)とcq06旧クエリ(推論)の
    # 突き合わせ。carry-over時も検査する(carried_overしたrs-systemグラフの
    # 内容そのものを検査するので、egov_law_ranと同じ理由で"rs-system" in
    # fetched_onで判定する——rs_resolution_ranではない。B54が「carry-overで
    # 意図せず据え置かれる」ケースを狙って"in fetched_on"にしたのと同じ理由)
    if "rs-system" in fetched_on:
        report_graph_mismatches.extend(_expenditure_category_mismatches(clean))

    return PipelineReport(
        # リリース名は**成果物ディレクトリのbasename**(Ruling B31)。
        # 以前は`max(fetched_on.values())`(=最も新しいソース取得日)だったが、
        # これは「リリースの同一性」ではなく「ソースの鮮度」であり、同じ日に
        # 複数のリリース(例: 支出先限定リリースAとcarry-over検証用リリースB。
        # どちらもegov-law取得日が同じ)を作るとreleaseフィールドが衝突し、
        # manifest.jsonだけでは区別できなくなる(§6.3の配布契約が嘘をつく)。
        # `--previous-release`は既に成果物ディレクトリのbasenameをキーにして
        # 前リリースを探しており(`_previous_release_kg_nq_path`)、de facto の
        # 同一性は元々basenameだった。ソースごとの鮮度は`sources`欄に残るため、
        # `max(fetched_on.values())`は必要なら`sources`から導出できる
        # (情報は失われない)。
        release=out_dir.name,
        rows_seen=stats.rows_seen,
        rows_rejected=stats.rows_rejected,
        rows_short=stats.rows_short,
        organizations=total_organizations,
        government_organs=len(orgs),
        ministries=len(ministries),
        unmatched_ministries=len(unmatched),
        # Task 10修正ラウンド1(観察4): 合格した据え置き候補もSHACL再検証を
        # 受けているので数える(据え置きグラフはgraphsに載るのに
        # graphs_validatedに数えられない、というズレを解消する)。**不合格の
        # 据え置き候補はgraphs_quarantinedに混ぜない**——「据え置きを諦めて
        # 正常に再生成した」という結末であり、enforce_release_gateが止める
        # べき失敗(このリリースに欠落が生じた)ではない
        graphs_validated=len(results) + sum(
            1 for r in carried_validation_results if r.conforms
        ),
        graphs_quarantined=len(quarantined),
        # Dataset から正確なグラフURIを取る。テキストから推測してはならない
        graphs=surviving_graphs,
        sources=surviving_sources,
        quarantined_sources=quarantined_sources,
        reference_violations=[str(v) for v in reference_violations],
        report_graph_mismatches=report_graph_mismatches,
        corporations_all=corporations_all,
        corporations_all_dedup_removed=corporations_all_dedup_removed,
        corporations_all_quarantined=corporations_all_quarantined,
        corporations_scope=corporations_scope if include_all_corporations else None,
        carried_over=carried_over,
        law_records=len(law_records) if egov_law_ran else None,
        law_jurisdiction_resolved=law_jurisdiction_resolved if egov_law_ran else None,
        law_jurisdiction_resolved_abolished=(
            law_jurisdiction_resolved_abolished if egov_law_ran else None
        ),
        law_jurisdiction_unresolved=law_jurisdiction_unresolved if egov_law_ran else None,
        law_jurisdiction_unresolved_by_reason=(
            law_jurisdiction_unresolved_by_reason if egov_law_ran else None
        ),
        law_jurisdiction_extraction_failed=(
            law_jurisdiction_extraction_failed if egov_law_ran else None
        ),
        budget_projects=len(budget_projects_all) if rs_resolution_ran else None,
        budget_expenditures=len(budget_expenditures_all) if rs_resolution_ran else None,
        budget_expenditures_bundled=(
            budget_stats.expenditures_bundled if rs_resolution_ran else None
        ),
        budget_recipients_sentinel=(
            budget_stats.recipients_sentinel if rs_resolution_ran else None
        ),
        budget_recipients_nonexistent_houjin_bangou=(
            budget_stats.recipients_nonexistent_houjin_bangou if rs_resolution_ran else None
        ),
        budget_recipients_resolved_by_houjin_bangou=(
            budget_stats.recipients_resolved_by_houjin_bangou if rs_resolution_ran else None
        ),
        budget_recipients_resolved_by_name=(
            budget_stats.recipients_resolved_by_name if rs_resolution_ran else None
        ),
        budget_recipients_unresolved=(
            budget_stats.recipients_unresolved if rs_resolution_ran else None
        ),
        budget_ministries_resolved=(
            budget_stats.ministries_resolved if rs_resolution_ran else None
        ),
        budget_ministries_unresolved=(
            budget_stats.ministries_unresolved if rs_resolution_ran else None
        ),
        budget_basis_law_resolved=(
            (
                budget_stats.basis_law_resolved_by_id
                + budget_stats.basis_law_resolved_by_title_raw
                + budget_stats.basis_law_resolved_by_title_stripped
            )
            if rs_resolution_ran else None
        ),
        budget_basis_law_unresolved=(
            budget_stats.basis_law_unresolved if rs_resolution_ran else None
        ),
        budget_ratio_exact_1_0=budget_ratio_exact_1_0 if rs_resolution_ran else None,
        budget_ratio_exact_2_0=budget_ratio_exact_2_0 if rs_resolution_ran else None,
        budget_ratio_exact_3_0=budget_ratio_exact_3_0 if rs_resolution_ran else None,
        budget_ratio_total_zero=budget_ratio_total_zero if rs_resolution_ran else None,
        budget_ratio_other=budget_ratio_other if rs_resolution_ran else None,
        budget_ratio_no_denominator=(
            budget_ratio_no_denominator if rs_resolution_ran else None
        ),
    )


# =============================================================================
# Task 11 / B28: CLI。build.sh から呼ぶ唯一の入口(モジュールdocstring参照)
# =============================================================================

REPORT_NAME = "pipeline-report.json"


def _parse_source(spec: str) -> tuple[str, datetime.date]:
    """`--source houjin-bangou=2026-08-23` の右辺をパースする。

    **未登録のソースIDを黙って受けない**(`sources.get_source`が弾く)。
    タイプミスした`--source houjin-banogu=...`が「そのソースを含めない
    リリース」として静かに成功するのが、このCLIで最も踏みやすい欠陥である。

    **コミット済みの参照表(`local_path`を持つソース。現状ministry-codesのみ)
    に対する日付は拒否する(block-A-review 項目2)。** 以前はここを素通り
    させていた。この関数が返す日付は`fetched_on[source_id]`としてグラフURIと
    `prov:generatedAtTime`(`rdf/provenance.py`)に流れ込むが、`core:recordedOn`
    は別途`sources.get_source(source_id).recorded_on`から取得される
    (`_source_date`参照)ため、`--source ministry-codes=<recorded_onと違う
    日付>`を渡すと1つのグラフが自分自身について矛盾する2つの日付
    (誤ったprov:generatedAtTimeと正しいcore:recordedOn)を主張する状態を
    黙って作れた。A-3以降`prov:generatedAtTime`はCQ8のカットオフの入力にも
    なっているため、誤った日付が黙ってCQ8の答えを狂わせる経路になる。
    `fetch.py:148-157`と同じ判定条件(`local_path is not None`。
    "ministry-codes"という文字列比較にしない——手書きの1要素除外リストに
    しないため。この源の日付は常に`sources.py`の`recorded_on`から決まり、
    呼び出し側が指定する余地は無い)で拒否する。
    """
    source_id, sep, date_str = spec.partition("=")
    if not sep or not source_id or not date_str:
        raise argparse.ArgumentTypeError(
            f"--source の形式が違う: {spec!r}。`<ソースID>=<YYYY-MM-DD>` と書く"
            "(例: --source houjin-bangou=2026-08-23)"
        )
    try:
        source = sources.get_source(source_id)
    except KeyError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if source.local_path is not None:
        raise argparse.ArgumentTypeError(
            f"{source.id!r} には --source で日付を渡せない(コミット済みの参照表。"
            f"{source.local_path} を直接編集し、sources.py の recorded_on を更新する)。"
            "この源の日付は常に sources.py の recorded_on から決まる——誤った日付を"
            "渡すと、そのグラフの prov:generatedAtTime(誤り)と core:recordedOn"
            "(正しい記録日)が矛盾したグラフを作ってしまう"
        )
    try:
        date = datetime.date.fromisoformat(date_str)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--source の日付が ISO 形式でない: {spec!r}({exc})"
        ) from exc
    return source_id, date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="取得済みスナップショットから kg.nq を1本作り、リリースゲートをかける"
    )
    parser.add_argument(
        "--source",
        action="append",
        type=_parse_source,
        metavar="ID=YYYY-MM-DD",
        default=None,
        help="ソースIDとその取得日。**複数回指定できる**"
        "(例: --source houjin-bangou=2026-08-23 --source egov-law=2026-08-24)。"
        " リポジトリにコミットした参照表(ministry-codes)は渡さない"
        " — sources.py の recorded_on が使われる",
    )
    parser.add_argument(
        "--out-dir", type=Path, required=True, help="成果物の出力先(例: data/artifact/2026-08-24)"
    )
    parser.add_argument(
        "--previous-release",
        type=str,
        default=None,
        help="前リリースの識別子(成果物ディレクトリのbasename。例: "
        "2026-08-24、または2026-08-24-payeesのような非ISO形式の名前も可。"
        "Ruling B31修正ラウンド3で日付形式限定を解消した)。渡すと差分検出"
        "(carry-over)が働き、前リリースから不変なグラフは再生成せず引き継ぐ",
    )
    parser.add_argument(
        "--include-all-corporations",
        action="store_true",
        help="法人グラフ(範囲は --corporations-scope で選ぶ)を含める。"
        "**rs-system を含むリリースでは必須**(裁定B17懸念2/B18)",
    )
    parser.add_argument(
        "--corporations-scope",
        choices=["all", "payees"],
        default="all",
        help="--include-all-corporations 指定時にどの範囲の法人を対象にするか"
        "(Ruling B30)。'all'=全法人(約581万件。houjin-bangou-allグラフ。"
        "TDB2実サイズ13.8GiB)。'payees'=budget:recipientの参照先として"
        "実際に登場する法人に限る(houjin-bangou-payeesグラフ。約19,000件・"
        "TDB2実サイズ429MiB。rs-system を含むリリースでのみ指定できる)。既定は'all'"
        "(全法人モードを捨てない。明示のフラグで選ぶ)",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="隔離が起きてもリリースを続ける。**既定は止まる側**(設計書§6.3)",
    )
    args = parser.parse_args(argv)

    if not args.source:
        parser.error(
            "--source を1つ以上渡す(例: --source houjin-bangou=2026-08-23)。"
            " 取得して来るソースの日付は呼び出し側が決める"
        )
    fetched_on: dict[str, datetime.date] = {}
    for source_id, date in args.source:
        if source_id in fetched_on and fetched_on[source_id] != date:
            parser.error(
                f"同じソース {source_id!r} に違う日付が2回渡された"
                f"({fetched_on[source_id].isoformat()} と {date.isoformat()})。"
                " 1リリースにつき1ソース1日付である"
            )
        fetched_on[source_id] = date

    report = run(
        fetched_on,
        args.out_dir,
        include_all_corporations=args.include_all_corporations,
        corporations_scope=args.corporations_scope,
        previous_release=args.previous_release,
    )

    # **レポートはゲートの前に書く。** 隔離で落ちたときに「何が落ちたか」を
    # 人が読めるようにするため(旧build.shが守っていた順序をここに移した)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / REPORT_NAME).write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    print(report.model_dump_json(indent=2))

    enforce_release_gate(report, allow_partial=args.allow_partial)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
