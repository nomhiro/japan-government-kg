"""SHACL検証ゲート。不合格のグラフはストアにロードしない(設計書§8.3)。

「一部が壊れていても入れてしまう」ことを許すと、公共財としての信頼性が
最初に崩れる。ここは厳格側に倒す。
"""
import json
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
    report_text: str


SHAPES_FILENAME = "all.shacl.ttl"
ONTOLOGY_FILENAME = "all.owl.ttl"


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

    **読めなかったら例外にする。** 空リストで素通りすると、`_assert_shapes_cover`
    が閉じたシェイプで防いでいる「対象0件で合格」の退化と同じ形になる —
    このファイルは消費者(このゲート)と同時に`scripts/generate-schema.sh`が
    生成するので、無いのは生成し忘れである。ファイルの中身が`[]`(有効なJSON
    だが0件)であること自体は不正ではない(自名前空間を指す`sh:class`が
    スキーマに1つも無ければ、それが正しい状態)。
    """
    path = shapes_dir / REFERENCE_CLASSES_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"{path} が無い。scripts/generate-schema.sh を実行する"
            "(schema_lang が sh:class から参照制約を抽出してこのファイルに書く)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


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


def check_reference_integrity(ds: Dataset, shapes_dir: Path) -> list[ReferenceViolation]:
    """自名前空間クラスへの参照(`sh:class`から抽出したもの)を和集合で検査する。

    **裁定B4(R2と同じ扱い)。** グラフを跨ぐ制約はグラフ単位のSHACL検証
    (`validate_dataset`)では原理的に検証できない — `org:houjinBangou`の
    必須制約がCQのSPARQLテストで担保されているのと同じ理由(設計書R2)。
    法令(`law:jurisdiction`)とその参照先の府省の型が別々の名前付きグラフに
    分かれる実運用(pipeline.pyの`source_id`別グラフ構成そのもの)では、
    参照先の型がその名前付きグラフの中に存在しないため、グラフ単位の
    `sh:class`は原理的に満たせない(Task 4 懸念1で発見したABox欠落)。
    `ds`は`default_union=True`のDataset(全グラフの和集合)を渡すこと。

    **houjin-all(Task 8の全法人グラフ)の内部参照はこのゲートの対象外
    にする設計である。** 全法人約3,500万トリプル規模の和集合はrdflibに
    載らないため、Task 8は自分のバッチ経路でこの検査を別途行う必要がある
    (このゲート自体には除外機構をまだ作り込んでいない — 対象を広げる前に
    Task 8側で規模に応じた方式を決める)。
    """
    reference_classes = _load_reference_classes(shapes_dir)
    ontology = _load_ontology(shapes_dir)

    violations: list[ReferenceViolation] = []
    for entry in reference_classes:
        path = URIRef(entry["path"])
        expected_class = URIRef(entry["expected_class"])
        allowed = _subclass_closure(ontology, expected_class)
        for s, o in ds.subject_objects(path):
            if not isinstance(o, URIRef):
                continue  # sh:nodeKind sh:IRI がグラフ単位のSHACLで既に担保している
            types = set(ds.objects(o, RDF.type))
            if types & allowed:
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
