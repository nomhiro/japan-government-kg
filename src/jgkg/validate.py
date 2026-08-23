"""SHACL検証ゲート。不合格のグラフはストアにロードしない(設計書§8.3)。

「一部が壊れていても入れてしまう」ことを許すと、公共財としての信頼性が
最初に崩れる。ここは厳格側に倒す。
"""
from dataclasses import dataclass
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import RDF, Dataset, Graph, URIRef
from rdflib.namespace import SH

from jgkg.config import get_settings


@dataclass(frozen=True)
class ValidationResult:
    graph_uri: str
    conforms: bool
    report_text: str


SHAPES_FILENAME = "all.shacl.ttl"


def _load_shapes(shapes_dir: Path) -> Graph:
    """検証用のSHACLシェイプを読む。

    **モジュール別のSHACLをマージしてはならない。** `org.yaml` は `core` を import する
    ため `org.shacl.ttl` にも core のクラスのNodeShapeが生成される。両方を読むと同一
    クラスに閉じたシェイプが2つ適用され、許可プロパティ集合の積になって偽の違反を
    起こす。全モジュールを束ねた `all.yaml` から生成した単一ファイルだけを読む。
    """
    path = shapes_dir / SHAPES_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"SHACLシェイプが見つからない: {path}。"
            " scripts/generate-schema.sh を実行する"
        )
    shapes = Graph()
    shapes.parse(path, format="turtle")
    return shapes


def _shape_target_classes(shapes: Graph) -> set[URIRef]:
    """シェイプが対象にしているクラスIRIの集合。

    LinkML の gen-shacl が出すのは `sh:targetClass` だけなので、それだけを見る。
    将来 `sh:targetSubjectsOf` 等を手書きで足したら、ここも足す必要がある。
    """
    return {o for o in shapes.objects(None, SH.targetClass) if isinstance(o, URIRef)}


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

        conforms, _report_graph, report_text = shacl_validate(
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
            )
        )
    return results


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
