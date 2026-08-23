"""生成物の整合性テスト。設計書§10の必須項目。"""
from pathlib import Path

import pytest
from rdflib import OWL, RDF, Graph, URIRef
from rdflib.namespace import SH, SKOS

from jgkg import validate

# **cwd に依存させない。** リポジトリ直下以外から pytest を起動したときに
# glob が空になると、パラメータ化したテストが1件も収集されず「合格」に見える。
# テストファイルの位置から解決する(tests/test_base_uri.py と同じ理由)
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = REPO_ROOT / "schema"
GENERATED = SCHEMA / "generated"

# 束ねモジュールの名前は**検証が実際に読むファイル名から導く。** ここを文字列で
# 書くと、シェイプファイルを改名したときに検査対象がずれる
AGGREGATE_MODULE = validate.SHAPES_FILENAME.removesuffix(".shacl.ttl")


def _discover_modules() -> list[str]:
    """`schema/*.yaml` からモジュール名を列挙する。

    **ハードコードしてはならない。** `MODULES = ["core", "org"]` と書いてあったため、
    3つ目のモジュールとして `all.yaml` を作ったときに検査対象へ足し忘れ、
    **検証の唯一の入力である `all.shacl.ttl` / `all.owl.ttl` を誰も見ていない**状態が
    続いた(元レビューI6の指摘1)。Task 8 の「片方をハードコードしていて常に真」と
    同じ型の欠陥で、これが3回目である。集合そのものを
    `test_every_generated_ontology_is_covered_by_a_check` が検査する。
    """
    return sorted(p.stem for p in SCHEMA.glob("*.yaml"))


# 全モジュール(束ねモジュールを含む)。**どのファイルがどの検査を受けるか**を
# ここで明示する:
#
#   ALL_MODULES    … @ja の後処理 / OWLとSHACLのIRI一致
#                    → `all.*` を含む。公開対象そのもので、SHACLゲートの実体だから
#   DOMAIN_MODULES … 自分の名前空間でのクラス宣言 / Pydanticモデル / 名前空間の一致
#                    → `all.yaml` は他モジュールを束ねるだけで自分の名前空間に
#                      クラスを1つも宣言しない(実測で own_ns_classes=0)ため対象外
ALL_MODULES = _discover_modules()
DOMAIN_MODULES = [m for m in ALL_MODULES if m != AGGREGATE_MODULE]

# モジュールごとに「そのモジュール自身が宣言すべきクラス」を明示する。
# import されたクラスは各モジュールのOWL/モデルにも現れるため、共通のクラス名で
# 検査すると org の検査が常に真になり空振りする(実際にそうなっていた)
EXPECTED_CLASSES = {
    "core": ["Agent", "Work", "Place", "Event", "MonetaryItem", "Concept", "UnresolvedReference"],
    "org": ["Organization", "GovernmentOrgan", "Ministry"],
    "law": ["Law", "LawRevision"],
}
EXPECTED_MODELS = {
    "core": ["Event", "UnresolvedReference"],
    "org": ["Organization", "GovernmentOrgan", "Ministry"],
    "law": ["Law", "LawRevision"],
}


def test_every_generated_ontology_is_covered_by_a_check():
    """生成された全OWL/SHACLが、どれかの検査対象に入っていること。

    **モジュールを1つ足したのに検査対象に入らない状態**が起きないことを、
    集合の突き合わせで担保する。左辺は `schema/*.yaml` から、右辺は
    `schema/generated/` の実ファイルから独立に作るので、どちらかだけが増えても落ちる。

    **何があれば落ちるか**: `schema/law.yaml` を足して再生成していない、
    生成物だけあってYAMLが消えている、`_discover_modules` をハードコードに
    戻した、`ALL_MODULES` から束ねモジュールを外した、のいずれでも落ちる。
    """
    assert ALL_MODULES, f"schema/*.yaml が1件も見つからない: {SCHEMA}"
    assert AGGREGATE_MODULE in ALL_MODULES, (
        f"束ねモジュール {AGGREGATE_MODULE!r} が検査対象に入っていない。"
        f" 検出したモジュール: {ALL_MODULES}"
    )
    assert set(DOMAIN_MODULES) | {AGGREGATE_MODULE} == set(ALL_MODULES)

    expected = {GENERATED / f"{m}.{kind}.ttl" for m in ALL_MODULES for kind in ("owl", "shacl")}
    actual = set(GENERATED.glob("*.owl.ttl")) | set(GENERATED.glob("*.shacl.ttl"))
    assert actual == expected, (
        "生成物と検査対象が食い違っている。"
        f" 検査対象なのに無い: {sorted(p.name for p in expected - actual)} /"
        f" 生成物なのに検査対象外: {sorted(p.name for p in actual - expected)}"
    )


def test_expected_class_tables_cover_every_domain_module():
    """`EXPECTED_CLASSES` / `EXPECTED_MODELS` がドメインモジュールを網羅すること。

    **何があれば落ちるか**: 新しいドメインモジュールを足して期待値を書かなければ
    落ちる(KeyErrorで落ちる前に、ここで理由が分かる形で落ちる)。
    """
    assert set(EXPECTED_CLASSES) == set(DOMAIN_MODULES), (
        f"EXPECTED_CLASSES={sorted(EXPECTED_CLASSES)} DOMAIN_MODULES={DOMAIN_MODULES}"
    )
    assert set(EXPECTED_MODELS) == set(DOMAIN_MODULES), (
        f"EXPECTED_MODELS={sorted(EXPECTED_MODELS)} DOMAIN_MODULES={DOMAIN_MODULES}"
    )


def _load(path: Path) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


@pytest.mark.parametrize("module", DOMAIN_MODULES)
def test_owl_declares_expected_classes(module):
    """そのモジュール自身の名前空間でクラスが宣言されていること。

    import されたクラスも各モジュールのOWLに現れるため、名前空間で絞らないと
    「常に真」の空振りテストになる。
    """
    g = _load(GENERATED / f"{module}.owl.ttl")
    declared = {str(s) for s in g.subjects(RDF.type, OWL.Class)}
    ns = f"/def/{module}#"
    own = {c for c in declared if ns in c}
    assert own, f"{module} が自身の名前空間でクラスを宣言していない"
    for name in EXPECTED_CLASSES[module]:
        assert any(c.endswith(f"{ns}{name}") for c in own), (
            f"{module} が自身の名前空間で {name} を宣言していない。宣言済み: {sorted(own)}"
        )


@pytest.mark.parametrize("module", ALL_MODULES)
def test_definitions_carry_japanese_language_tag(module):
    """定義文に @ja が付いていること。

    linkml==1.11.1 のCLIには言語タグを付けるオプションが無いため、
    scripts/generate-schema.sh が rdflib で後処理して付けている。
    ここが落ちたら後処理が実行されていない。
    rdfs:label は要素名(ASCII識別子)なので対象にしない。

    **`all.*` も対象にする(`ALL_MODULES`)。** ここが `["core", "org"]` だった間、
    検証の唯一の入力かつ公開対象そのものである `all.owl.ttl` / `all.shacl.ttl` から
    @ja を全部消しても全テストが緑だった(再レビュー Important 2 の実測)。
    """
    g = _load(GENERATED / f"{module}.owl.ttl")
    definitions = list(g.objects(None, SKOS.definition))
    assert definitions, "skos:definition が出力されていない"
    untagged = [d for d in definitions if getattr(d, "language", None) != "ja"]
    assert not untagged, f"@ja が付いていない定義文がある: {untagged[:3]}"

    # SHACL側も後処理の対象。sh:description は必ず出力され、すべてタグ付きであること
    shapes = _load(GENERATED / f"{module}.shacl.ttl")
    descriptions = list(shapes.objects(None, SH.description))
    assert descriptions, "sh:description が出力されていない"
    untagged_shapes = [d for d in descriptions if getattr(d, "language", None) != "ja"]
    assert not untagged_shapes, f"SHACLに@jaが付いていない説明文がある: {untagged_shapes[:3]}"


@pytest.mark.parametrize("module", ALL_MODULES)
def test_shacl_target_classes_match_owl_classes(module):
    """設計書§10 最重要: SHACLの sh:targetClass と OWLのクラスIRIが一致すること。

    gen-owl の --use-native-uris は既定 True で、gen-shacl は class_uri 側を使う。
    既定のままだと OWL とSHACLが別のIRIを語るため、ここで固定する。
    """
    owl_g = _load(GENERATED / f"{module}.owl.ttl")
    shacl_g = _load(GENERATED / f"{module}.shacl.ttl")

    owl_classes = {str(s) for s in owl_g.subjects(RDF.type, OWL.Class)}
    targets = {str(o) for o in shacl_g.objects(None, SH.targetClass)}

    assert targets, "SHACLに sh:targetClass が無い"
    missing = targets - owl_classes
    assert not missing, (
        f"SHACLが対象にしているクラスがOWLに存在しない: {sorted(missing)}\n"
        f"gen-owl に --no-use-native-uris を付け忘れている可能性がある"
    )


@pytest.mark.parametrize("module", DOMAIN_MODULES)
def test_pydantic_models_import(module):
    """生成されたPydanticモデルが import でき、そのモジュールのクラスを持つこと。"""
    import importlib.util

    path = GENERATED / f"{module}_models.py"
    spec = importlib.util.spec_from_file_location(f"{module}_models", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in EXPECTED_MODELS[module]:
        assert hasattr(mod, name), f"{module}_models に {name} が無い"


@pytest.mark.parametrize("module", DOMAIN_MODULES)
def test_schema_namespace_matches_config_default(module):
    """LinkMLスキーマの名前空間と設定の既定ベースURIが一致すること。

    ここがずれると、SHACLのシェイプがデータと別の名前空間を対象にするため、
    検証が「対象0件で合格」という空振りになる。最も気づきにくい失敗なので
    テストで固定する。ドメイン確定時は schema/*.yaml と config.py の既定値を
    同時に変更する。
    """
    from jgkg.config import Settings

    default_base = Settings.model_fields["base_uri"].default
    g = _load(GENERATED / f"{module}.owl.ttl")
    classes = [str(s) for s in g.subjects(RDF.type, OWL.Class)]
    own = [c for c in classes if c.startswith("http")]
    assert own, "クラスが宣言されていない"
    assert any(c.startswith(f"{default_base}/def/{module}#") for c in own), (
        f"スキーマの名前空間が設定の既定ベースURI({default_base})と一致しない。"
        f" 実際のクラスIRI例: {own[:3]}"
    )


# 検証の唯一の入力。ここに現れないクラスは「何を入れても conforms=True」になる
ALL_SHACL = GENERATED / validate.SHAPES_FILENAME


def _target_classes(path: Path) -> set[str]:
    return {str(o) for o in _load(path).objects(None, SH.targetClass)}


def test_all_shacl_covers_every_module():
    """全モジュールのNodeShapeが `all.shacl.ttl` に入っていること。

    `schema/all.yaml` の imports に新モジュールを足し忘れると、
    **そのクラスの検証だけが静かに消える**(そのグラフは何を入れても
    `conforms=True` になる)。これを強制する装置が無かった(レビューI6)。

    **何があれば落ちるか**: `all.yaml` の imports からモジュールを1つ外したら
    落ちる。新しい `schema/<m>.yaml` を足して imports に書き忘れたら落ちる。
    再生成していなければ落ちる。実行時には
    `validate.validate_dataset` の網羅性ガードが同じずれを捕まえる。
    """
    modules = DOMAIN_MODULES
    assert modules, "schema/*.yaml が1つも見つからない(検査対象が空)"

    all_targets = _target_classes(ALL_SHACL)
    assert all_targets, f"{ALL_SHACL} に sh:targetClass が無い"

    missing: dict[str, list[str]] = {}
    for module in modules:
        path = GENERATED / f"{module}.shacl.ttl"
        assert path.exists(), (
            f"{path} が無い。schema/{module}.yaml を足したなら"
            " scripts/generate-schema.sh を実行してコミットする"
        )
        targets = _target_classes(path)
        assert targets, f"{path} に sh:targetClass が無い"
        gap = sorted(targets - all_targets)
        if gap:
            missing[module] = gap

    assert not missing, (
        f"モジュールのNodeShapeが all.shacl.ttl に入っていない: {missing}。"
        " schema/all.yaml の imports に追加して再生成する"
        "(入っていないクラスの検証は素通しになる)"
    )


def test_all_shacl_covers_the_classes_emitted_by_the_pipeline():
    """パイプラインが実際に出す型が `all.shacl.ttl` の対象になっていること。

    モジュール間の網羅性(上のテスト)とは別に、**出力側から見た網羅性**を見る。
    `emit` が出す型のどれか1つがシェイプの対象から外れると、そのグラフの
    その型は検証されない。
    """
    emitted = {"Organization", "GovernmentOrgan", "Ministry"}
    targets = _target_classes(ALL_SHACL)
    for name in emitted:
        assert any(t.endswith(f"/def/org#{name}") for t in targets), (
            f"emit が出す org:{name} のシェイプが all.shacl.ttl に無い: {sorted(targets)}"
        )
    # レビュー指摘8: emit_laws が出す law:Law / law:LawRevision もこのテストの
    # 対象に含める(org# 限定のループとは別に、law# を明示的に確認する)
    for name in ("Law", "LawRevision"):
        assert any(t.endswith(f"/def/law#{name}") for t in targets), (
            f"emit が出す law:{name} のシェイプが all.shacl.ttl に無い: {sorted(targets)}"
        )
    assert any(t.endswith("/def/core#UnresolvedReference") for t in targets), (
        f"emit が出す core:UnresolvedReference のシェイプが無い: {sorted(targets)}"
    )


OVERLAY = SCHEMA / "overlay"


def test_overlay_terms_all_exist_in_generated_owl():
    """設計書§10: オーバーレイが言及する用語はすべて生成OWLに存在すること。

    存在しない用語への公理は、スキーマへの未反映かタイポである。
    """
    from jgkg.schema_merge import overlay_terms

    owl_g = Graph()
    for p in sorted(GENERATED.glob("*.owl.ttl")):
        owl_g.parse(p, format="turtle")
    declared = {str(s) for s in owl_g.subjects(RDF.type, OWL.Class)}
    declared |= {str(s) for s in owl_g.subjects(RDF.type, OWL.ObjectProperty)}
    declared |= {str(s) for s in owl_g.subjects(RDF.type, OWL.DatatypeProperty)}

    for overlay in sorted(OVERLAY.glob("*.ttl")):
        referenced = overlay_terms(overlay)
        # 自分の名前空間の用語だけを検査する。外部語彙(prov: 等)は対象外
        base = "https://jgkg.norr-tech.com/def/"
        own = {t for t in referenced if t.startswith(base)}
        missing = own - declared
        assert not missing, (
            f"{overlay} が言及する用語が生成OWLに存在しない: {sorted(missing)}"
        )


def test_merged_ontology_contains_both_sources():
    from jgkg.schema_merge import merge_ontology

    merged = merge_ontology(
        generated=sorted(GENERATED.glob("*.owl.ttl")),
        overlay=sorted(OVERLAY.glob("*.ttl")),
    )
    # 生成側由来
    assert (None, RDF.type, OWL.Class) in merged
    # オーバーレイ由来
    assert any(merged.triples((None, OWL.disjointWith, None))), "オーバーレイの公理が入っていない"


def test_overlay_declares_all_axis_disjointness_pairs():
    """6軸+未解決参照の21ペアすべてがdisjointとして宣言されていること。

    手で書くと漏れる。実際に初版では Concept が5軸との排他を落としていた
    (15ペアしか無かった)。件数で固定して再発を防ぐ。
    """
    from itertools import combinations

    from jgkg.schema_merge import merge_ontology

    merged = merge_ontology(
        generated=sorted(GENERATED.glob("*.owl.ttl")),
        overlay=sorted(OVERLAY.glob("*.ttl")),
    )
    core = "https://jgkg.norr-tech.com/def/core#"
    axes = [
        "Agent", "Work", "Place", "Event",
        "MonetaryItem", "Concept", "UnresolvedReference",
    ]

    missing = []
    for a, b in combinations(axes, 2):
        ua, ub = URIRef(core + a), URIRef(core + b)
        # owl:disjointWith は対称なのでどちら向きでも可
        if (ua, OWL.disjointWith, ub) not in merged and (ub, OWL.disjointWith, ua) not in merged:
            missing.append(f"{a}-{b}")

    assert not missing, f"disjointの宣言が無いペアがある({len(missing)}件): {missing}"


# =============================================================================
# 裁定B4: sh:class を自名前空間について除去し、reference-classes.json に移す
# =============================================================================

REFERENCE_CLASSES = GENERATED / "reference-classes.json"


def test_no_self_namespace_sh_class_remains_in_generated_shacl():
    """自名前空間のクラスを指す `sh:class` が、生成された全SHACLから除去
    されていること(裁定B4)。`schema_lang.extract_reference_classes` が
    `reference-classes.json` へ移す。

    **全shapesを走査する。手でプロパティ名をリストしない** — 個々の名前を
    書くと、新しい参照プロパティ(例: 将来の `budget:basisLaw`)が追加された
    ときに検査対象から漏れて、除去し忘れに気づけない。
    """
    base = "https://jgkg.norr-tech.com/def/"
    offending: dict[str, list[str]] = {}
    for path in sorted(GENERATED.glob("*.shacl.ttl")):
        g = _load(path)
        self_ns = {
            str(o)
            for o in g.objects(None, SH["class"])
            if isinstance(o, URIRef) and str(o).startswith(base)
        }
        if self_ns:
            offending[path.name] = sorted(self_ns)
    assert not offending, (
        f"自名前空間へのsh:classが残っているファイルがある: {offending}"
    )


def test_reference_classes_json_contains_the_jurisdiction_pair():
    """`reference-classes.json` に `law:jurisdiction` → `org:Organization` の対が
    入っていること(空でないことも合わせて固定する)。

    **何があれば落ちるか**: `schema_lang` の抽出漏れ、`scripts/generate-schema.sh`
    の再実行忘れ、あるいはファイルが空のまま(「対象0件で合格」の型の退化)で落ちる。
    """
    import json

    assert REFERENCE_CLASSES.exists(), (
        f"{REFERENCE_CLASSES} が無い。scripts/generate-schema.sh を実行する"
    )
    entries = json.loads(REFERENCE_CLASSES.read_text(encoding="utf-8"))
    assert entries, f"{REFERENCE_CLASSES} が空である"

    pairs = {(e["path"], e["expected_class"]) for e in entries}
    assert (
        "https://jgkg.norr-tech.com/def/law#jurisdiction",
        "https://jgkg.norr-tech.com/def/org#Organization",
    ) in pairs, f"jurisdiction→Organizationの対が無い: {sorted(pairs)}"


def test_enum_has_a_single_iri_across_generated_owl():
    """同一の enum が複数のIRIで宣言されていないこと。

    import された enum が import 側の名前空間で再鋳造されると、公開する
    オントロジーの中で同一概念が複数のIRIを持つ。識別子の一貫性を中核に置く
    設計と衝突するため、ここで固定する。
    """
    from collections import defaultdict

    by_local_name: dict[str, set[str]] = defaultdict(set)
    for path in sorted(GENERATED.glob("*.owl.ttl")):
        g = _load(path)
        for s in g.subjects(RDF.type, OWL.Class):
            iri = str(s)
            if "#" not in iri:
                continue
            local = iri.rsplit("#", 1)[1]
            if local.endswith("Enum"):
                by_local_name[local].add(iri)

    conflicts = {name: sorted(iris) for name, iris in by_local_name.items() if len(iris) > 1}
    assert not conflicts, f"同一の enum が複数のIRIで宣言されている: {conflicts}"
