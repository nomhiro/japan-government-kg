"""パイプラインの結線。取得済みスナップショットからN-Quadsまでを1本にする。

各段の件数を PipelineReport として返す。観測性は設計書§11.1の要件。
"""
import datetime
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path

from pydantic import BaseModel
from rdflib import Dataset, Graph, URIRef

from jgkg import lake, sources, uris, validate
from jgkg.config import get_settings
from jgkg.connectors import egov_law, houjin_bangou, rs_system
from jgkg.rdf import emit, stream_emit
from jgkg.rdf.provenance import provenance_graph
from jgkg.transform import law as law_mod
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import old_ministries
from jgkg.transform import organization as org_mod
from jgkg.transform import rs as rs_mod

# 全法人の別グラフ(Task 8)のグラフID部分。「houjin-bangou」と同じ取得済み
# スナップショットから作る別グラフなので、sources.pyに新しいソースを登録する
# 必要はない — 出典(provenance_graph)は"houjin-bangou"のsource_idのまま、
# グラフURIだけをこの名前にする(同じ一次資料から2つの異なる粒度のグラフを
# 作っている、という事実をそのまま記録する)
ALL_CORPORATIONS_GRAPH_ID = "houjin-bangou-all"

MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")
SHAPES_DIR = Path("schema/generated")

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
# =============================================================================
_GRAPH_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "houjin-bangou": ("houjin-bangou",),
    "egov-law": ("houjin-bangou", "ministry-codes", "egov-law"),
    "rs-system": ("houjin-bangou", "ministry-codes", "egov-law", "rs-system"),
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
    # Task 8: `--include-all-corporations`(相当のフラグ)が指定されたときだけ
    # 意味を持つ。フラグ未指定なら3つとも既定値0のまま(全法人ストリームに
    # 触れていないことがそのまま分かる)
    #
    # houjin-bangou-allグラフに実際に書き出したエンティティ数(dedup後)。
    # 「全法人約581万件」の実測値がここに載る(Task 11が単価計算に使う)
    corporations_all: int = 0
    # 法人番号の重複により上流でdedupして弾いた行数。**消したことを黙らない**
    # (stream_emit.StreamStats.dedup_removedがそのまま渡る)
    corporations_all_dedup_removed: int = 0
    # バッチSHACL検証(validate_stream)で不合格だったバッチ数。0でなければ
    # houjin-bangou-allグラフはkg.nqに追記されない(検証前に本体へ混ぜない)。
    # enforce_release_gateがこれも見て止める
    corporations_all_quarantined: int = 0

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
    # =========================================================================
    law_records: int = 0
    law_jurisdiction_resolved: int = 0    # JurisdictionResult.resolved の延べ数
    law_jurisdiction_unresolved: int = 0  # JurisdictionResult.unresolved の延べ数
    # 府省令・規則の形をしているのに名称を抽出できなかった件数
    # (law.EXTRACTION_FAILED。件数を「経路1の欠陥」と読むと過大評価になる
    # ことに注意 — 皇室令など非府省令の法形式もここに拾われる。task-4-report.md
    # Task 11への申し送り参照)
    law_jurisdiction_extraction_failed: int = 0

    # =========================================================================
    # Task 10: rs-system結線。rs.BuildStatsを結線後に初めてPipelineReportへ
    # 搭載する(rs.py docstring「PipelineReportに載せることは結線を担うタスク
    # の作業」)。**rs-systemのグラフが据え置き(carried_over)された場合、
    # このセクションは全て既定値0のまま**(据え置きは解決処理そのものを
    # 走らせないため。据え置き元の値は前リリースのreportを参照する —
    # corporations_all系がフラグOFF時に0のままである既存の作法と同じ形)
    # =========================================================================
    budget_projects: int = 0
    budget_expenditures: int = 0
    budget_expenditures_bundled: int = 0
    budget_recipients_sentinel: int = 0
    budget_recipients_resolved_by_houjin_bangou: int = 0
    budget_recipients_resolved_by_name: int = 0
    budget_recipients_unresolved: int = 0
    budget_ministries_resolved: int = 0
    budget_ministries_unresolved: int = 0
    budget_basis_law_resolved: int = 0
    budget_basis_law_unresolved: int = 0

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
    # (advisor2回目レビュー指摘)
    budget_ratio_exact_1_0: int = 0
    budget_ratio_exact_2_0: int = 0
    budget_ratio_exact_3_0: int = 0
    budget_ratio_total_zero: int = 0
    budget_ratio_other: int = 0
    budget_ratio_no_denominator: int = 0


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
    source_id: str, current_date: datetime.date, previous_release: datetime.date
) -> datetime.date | None:
    """`source_id`が前リリース時点からバイト単位で不変なら、その前リリース

    時点でのfetched_on(引き継ぐべきグラフの日付)を返す。変化していれば
    (または前リリース時点にスナップショットが無ければ)`None`。

    rs-systemは事業年度ごと15本の関連ファイルに分かれるため、単一の
    sha256では比較できない — ファイル名の集合ごと突き合わせる(1本でも
    増減・変化していれば不変ではない)。
    """
    if source_id == "rs-system":
        current_digests = _rs_system_file_digests(current_date)
        prev_snapshot = lake.latest_before(source_id, previous_release)
        if prev_snapshot is None:
            return None
        prev_digests = _rs_system_file_digests(prev_snapshot.fetched_on)
        return prev_snapshot.fetched_on if prev_digests == current_digests else None

    prev_snapshot = lake.latest_before(source_id, previous_release)
    if prev_snapshot is None:
        return None
    current_snapshot = next(
        (s for s in lake.list_snapshots(source_id) if s.fetched_on == current_date),
        None,
    )
    if current_snapshot is None or current_snapshot.sha256 != prev_snapshot.sha256:
        return None
    return prev_snapshot.fetched_on


def _carry_over_source_date(
    own_source_id: str,
    fetched_on: Mapping[str, datetime.date],
    previous_release: datetime.date | None,
) -> datetime.date | None:
    """`own_source_id`のグラフを据え置ける場合、その前リリース時点の

    fetched_onを返す。**依存元(`_GRAPH_DEPENDENCIES`)のいずれか1つでも
    変化していれば`None`**(このグラフ自身は再生成する) — `own_source_id`
    自身のバイト列が不変でも、egov-law/rs-systemはhoujin-bangou由来の
    ministriesの解決結果に依存するため、自ソースだけを見る判定は不健全
    (このモジュールのコメント「Task 10: 更新の一巡」参照)。
    """
    if previous_release is None or own_source_id not in fetched_on:
        return None
    result: datetime.date | None = None
    for dep in _GRAPH_DEPENDENCIES[own_source_id]:
        if dep == "ministry-codes":
            continue  # 常に再計算する前提。依存判定には数えない
        dep_date = fetched_on.get(dep)
        if dep_date is None:
            # 依存元ソースが今回の実行対象に含まれていない。保守的に
            # 「不変と確認できない」として据え置きを諦める
            return None
        prev_date = _previous_date_if_unchanged(dep, dep_date, previous_release)
        if prev_date is None:
            return None
        if dep == own_source_id:
            result = prev_date
    return result


def _previous_release_kg_nq_path(previous_release: datetime.date) -> Path:
    """前リリースのkg.nqのパスを返す。**存在確認のみ行い、内容は読まない。**

    存在しなければ例外にする(呼び出し側が`previous_release`を渡した
    時点で「前リリースが存在する」という明示の主張になるため、黙って
    据え置きを諦めるのではなく矛盾として止める) — この確認は、carry-over
    候補が結果的に1件も無い呼び出しでも行う(「前リリースが実在する」と
    いう主張そのものは、carry-overが実際に起きるかどうかとは独立している)。
    """
    path = Path(get_settings().artifact_dir) / previous_release.isoformat() / "kg.nq"
    if not path.exists():
        raise FileNotFoundError(
            f"前リリース({previous_release.isoformat()})の成果物が見つからない: {path}。"
            " previous_release を渡す呼び出しは、そのリリースのkg.nqが"
            "実在することを前提にする"
        )
    return path


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


def run(
    fetched_on: Mapping[str, datetime.date],
    out_dir: Path,
    *,
    include_all_corporations: bool = False,
    previous_release: datetime.date | None = None,
) -> PipelineReport:
    """ソースIDごとの「いつ時点か」を受け取ってKGを1本作る。

    **単一の取得日を全ソースに仮定しない。** 設計書§6.4の更新頻度表は
    monthly/annual/ondemand とソースごとに異なるため、単一日付の仮定は
    Phase 1(e-Gov 月次 / 予算 年次)で必ず破綻する。

    `include_all_corporations`(Task 8。`--include-all-corporations`相当の
    フラグ): 指定すると、全法人(約581万件。国の機関だけでなく民間企業も含む)
    を`graph/houjin-bangou-all/{取得日}`という別グラフとしてkg.nqに追記する。
    **既存の国の機関グラフ(848件規模の縦スライス)は変えない**(task-8-brief.md)。
    既定はFalse(触らない) — この規模のストリーミング投入・バッチ検証は
    コストが軽くないため、必要なリリース(RS/支出データを含むもの)でだけ
    明示的に有効にする。

    **`fetched_on`に`rs-system`を含めるなら`include_all_corporations=True`が
    必須**(裁定B17懸念2/B18。task-7-report.md)。`budget:recipient`が指す
    支出先の多くは民間企業で、848件規模の国の機関グラフには存在しない。
    全法人グラフを投入しないと参照整合ゲートが必ず数万件規模の違反で
    止まる — それ自体はゲートが正しく機能している証拠だが、「意図せず
    RSだけを結線してゲートに阻まれる」を避けるため、ここで先に明示的に
    エラーにする(黙って通さない)。

    `previous_release`(Task 10。更新の一巡): 前リリースの取得日を渡すと、
    ソースの内容が前リリース時点からバイト単位で不変なグラフについては
    再生成(emit+SHACL検証)をスキップし、前リリースのグラフをそのまま
    `clean`(検証後のDataset)へ引き継ぐ(carry-over)。**依存関係を考慮する**:
    houjin-bangou自体が不変でも、そのグラフに依存するegov-law/rs-system
    のグラフは、依存元(houjin-bangou・ministry-codes・egov-law)のいずれか
    が変化していれば据え置かない(`_GRAPH_DEPENDENCIES`参照)。既定は`None`
    (=carry-over を一切使わない。既存の全呼び出し元と後方互換)。
    """
    settings = get_settings()
    if not fetched_on:
        raise ValueError(
            "取得日が1件も渡されていない。例: {'houjin-bangou': date(2026, 8, 1)}"
        )
    if "rs-system" in fetched_on and not include_all_corporations:
        raise ValueError(
            "rs-system を含むリリースは include_all_corporations=True が必須である"
            "(裁定B17懸念2/B18)。budget:recipient が指す支出先の多くは民間企業"
            "であり、848件規模の国の機関グラフには存在しない。全法人グラフを"
            "投入しないと参照整合ゲートが必ず違反で止まる。意図的にrs-systemを"
            "含めるなら include_all_corporations=True を明示する"
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
    # fetched_on/レイクメタデータだけで判定できるため、egov-law/rs-systemの
    # 実ファイル解析より前に決められる——`_carry_over_source_date`は
    # `own_source_id`が`fetched_on`に無ければ`None`を返すので、無条件に
    # 呼んでよい)。**前リリースへの実際の存在確認はここで1回だけ行う**
    # (advisorレビュー指摘: ソースごとに前リリースのkg.nqを何度も読むと、
    # RS入りの前リリースではhoujin-bangou-allの約3,500万行を含むため、
    # `rs_carry_date`の判定を後段(rs-systemブロック内)まで遅らせたまま
    # `Dataset`へ丸ごとパースする実装はR19/R21に反する規模のメモリを使う。
    # 3件の据え置き候補のうちrs-systemだけは後段の「解析そのものを省略する」
    # 分岐(後述)がこの値を直接使うため、その分岐より前に確定させる必要がある)
    houjin_carry_date = _carry_over_source_date("houjin-bangou", fetched_on, previous_release)
    egov_carry_date = _carry_over_source_date("egov-law", fetched_on, previous_release)
    rs_carry_date = _carry_over_source_date("rs-system", fetched_on, previous_release)

    carried_graphs: dict[str, Graph] = {}
    if previous_release is not None:
        # wanted_urisが空でも存在確認だけは行う(「前リリースが実在する」
        # という呼び出し側の明示の主張は、carry-over候補の有無と無関係)
        previous_kg_path = _previous_release_kg_nq_path(previous_release)
        wanted_uris: set[str] = set()
        if houjin_carry_date is not None:
            wanted_uris.add(uris.graph_uri("houjin-bangou", houjin_carry_date))
        if egov_carry_date is not None:
            wanted_uris.add(uris.graph_uri("egov-law", egov_carry_date))
        if rs_carry_date is not None:
            wanted_uris.add(uris.graph_uri("rs-system", rs_carry_date))
        if wanted_uris:
            carried_graphs = _extract_graphs_from_kg_nq(previous_kg_path, wanted_uris)

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
    law_jurisdiction_extraction_failed = 0
    egov_date: datetime.date | None = None
    egov_snapshot = None

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
            jr = law_mod.derive_jurisdiction(record, ministry_reference_by_name, old_ministry_names)
            if jr is None or jr is law_mod.EXTRACTION_FAILED:
                if jr is law_mod.EXTRACTION_FAILED:
                    law_jurisdiction_extraction_failed += 1
                continue
            jurisdictions[record.law_id] = jr
            law_jurisdiction_resolved += len(jr.resolved)
            law_jurisdiction_unresolved += len(jr.unresolved)

    # =========================================================================
    # Task 10: rs-system結線(任意ソース)。
    #
    # **据え置き(carry-over)対象なら、パース・解決処理そのものを省略する**
    # (houjin-bangou/egov-lawと異なり、rs-systemの解決結果を必要とする
    # 下流の消費者がpipeline内に無いため、省略しても他の処理に影響しない —
    # これがcarry-overの実際の計算コスト削減になる部分。`rs_carry_date`は
    # 既にファイル冒頭で確定・存在確認済みなので、ここでは再計算しない)
    # =========================================================================
    budget_projects_all: tuple[rs_mod.BudgetProjectRecord, ...] = ()
    budget_expenditures_all: tuple[rs_mod.ExpenditureRecord, ...] = ()
    budget_unresolved_all: tuple[rs_mod.UnresolvedBudgetReference, ...] = ()
    budget_stats = rs_mod.BuildStats()
    rs_date: datetime.date | None = None
    rs_snapshot_sha256s: list[str] = []

    if "rs-system" in fetched_on:
        rs_date = _source_date("rs-system", fetched_on)
        # ファイル群の実在確認(メタデータのみ。CSV本体は読まない)は
        # 据え置き判定の有無にかかわらず行う — 呼び出し側が指定した取得日に
        # スナップショットが無ければ、据え置くにせよ再生成するにせよ
        # 前提が崩れている
        rs_paths = _rs_group_paths(rs_date)
        rs_snapshot_sha256s = [
            s.sha256
            for s in lake.list_snapshots("rs-system")
            if s.fetched_on == rs_date and s.path in rs_paths.values()
        ]

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
            rs_parse_stats = rs_mod.RsParseStats()
            rs_rows = list(rs_mod.parse_rs(rs_paths, stats=rs_parse_stats))
            budget_result = rs_mod.build_projects(
                rs_rows, ministry_reference_by_name, laws_by_id, laws_by_title, name_index={}
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

    # =========================================================================
    # Task 8: 全法人のストリーミング投入(フラグON時のみ)。
    #
    # rdflib の Dataset には載せない(全法人約3,500万トリプル規模はメモリが
    # 破綻する — stream_emit.py モジュールdocstring参照)。国の機関グラフとは
    # 完全に独立した経路で、別ファイルへストリーミングで書き、バッチSHACLで
    # 検証してから**検証を通った場合だけ**kg.nqへ追記する(検証前に本体へ
    # 混ぜない。enforce_release_gate の「既定は止まる側」をここでも守る)。
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
        all_corporations_graph_uri = uris.graph_uri(ALL_CORPORATIONS_GRAPH_ID, houjin_date)
        out_dir.mkdir(parents=True, exist_ok=True)
        all_corporations_nq_path = out_dir / "houjin-bangou-all.nq"

        def _all_corporations_source() -> Iterator[org_mod.Organization]:
            # **ParseStatsを渡さない。** dedup_organizationsはこの関数(source)を
            # 2回呼ぶ(2パス方式。stream_emit.dedup_organizationsのdocstring
            # 参照)。同じParseStatsオブジェクトをここで束縛して2回分蓄積させると、
            # rows_seen等の集計が二重になる(dedup_organizations側が注意している
            # 罠と対になる、呼び出し側の責務)。列レイアウトの妥当性検査
            # (_assert_layout_plausible)はstats無しでも内部で自動的に走るので、
            # 渡さなくても安全装置は落ちない
            return org_mod.parse_source(snapshot_path)

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
                f"警告: houjin-bangou-allのバッチ検証で"
                f"{corporations_all_quarantined}バッチが不合格"
                f"(違反合計{total_violations}件)。"
                f" バッチ番号: {[r.batch_index for r in failing_batches]}"
                f" 詳細レポート: {[r.report_path for r in failing_batches]}"
            )

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
        # O-10: 合格時は中間ファイルを削除する。内容はkg.nqへ追記済みで
        # 二重に持つ理由が無く、581万件規模(約1GB)を毎回残すと成果物
        # ディレクトリが肥大する。**不合格時はここに来ない**ため、
        # houjin-bangou-all.nqは事実上の隔離物として残る(バッチ単位の
        # 違反レポートとは別に、入力全体を再現できる状態を保つ意味がある)
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

    return PipelineReport(
        # リリース名は**呼び出し側が渡した取得日**のうち最も新しいもの。
        # 参照表の recorded_on を混ぜないのは、成果物ディレクトリ名や manifest の
        # release と食い違わせないため
        release=max(fetched_on.values()).isoformat(),
        rows_seen=stats.rows_seen,
        rows_rejected=stats.rows_rejected,
        rows_short=stats.rows_short,
        organizations=total_organizations,
        government_organs=len(orgs),
        ministries=len(ministries),
        unmatched_ministries=len(unmatched),
        graphs_validated=len(results),
        graphs_quarantined=len(quarantined),
        # Dataset から正確なグラフURIを取る。テキストから推測してはならない
        graphs=surviving_graphs,
        sources=surviving_sources,
        quarantined_sources=quarantined_sources,
        reference_violations=[str(v) for v in reference_violations],
        corporations_all=corporations_all,
        corporations_all_dedup_removed=corporations_all_dedup_removed,
        corporations_all_quarantined=corporations_all_quarantined,
        carried_over=carried_over,
        law_records=len(law_records),
        law_jurisdiction_resolved=law_jurisdiction_resolved,
        law_jurisdiction_unresolved=law_jurisdiction_unresolved,
        law_jurisdiction_extraction_failed=law_jurisdiction_extraction_failed,
        budget_projects=len(budget_projects_all),
        budget_expenditures=len(budget_expenditures_all),
        budget_expenditures_bundled=budget_stats.expenditures_bundled,
        budget_recipients_sentinel=budget_stats.recipients_sentinel,
        budget_recipients_resolved_by_houjin_bangou=budget_stats.recipients_resolved_by_houjin_bangou,
        budget_recipients_resolved_by_name=budget_stats.recipients_resolved_by_name,
        budget_recipients_unresolved=budget_stats.recipients_unresolved,
        budget_ministries_resolved=budget_stats.ministries_resolved,
        budget_ministries_unresolved=budget_stats.ministries_unresolved,
        budget_basis_law_resolved=(
            budget_stats.basis_law_resolved_by_id
            + budget_stats.basis_law_resolved_by_title_raw
            + budget_stats.basis_law_resolved_by_title_stripped
        ),
        budget_basis_law_unresolved=budget_stats.basis_law_unresolved,
        budget_ratio_exact_1_0=budget_ratio_exact_1_0,
        budget_ratio_exact_2_0=budget_ratio_exact_2_0,
        budget_ratio_exact_3_0=budget_ratio_exact_3_0,
        budget_ratio_total_zero=budget_ratio_total_zero,
        budget_ratio_other=budget_ratio_other,
        budget_ratio_no_denominator=budget_ratio_no_denominator,
    )
