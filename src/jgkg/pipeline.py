"""パイプラインの結線。取得済みスナップショットからN-Quadsまでを1本にする。

各段の件数を PipelineReport として返す。観測性は設計書§11.1の要件。
"""
import datetime
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel
from rdflib import Dataset

from jgkg import lake, sources, uris, validate
from jgkg.config import get_settings
from jgkg.connectors import houjin_bangou
from jgkg.rdf import emit
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import organization as org_mod

MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")
SHAPES_DIR = Path("schema/generated")


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
    #  オブジェクトIRIを誤認する。実測で確認済み)
    graphs: list[str]
    # ソースIDごとの「いつ時点か」。**単一の取得日でリリース全体を語らない。**
    # 設計書§6.4の更新頻度表は monthly/annual/ondemand とソースごとに異なる。
    # manifest はこれをそのまま使う(build.sh で手書きしない)。
    # **KGに実際に残ったソースだけを載せる。** 隔離されたソースの日付を書くと
    # 「この日付のデータを含む」という嘘になる(I2 で直した捏造と同族)
    sources: dict[str, str]
    # 隔離されて成果物に入らなかったソース。**落ちたことを黙って消さない**ため、
    # sources から外す代わりにここに出す(設計書§8.2「未解決を無かったことにしない」)
    quarantined_sources: list[str]


class QuarantineNotEmptyError(RuntimeError):
    """隔離が発生した状態でリリースしようとした。"""


def enforce_release_gate(report: PipelineReport, *, allow_partial: bool = False) -> None:
    """隔離が起きていたらリリース処理を止める(設計書§6.3のリリースゲート)。

    グラフ単位で隔離するため、**5百万行のうち1行の違反でそのソースのグラフ全体が
    落ちる。** そのとき残るのは出典グラフだけなので、KGは「2026-08-01時点の法人番号
    データを含む」と答え続けるのに中身が無い、という状態になる。設計書§6.3は
    「CIで検証を通った成果物だけが本番に出るという構造を強制する」と書いているが、
    この判定を行う場所がどのタスクにも割り当てられていなかった。

    **既定は止まる側。** 部分的なリリースが必要な運用は、呼び出し側が
    `allow_partial=True`(build.sh では `--allow-partial`)を明示的に渡す。
    「気づかずに出荷される」経路を無くすことが目的なので、既定を緩めてはならない。
    """
    if report.graphs_quarantined == 0:
        return
    message = (
        f"SHACL検証で {report.graphs_quarantined} グラフが隔離された"
        f"(検証したグラフ数 {report.graphs_validated}、"
        f"残ったグラフ {report.graphs})。"
        f" 隔離内容は quarantine ディレクトリを見る。"
        " このままリリースすると、中身が無いのに出典だけが残ったKGが出荷される"
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


def run(fetched_on: Mapping[str, datetime.date], out_dir: Path) -> PipelineReport:
    """ソースIDごとの「いつ時点か」を受け取ってKGを1本作る。

    **単一の取得日を全ソースに仮定しない。** 設計書§6.4の更新頻度表は
    monthly/annual/ondemand とソースごとに異なるため、単一日付の仮定は
    Phase 1(e-Gov 月次 / 予算 年次)で必ず破綻する。
    """
    settings = get_settings()
    if not fetched_on:
        raise ValueError(
            "取得日が1件も渡されていない。例: {'houjin-bangou': date(2026, 8, 1)}"
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

    ds = Dataset(default_union=True)
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

    results = validate.validate_dataset(ds, SHAPES_DIR)
    quarantined = [r for r in results if not r.conforms]
    if quarantined:
        validate.quarantine(ds, results, Path(settings.quarantine_dir))

    clean = validate.passing_dataset(ds, results)
    out_dir.mkdir(parents=True, exist_ok=True)
    emit.write_nquads(clean, out_dir / "kg.nq")

    surviving_graphs = sorted(str(c.identifier) for c in clean.graphs() if len(c) > 0)
    # **成果物に残ったソースだけを sources に載せる。** グラフが隔離されたのに
    # 「このソースはこの日付のデータを含む」と書くと、manifest が嘘をつく
    # (`--allow-partial` で出荷したときに実際に起きる)。落ちたことは
    # quarantined_sources に出して、黙って消さない
    source_dates = {"houjin-bangou": houjin_date, "ministry-codes": ministry_date}
    surviving_sources = {
        sid: d.isoformat()
        for sid, d in source_dates.items()
        if uris.graph_uri(sid, d) in surviving_graphs
    }
    quarantined_sources = sorted(set(source_dates) - set(surviving_sources))

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
    )
