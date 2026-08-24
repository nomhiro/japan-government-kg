"""SHACL検証ゲート。不合格のグラフはストアにロードしない(設計書§8.3)。

「一部が壊れていても入れてしまう」ことを許すと、公共財としての信頼性が
最初に崩れる。ここは厳格側に倒す。
"""
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import RDF, RDFS, Dataset, Graph, URIRef
from rdflib.namespace import SH

from jgkg.config import get_settings
from jgkg.schema_lang import REFERENCE_CLASSES_FILENAME


@dataclass(frozen=True)
class ValidationResult:
    graph_uri: str
    conforms: bool
    # **`validate_dataset`では全文。`validate_stream`では要約(意識的な非対称。
    # B-1/裁定B23)。** `validate_dataset`が検証するグラフは設計上有界
    # (Phase 1のrs-systemグラフでも最大2万エンティティ規模。O(5.8M)には
    # ならない)ため全文を保持してもメモリは問題にならず、不合格時は
    # `quarantine()`が既にディスクへ書く。一方`validate_stream`は581万件÷
    # batch_size回分の結果を`list`に積むため、1件でも全文(pyshaclは違反
    # 1件ごとにshapeの説明文まで複製する形式で出す — 実測5件で4,117文字)
    # を持たせるとバッチ数×違反件数に比例してメモリが伸びる(実測: 8GiB
    # 想定構成で破綻)。`validate_stream`はここに要約だけを置き、全文は
    # `report_path`(ディスク)に書く
    report_text: str
    # バッチ検証(validate_stream)の結果にのみ設定される(0起点)。
    # validate_datasetの結果は常にNone(グラフ単位=バッチという概念が無い)。
    # Task 11がどのバッチで違反が起きたかを特定できるようにするための追加情報
    # (task-8-brief.md「消費者のいない記録」を避ける)。**batch_indexの読み手は
    # 2つ**: 不合格時の隔離レポートのファイル名(batch-{index:04d})と、
    # pipeline.pyがコンソールに出す警告
    batch_index: int | None = None
    # 違反の総件数。`report_text`が要約であっても、この値だけは常に厳密
    # (pyshaclの検証レポートグラフから`sh:ValidationResult`型の主語数を数えた
    # 値。validate_dataset/validate_streamの両方で埋める)
    violation_count: int = 0
    # 不合格バッチの違反全文を書き出したファイルへのパス文字列。
    # `validate_stream`が不合格バッチについてのみ設定する(合格バッチ・
    # `validate_dataset`の結果は常にNone)。全文は`quarantine_dir`直下に
    # バッチ単位でストリーミング書き出しする(B-1/裁定B23)
    report_path: str | None = None


SHAPES_FILENAME = "all.shacl.ttl"
ONTOLOGY_FILENAME = "all.owl.ttl"

# **モジュールレベルの単純キャッシュ(Task 4の申し送り)。** validate_streamは
# 581万件÷batch_sizeの回数だけ_load_shapesを呼ぶ(バッチごとに検証するため)。
# キャッシュが無いと、そのたびに all.shacl.ttl(500行超)を再パースし、実測で
# 全体の25〜30%のコストになる。shapes_dirの解決済みパスをキーにする —
# 同じディレクトリを指す相対/絶対パスの表記違いを同一視するため。
# **返り値のGraphは呼び出し側で変更しないことが前提**(validate_dataset/
# validate_streamのどちらも読み取りにしか使わない。共有しても安全)
_shapes_cache: dict[str, Graph] = {}


def _load_shapes(shapes_dir: Path) -> Graph:
    """検証用のSHACLシェイプを読む(モジュールレベルでキャッシュする)。

    **モジュール別のSHACLをマージしてはならない。** `org.yaml` は `core` を import する
    ため `org.shacl.ttl` にも core のクラスのNodeShapeが生成される。両方を読むと同一
    クラスに閉じたシェイプが2つ適用され、許可プロパティ集合の積になって偽の違反を
    起こす。全モジュールを束ねた `all.yaml` から生成した単一ファイルだけを読む。
    """
    key = str(Path(shapes_dir).resolve())
    cached = _shapes_cache.get(key)
    if cached is not None:
        return cached

    path = shapes_dir / SHAPES_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"SHACLシェイプが見つからない: {path}。"
            " scripts/generate-schema.sh を実行する"
        )
    shapes = Graph()
    shapes.parse(path, format="turtle")
    _shapes_cache[key] = shapes
    return shapes


def _shape_target_classes(shapes: Graph) -> set[URIRef]:
    """シェイプが対象にしているクラスIRIの集合。

    LinkML の gen-shacl が出すのは `sh:targetClass` だけなので、それだけを見る。
    将来 `sh:targetSubjectsOf` 等を手書きで足したら、ここも足す必要がある。
    """
    return {o for o in shapes.objects(None, SH.targetClass) if isinstance(o, URIRef)}


def _count_violations(report_graph: Graph) -> int:
    """SHACL検証レポートから違反件数を数える(`sh:ValidationResult`型の主語数)。

    `report_text`(pyshaclの人間向けテキスト出力)は違反1件ごとにshapeの
    説明文まで複製して積むため、件数が増えるほど文字数が線形に伸びる
    (実測: 5件で4,117文字)。件数だけが要る場面(validate_streamの要約・
    バッチ結果の集計)では、テキストを数えるのではなく、構造化された
    レポートグラフ側の`sh:ValidationResult`を数える方が正確かつ軽い。
    """
    return len(list(report_graph.subjects(RDF.type, SH.ValidationResult)))


def _own_declared_classes(graph: Graph, term_prefix: str) -> set[URIRef]:
    """このグラフが `rdf:type` で名指しした、自オントロジーのクラスIRI。"""
    return {
        o
        for o in graph.objects(None, RDF.type)
        if isinstance(o, URIRef) and str(o).startswith(term_prefix)
    }


def _assert_shapes_cover(graph_uri: str, declared: set[URIRef], targets: set[URIRef]) -> None:
    """自オントロジーのクラスを名指ししているのにシェイプが無い、を例外にする。

    **これが無いと、名前空間がずれた瞬間に検証ゲートが「対象0件で合格」に静かに
    退化する。** 起こりうる原因は3つあり、どれも今までは沈黙していた:

    1. `.env` の `JGKG_BASE_URI` を変えたが生成物を作り直していない
       (`jgkg.base_uri` の差し替え+再生成が必要)
    2. 新しいモジュールを追加して `schema/all.yaml` の `imports` に足し忘れた
       → そのクラスのシェイプが `all.shacl.ttl` に無い
    3. 生成物が古い

    出典グラフのように `rdf:type` を1つも持たないグラフは対象外(`declared` が空)。
    """
    missing = declared - targets
    if not missing:
        return
    raise ValueError(
        f"グラフ {graph_uri} は自オントロジーのクラスを名指ししているのに、"
        f"対応するSHACLシェイプが1つも無い: {sorted(str(m) for m in missing)}。"
        " このまま検証すると対象0件で合格し、検証ゲートが素通しになる。"
        " (a) ベースURIを差し替えたなら"
        " `uv run python -m jgkg.base_uri --check` と `./scripts/generate-schema.sh`、"
        " (b) モジュールを追加したなら `schema/all.yaml` の imports を確認する"
    )


def validate_dataset(ds: Dataset, shapes_dir: Path) -> list[ValidationResult]:
    """名前付きグラフごとに検証する。グラフが置換の単位なので検証も同じ単位で行う。

    **`sh:class`はここでは検証しない(裁定B4)。** グラフを跨ぐ参照の型制約は
    グラフ単位のSHACLでは原理的に検証できないため、`schema_lang`が生成時に
    自名前空間への`sh:class`をシェイプから除去している。型の検証は
    `check_reference_integrity`(和集合Dataset向け)が別途行う。
    """
    shapes = _load_shapes(shapes_dir)
    targets = _shape_target_classes(shapes)
    term_prefix = f"{get_settings().base_uri}/def/"
    results: list[ValidationResult] = []

    for ctx in ds.graphs():
        if len(ctx) == 0:
            continue
        target = Graph()
        for triple in ctx:
            target.add(triple)

        _assert_shapes_cover(
            str(ctx.identifier),
            _own_declared_classes(target, term_prefix),
            targets,
        )

        conforms, report_graph, report_text = shacl_validate(
            data_graph=target,
            shacl_graph=shapes,
            advanced=True,
            inplace=False,
        )
        results.append(
            ValidationResult(
                graph_uri=str(ctx.identifier),
                conforms=bool(conforms),
                report_text=report_text,
                violation_count=_count_violations(report_graph),
            )
        )
    return results


# =============================================================================
# Task 8: 全法人規模のバッチSHACL検証(validate_stream)
#
# **バッチSHACLが全体検証と等価である条件(このタスクの中心の論証)**:
# このスキーマのSHACLシェイプはエンティティ局所(閉じたNodeShape。エンティティ
# を跨ぐ制約はR2で排除済み、裁定B4)である。したがって、同一主語の全トリプル
# が同じバッチに入っていれば、バッチ単位の検証結果の合併は全体検証と一致する。
# この関数は3条件のうち「バッチ境界は主語の切れ目でのみ切る」を担う。
# 残り2条件(1エンティティ連続書き/上流dedup)は`stream_emit`側の責務であり、
# この関数はそれが守られたN-Quadsファイルであることを前提にする
# (tests/test_stream_emit.pyのStep3が、この前提を外すと結果が全体一発と
# 一致しなくなることを実証している)。
# =============================================================================


def _split_nquads_line(line: str) -> tuple[str, str]:
    """1行のN-Quadsを`(N-Triples本体, グラフ項)`に分ける。

    行は必ず`SUBJ PRED OBJ GRAPH .`の形($8.3節のstream_emit出力そのもの)。
    末尾から2つ目・1つ目の空白がそれぞれ「OBJの終わり/GRAPHの始まり」と
    「GRAPHの終わり/`.`の始まり」に一致する。**これはIRI(グラフ項)がraw
    spaceを含まないから常に成立する**。OBJがリテラルで内部に空白を含んでいても、
    その空白は末尾から数えて3つ目以降にしか現れないので`rsplit(maxsplit=2)`
    は安全(`stream_emit_organizations`が書いた行にのみ通用する前提)。
    """
    body = line.rstrip("\n").rstrip("\r")
    # O-12: 空行(または空白のみの行)は`rsplit(" ", 2)`が3要素を返せず
    # `ValueError: not enough values to unpack`という、原因の分からない
    # メッセージで落ちる。stream_emit_organizationsは空行を書かないため、
    # ここに来るのは想定外の入力(手編集・破損)であり、その旨を先に言う
    if not body.strip():
        raise ValueError(
            f"N-Quadsの行として想定外の空行が混入している: {line!r}。"
            " stream_emit_organizations以外が書いたファイルの疑いがある"
        )
    nt_body, graph_term, dot = body.rsplit(" ", 2)
    if dot != ".":
        raise ValueError(
            f"N-Quadsの行として想定外の終端(末尾が'.'でない): {line!r}。"
            " stream_emit_organizations以外が書いたファイルの疑いがある"
        )
    return nt_body, graph_term


# 1エンティティが持つ最大トリプル数(このスキーマでは6: type/prefLabel/
# houjinBangou/organizationKindCode/prefectureName/cityName)に十分な安全
# 余裕を持たせた上限。**厳密な物理限界ではなく、退行の検出線。** 上流の
# dedup_organizationsが効かず同一法人番号の行が延々と連続して書かれるような
# 系統的な壊れ方を、バッファが無制限に伸びる前に止める(F-4a)
_MAX_SUBJECT_RUN = 1000

# validate_streamの要約(ValidationResult.report_text)の文字数上限。
# pyshaclのreport_textは違反1件ごとにshapeの説明文まで複製するため件数に
# 比例して伸びる(実測: 5件で4,117文字≒1件あたり約800文字)。先頭をこの
# 文字数で切ることで、要約の長さをバッチの違反件数と無関係なO(1)に保つ
# (B-1/裁定B23)。全文は`quarantine_dir`のファイルに別途書く
_SUMMARY_MAX_CHARS = 2000


def _bounded_summary(report_text: str, violation_count: int, report_path: Path) -> str:
    """`report_text`の先頭`_SUMMARY_MAX_CHARS`文字だけを使った要約を作る。

    全文は`report_path`(呼び出し側が既に書いたファイル)を指すだけで、
    ここでは保持しない。バッチの違反が1件でも2,000件でも、この関数が返す
    文字列の長さはほぼ一定になる(B-1修正の中心。実際の固定を
    tests/test_stream_emit.pyで違反200件・2,000件の2規模で確認する)。
    """
    head = report_text[:_SUMMARY_MAX_CHARS]
    suffix = "...(以下省略。全文は上記ファイル)" if len(report_text) > _SUMMARY_MAX_CHARS else ""
    return f"{violation_count}件の違反。全文: {report_path}\n{head}{suffix}"


def validate_stream(
    nq_path: Path,
    shapes_dir: Path,
    quarantine_dir: Path,
    batch_size: int = 50_000,
) -> list[ValidationResult]:
    """N-Quadsファイルをバッチに分けてSHACL検証する(全件を一度にrdflibへ載せない)。

    **前提**: `nq_path`は`stream_emit.stream_emit_organizations`が書いた
    ファイルであること(1行=1トリプル・主語は常にIRI・1エンティティの全
    トリプルが連続・上流でdedup済み)。この前提が崩れている場合、以下の
    3つの防御のどれかが例外にする(沈黙して結果が全体一発の結果と食い違う
    ことを許さない — レビューが実測で指摘した実際の退行経路):

    1. **バッファ上限(F-4a)**: 同一主語が`_MAX_SUBJECT_RUN`行を超えて
       連続したら例外。dedupが効かず同一法人番号の行が延々と書かれるような
       系統的な壊れ方を検出する。
    2. **主語の非隣接再出現(F-4b/O-8)**: 一度閉じた(検証済みの)バッチに
       現れた主語が、後の別バッチに再出現したら例外。1エンティティ連続
       書き(条件1)か上流dedup(条件3)のいずれかが崩れている状況そのもの
       (`closed_subjects`という全主語文字列の集合を保持する — 5.8M件で
       実測約683MiB。**B21(Task 10)以前**は`dedup_organizations`の1パス目
       `seen`(int化した法人番号のみ。実測約490MiB)と同時に生存しなかった
       (dedupが完全に終わり`seen`を解放した後に初めてstream_emit_
       organizationsの書き出しが始まり、その書き出しが終わった後に初めて
       この関数が読み始める逐次のパイプラインだったため)。**B21以降は
       この前提が崩れている**: `dedup_organizations`は`seen`を
       `StreamStats.houjin_bangou_seen`として保持し続け、pipeline.pyが
       この関数(`validate_stream`)の実行後もそれを`check_reference_
       integrity`まで持ち越すため、この関数の実行中は`seen`(≒490MiB)と
       `closed_subjects`(≒683MiB)が**同時に生存する**(合計ピーク約
       1.2GiB。Phase 1の想定実行環境8GiBに対しては十分小さい。
       `jgkg.rdf.stream_emit`のモジュールdocstring参照)。
    3. **対象0件ガード(B-2)**: バッチが自オントロジーのクラスを1つも
       名指ししていない(=SHACLの対象が0件)なら例外。`validate_dataset`の
       `_assert_shapes_cover`と同じ原則をバッチ単位でも適用する — これが
       無いと、名前空間drift等でバッチが「対象0件で合格」に静かに退化する。

    **バッチ境界は主語の切れ目でのみ切る。** `batch_size`はバッチが到達する
    目安の行数であり、厳密な上限ではない — 主語が変わった行でだけ
    「今までのバッファを閉じるか」を判定するため、実際のバッチ行数は
    `batch_size`以上になることがある(1エンティティが`batch_size`行を
    超える場合はそのエンティティが尽きるまで閉じない)。

    **結果は要約のみを保持する(B-1/裁定B23)。** 以前は`ValidationResult.
    report_text`にpyshaclの全文をバッチごとに積んでいたため、`results`
    (バッチ数に比例する`list`)全体のメモリがバッチ数×違反件数に比例して
    伸びた(実測: 8GiB想定構成で破綻する規模)。不合格バッチについては
    全文を`quarantine_dir`へバッチ単位のファイルとして書き出し、
    `ValidationResult`には要約(`_bounded_summary`)・厳密な違反件数
    (`violation_count`)・そのファイルへのパス(`report_path`)だけを持たせる。

    バッチごとに新しい`Graph`へN-Triples(グラフ項を剥がした形)としてパース
    し、`validate_dataset`と同じ検査(網羅性ガード`_assert_shapes_cover` +
    `pyshacl`)を適用する。`_load_shapes`はモジュールレベルでキャッシュされる
    ため、バッチ数(581万÷batch_size)に比例した再パースは起きない
    (Task 4の申し送り)。
    """
    shapes = _load_shapes(shapes_dir)
    targets = _shape_target_classes(shapes)
    term_prefix = f"{get_settings().base_uri}/def/"

    results: list[ValidationResult] = []
    batch_index = 0
    graph_uri: str | None = None
    # 非隣接再出現(F-4b/O-8)の検出用。フル文字列で持つ理由・メモリの
    # 逐次性の論証はこの関数のdocstring参照
    closed_subjects: set[str] = set()

    def _flush(lines: list[str]) -> None:
        nonlocal batch_index, graph_uri
        if not lines:
            return
        nt_lines: list[str] = []
        batch_subjects: set[str] = set()
        for line in lines:
            nt_body, graph_term = _split_nquads_line(line)
            subject = nt_body.split(" ", 1)[0]
            if subject in closed_subjects:
                raise ValueError(
                    f"主語 {subject} が、既に閉じた(検証済みの)バッチとは"
                    f"別のバッチ({batch_index})に非連続で再出現した。"
                    " stream_emit_organizationsが1エンティティの全トリプルを"
                    "連続して書く前提(条件1)か、上流のdedup_organizationsが"
                    "同一法人番号を1件に統合する前提(条件3)のいずれかが"
                    "崩れている疑いがある。バッチ検証はどちらの前提にも"
                    "依存しているため、沈黙せずここで例外にする(F-4b/O-8)"
                )
            batch_subjects.add(subject)
            this_graph = graph_term[1:-1] if graph_term.startswith("<") else graph_term
            if graph_uri is None:
                graph_uri = this_graph
            elif this_graph != graph_uri:
                raise ValueError(
                    f"1ファイル内に複数のグラフが混在している({graph_uri!r} と "
                    f"{this_graph!r})。stream_emit_organizationsは1呼び出しにつき"
                    "1グラフしか書かない前提が崩れている"
                )
            nt_lines.append(nt_body + " .\n")
        closed_subjects.update(batch_subjects)

        batch_graph = Graph()
        batch_graph.parse(data="".join(nt_lines), format="nt")

        declared = _own_declared_classes(batch_graph, term_prefix)
        if not declared:
            raise ValueError(
                f"バッチ{batch_index}(グラフ {graph_uri!r})が自オントロジーの"
                "クラスを1つも名指ししていない(rdf:typeが無いか、名前空間が"
                "ずれている)。このまま検証すると対象0件で合格し、検証ゲートが"
                "素通しになる。validate_datasetの_assert_shapes_coverと同じ"
                "原則をここでも適用する(B-2)"
            )
        _assert_shapes_cover(graph_uri or "(unknown)", declared, targets)

        conforms, report_graph, report_text = shacl_validate(
            data_graph=batch_graph,
            shacl_graph=shapes,
            advanced=True,
            inplace=False,
        )
        violation_count = _count_violations(report_graph)
        report_path: str | None = None
        summary = report_text
        if not conforms:
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            stem = _safe_stem(graph_uri or "unknown")
            out_path = quarantine_dir / f"{stem}.batch-{batch_index:04d}.report.txt"
            out_path.write_text(report_text, encoding="utf-8")
            report_path = str(out_path)
            summary = _bounded_summary(report_text, violation_count, out_path)

        results.append(
            ValidationResult(
                graph_uri=graph_uri or "(unknown)",
                conforms=bool(conforms),
                report_text=summary,
                batch_index=batch_index,
                violation_count=violation_count,
                report_path=report_path,
            )
        )
        batch_index += 1

    buffer: list[str] = []
    current_subject: str | None = None
    same_subject_run = 0
    with nq_path.open("r", encoding="utf-8") as f:
        for line in f:
            subject = line.split(" ", 1)[0]
            if subject != current_subject:
                if len(buffer) >= batch_size:
                    _flush(buffer)
                    buffer = []
                same_subject_run = 0
            same_subject_run += 1
            if same_subject_run > _MAX_SUBJECT_RUN:
                raise ValueError(
                    f"主語 {subject} が {same_subject_run} 行を超えて連続して"
                    f"いる(上限 {_MAX_SUBJECT_RUN})。1エンティティが持つ"
                    "トリプル数は通常一桁(このスキーマでは最大6行)なので、"
                    "桁違いの連続は上流のdedup_organizationsが効かず同一"
                    "法人番号の行が延々と書かれている疑いがある。バッファが"
                    "無制限に伸びる前にここで止める(F-4a)"
                )
            buffer.append(line)
            current_subject = subject
    _flush(buffer)

    # **0バッチ(空ファイル)を正常終了として返さない。** `all([])`はTrueに
    # なるので、呼び出し側が`all(r.conforms for r in results)`のような
    # 判定をすると「対象0件で合格」に退化する。validate_dataset側の
    # `_assert_shapes_cover`と同じ原則(このモジュール一貫の作法)。
    # pipeline.py経路では`total_organizations == 0`の既存ガードが先に落ちる
    # ため実際には到達しないが、`validate_stream`は単体でも呼べる関数なので
    # ここでも独立に防ぐ
    if not results:
        raise ValueError(
            f"{nq_path} から1件も検証できなかった(空ファイルの疑いがある)。"
            " 0バッチを「合格」として返すと、all(r.conforms for r in results)"
            " のような判定が空振りで真になり、検証ゲートが素通しになる"
        )

    return results


# =============================================================================
# 参照整合ゲート(裁定B4): グラフを跨ぐ参照の型制約を和集合Datasetで検証する
# =============================================================================


@dataclass(frozen=True)
class ReferenceViolation:
    """`check_reference_integrity` が見つけた違反1件。"""

    path: str
    expected_class: str
    subject: str
    value: str
    reason: str

    def __str__(self) -> str:
        return (
            f"{self.subject} -{self.path}-> {self.value}: {self.reason}"
            f"(期待クラス: {self.expected_class})"
        )


def _load_ontology(shapes_dir: Path) -> Graph:
    """サブクラス閉包の計算に使う `rdfs:subClassOf` を読む(`all.owl.ttl`)。

    **`sh:class`の値検証のためではない(それは裁定B4で自名前空間について
    SHACLから除去済み)。** ここでの用途は`check_reference_integrity`が
    `rdf:type/rdfs:subClassOf*`(SHACLの`sh:class`と同じ意味論)を
    SHACLエンジンの外で自前で計算するための知識源。**データには混ぜない**
    (R1: 上位クラスの`rdf:type`を実体化しない、を維持する。データグラフに
    実体化するのではなく、このグラフを別途参照するだけ)。
    """
    path = shapes_dir / ONTOLOGY_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"OWLオントロジーが見つからない: {path}。"
            " scripts/generate-schema.sh を実行する"
        )
    ontology = Graph()
    ontology.parse(path, format="turtle")
    return ontology


def _load_reference_classes(shapes_dir: Path) -> list[dict[str, str]]:
    """`schema_lang`が`sh:class`から抽出した参照制約(`reference-classes.json`)を読む。

    **ファイルが無ければ例外。中身が`[]`でも例外にする(裁定B9)。** 空リストで
    素通りすると、`_assert_shapes_cover`が閉じたシェイプで防いでいる「対象0件で
    合格」の退化と同じ形になる。

    このスキーマには自名前空間への`sh:class`が現に存在する(`jurisdiction`/
    `involves_agent`/`unresolvedFor`)ので、`[]`は「対象が無い」という正常な
    状態ではなく、**後処理の二重適用の証拠**である(実測で確認した非冪等性:
    `schema_lang.process()`は`sh:class`を除去しながら対を書き出すため、
    既に処理済みの`all.shacl.ttl`に再適用すると`reference-classes.json`が
    `[]`になる。`scripts/generate-schema.sh`は毎回`gen-shacl`から作り直すので
    通常は起きないが、生成物1ファイルだけを手で流し直すと起きる)。
    レビュー指摘5を受け、「対象0件で合格」を作らない原則をここでも優先する
    (将来このスキーマから自名前空間へのsh:classが本当に0件になる変更が
    入った場合、この例外はいったん誤検知になる — その場合はこの関数自体を
    見直す)。
    """
    path = shapes_dir / REFERENCE_CLASSES_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"{path} が無い。scripts/generate-schema.sh を実行する"
            "(schema_lang が sh:class から参照制約を抽出してこのファイルに書く)"
        )
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not entries:
        raise ValueError(
            f"{path} の中身が空である。このスキーマには自名前空間へのsh:classが"
            "現に存在するため、空は後処理の二重適用の疑いがある(schema_lang."
            "process()は非冪等 — 既に除去済みのシェイプに再適用すると空になる)。"
            " scripts/generate-schema.sh からやり直す(gen-shaclの生の出力から"
            "作り直せば正しい件数になる)"
        )
    return entries


def _subclass_closure(ontology: Graph, cls: URIRef) -> set[URIRef]:
    """`cls`自身と、`rdfs:subClassOf*`で辿れるそのサブクラス全ての集合。

    `sh:class`の意味論(`rdf:type/rdfs:subClassOf*`)をSHACLエンジンの外で
    計算する部分(参照整合ゲートの中核)。
    """
    seen = {cls}
    frontier = [cls]
    while frontier:
        current = frontier.pop()
        for sub in ontology.subjects(RDFS.subClassOf, current):
            if isinstance(sub, URIRef) and sub not in seen:
                seen.add(sub)
                frontier.append(sub)
    return seen


def check_reference_integrity(
    ds: Dataset,
    shapes_dir: Path,
    externally_typed: Mapping[URIRef, Callable[[URIRef], bool]] | None = None,
) -> list[ReferenceViolation]:
    """自名前空間クラスへの参照(`sh:class`から抽出したもの)を和集合で検査する。

    **裁定B4(R2と同じ扱い)。** グラフを跨ぐ制約はグラフ単位のSHACL検証
    (`validate_dataset`)では原理的に検証できない — `org:houjinBangou`の
    必須制約がCQのSPARQLテストで担保されているのと同じ理由(設計書R2)。
    法令(`law:jurisdiction`)とその参照先の府省の型が別々の名前付きグラフに
    分かれる実運用(pipeline.pyの`source_id`別グラフ構成そのもの)では、
    参照先の型がその名前付きグラフの中に存在しないため、グラフ単位の
    `sh:class`は原理的に満たせない(Task 4 懸念1で発見したABox欠落)。
    `ds`は`default_union=True`のDataset(全グラフの和集合)を渡すこと。

    **`externally_typed`(裁定B21。Task 8の`exclude`機構を置き換える)**:
    期待クラスのIRI → membership_test(`URIRef -> bool`)の対応。全法人
    約3,500万トリプル規模(houjin-bangou-allグラフ)はrdflibの和集合に
    載せられないため、そこにしか型情報が無い参照(`budget:recipient`が
    指す民間企業など)を検査する手段が要る。**Task 8時点の`exclude`は
    「対象グラフを和集合から取り除く」機構だったが、これは54.9k件規模の
    実参照(Task 7懸念2で判明した実データの規模)を丸ごと検査放棄すること
    になり、参照整合ゲートの目的そのものに反する(裁定B21)。** 代わりに、
    houjin-bangou-allを実際にストリーミング投入した際に確定する「実在した
    法人番号の集合」(`stream_emit.StreamStats.houjin_bangou_seen`)を
    **外部の知識**としてここに渡す — rdflibには載せていない事実を、
    「載っているのと同じ扱いで検査に使う」ための経路である(除外=検査放棄
    ではなく、別経路で検査する)。

    判定は「`externally_typed`の各キー`C`のうち、`C`が`expected_class`の
    サブクラス閉包(`allowed`)に含まれるものについて、`membership_test(node)`
    を試す」という形にする。**単純な`externally_typed.get(expected_class)`
    にしてはならない** — 例えば`budget:recipient`の期待クラスは
    `core:Agent`だが、外部知識として渡す集合は`org:Organization`
    (houjin-bangou-allが実際に持つ最も具体的な型)の判定なので、鍵が完全
    一致しない。`Organization`は`Agent`のサブクラスなので、サブクラス閉包
    経由でなければ54.9k件の違反がゲートに残ってしまう(実際に踏んだ設計上の罠)。

    **既定は外部知識なし**(`externally_typed=None`/`{}`)。呼び出し側
    (pipeline.py)が全法人ストリームを実行した場合だけ渡す — 黙って
    緩めない(task-8-brief.md 引き継ぐ決定と同じ精神)。
    """
    externally_typed = externally_typed or {}
    reference_classes = _load_reference_classes(shapes_dir)
    ontology = _load_ontology(shapes_dir)

    def _live_type_closure(node: URIRef) -> set[URIRef]:
        return {
            t
            for _s, _p, t, _g in ds.quads((node, RDF.type, None, None))
            if isinstance(t, URIRef)
        }

    def _satisfied_externally(node: URIRef, allowed: set[URIRef]) -> bool:
        for class_uri, membership_test in externally_typed.items():
            if class_uri in allowed and membership_test(node):
                return True
        return False

    violations: list[ReferenceViolation] = []
    for entry in reference_classes:
        path = URIRef(entry["path"])
        expected_class = URIRef(entry["expected_class"])
        allowed = _subclass_closure(ontology, expected_class)

        seen_pairs: set[tuple[URIRef, URIRef]] = set()
        for s, _p, o, _g in ds.quads((None, path, None, None)):
            if not isinstance(o, URIRef):
                continue  # sh:nodeKind sh:IRI がグラフ単位のSHACLで既に担保している
            if (s, o) in seen_pairs:
                continue  # 同じ参照が複数グラフに現れても1件として数える(旧実装と同じ)
            seen_pairs.add((s, o))

            types = _live_type_closure(o)
            if types & allowed:
                continue
            if _satisfied_externally(o, allowed):
                continue
            reason = "型が無い" if not types else "期待クラスのサブクラスでない"
            violations.append(
                ReferenceViolation(
                    path=str(path),
                    expected_class=str(expected_class),
                    subject=str(s),
                    value=str(o),
                    reason=reason,
                )
            )
    return violations


# ファイル名に使えない文字。**Windowsでは `:` が致命的で、`名前:ストリーム名` は
# NTFSの代替データストリーム(ADS)の構文になる。** 既定のベースURIは
# `https://jgkg.norr-tech.com` でポート番号のコロンを含むため、置換しないと
# 隔離した内容が `ls` にも `git status` にも tar にも現れない(`Path.exists()` と
# `stat()` だけは成功するので、返り値を見るテストでは検出できない)。
# Linuxのコロンは合法なので、この差はCIには永久に出ない。
_UNSAFE_IN_FILENAME = '<>:"/\\|?*'


def _safe_stem(graph_uri: str) -> str:
    """グラフURIをどのOSでも実ファイルになる名前に変換する。"""
    stem = graph_uri.rstrip("/").replace("://", "_")
    for ch in _UNSAFE_IN_FILENAME:
        stem = stem.replace(ch, "_")
    # 制御文字も除く(グラフURIに入ることは無いが、名前生成の前提を明示する)
    stem = "".join(c if c.isprintable() else "_" for c in stem)
    # Windowsは末尾のドットと空白を落とすため、名前が変わってしまう
    return stem.rstrip(". ") or "graph"


def quarantine(ds: Dataset, results: list[ValidationResult], out_dir: Path) -> list[Path]:
    """不合格グラフとその違反内容を隔離ディレクトリに書き出す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for r in results:
        if r.conforms:
            continue
        stem = _safe_stem(r.graph_uri)
        nq = out_dir / f"{stem}.nq"
        txt = out_dir / f"{stem}.report.txt"

        g = Graph()
        for triple in ds.graph(URIRef(r.graph_uri)):
            g.add(triple)
        g.serialize(destination=str(nq), format="nt", encoding="utf-8")
        txt.write_text(r.report_text, encoding="utf-8")
        written.extend([nq, txt])
    return written


def passing_dataset(ds: Dataset, results: list[ValidationResult]) -> Dataset:
    """検証を通ったグラフだけを含む新しいDatasetを返す。"""
    failing = {r.graph_uri for r in results if not r.conforms}
    clean = Dataset(default_union=True)
    for ctx in ds.graphs():
        if len(ctx) == 0 or str(ctx.identifier) in failing:
            continue
        target = clean.graph(ctx.identifier)
        for triple in ctx:
            target.add(triple)
    return clean
