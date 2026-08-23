"""パイプラインの結線。取得済みスナップショットからN-Quadsまでを1本にする。

各段の件数を PipelineReport として返す。観測性は設計書§11.1の要件。
"""
import datetime
from collections.abc import Iterator, Mapping
from pathlib import Path

from pydantic import BaseModel
from rdflib import Dataset, URIRef

from jgkg import lake, sources, uris, validate
from jgkg.config import get_settings
from jgkg.connectors import houjin_bangou
from jgkg.rdf import emit, stream_emit
from jgkg.rdf.provenance import provenance_graph
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import organization as org_mod

# 全法人の別グラフ(Task 8)のグラフID部分。「houjin-bangou」と同じ取得済み
# スナップショットから作る別グラフなので、sources.pyに新しいソースを登録する
# 必要はない — 出典(provenance_graph)は"houjin-bangou"のsource_idのまま、
# グラフURIだけをこの名前にする(同じ一次資料から2つの異なる粒度のグラフを
# 作っている、という事実をそのまま記録する)
ALL_CORPORATIONS_GRAPH_ID = "houjin-bangou-all"

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


def run(
    fetched_on: Mapping[str, datetime.date],
    out_dir: Path,
    *,
    include_all_corporations: bool = False,
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

    # **隔離を通過した `clean` に対して検査する(`ds` ではない)。** SHACLで
    # 隔離されたグラフへの参照は「壊れて当然」なのでここでも違反として拾って
    # しまうと、原因(SHACL側の隔離)と結果(参照切れ)が両方報告されて
    # ノイズになる。`clean` は`--allow-partial`時に実際に出荷される内容と
    # 一致するので、そこでの参照切れこそがこのゲートが守るべきものである。
    # **houjin-bangou-allは`clean`に含まれない**(rdflibに載らない規模のため
    # 意図的に別経路。validate.check_reference_integrityのexcludeパラメータは
    # このゲートに和集合として merge する将来の呼び出し側のために用意した
    # 機構であり、ここでは使わない — 除外は「載っているものを取り除く」
    # 操作であって、そもそも載せていないものには不要)
    reference_violations = validate.check_reference_integrity(clean, SHAPES_DIR)

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
        reference_violations=[str(v) for v in reference_violations],
        corporations_all=corporations_all,
        corporations_all_dedup_removed=corporations_all_dedup_removed,
        corporations_all_quarantined=corporations_all_quarantined,
    )
