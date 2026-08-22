"""生成物の整合性テスト。設計書§10の必須項目。"""
from pathlib import Path

import pytest
from rdflib import Graph, OWL, RDF, RDFS, URIRef
from rdflib.namespace import SH, SKOS

GENERATED = Path("schema/generated")
MODULES = ["core"]


def _load(path: Path) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


@pytest.mark.parametrize("module", MODULES)
def test_owl_declares_expected_classes(module):
    g = _load(GENERATED / f"{module}.owl.ttl")
    classes = {str(s) for s in g.subjects(RDF.type, OWL.Class)}
    assert any(c.endswith("#Event") for c in classes), f"Event が宣言されていない: {classes}"
    assert any(c.endswith("#Agent") for c in classes)
    assert any(c.endswith("#UnresolvedReference") for c in classes)


@pytest.mark.parametrize("module", MODULES)
def test_definitions_carry_japanese_language_tag(module):
    """定義文に @ja が付いていること。

    linkml==1.11.1 のCLIには言語タグを付けるオプションが無いため、
    scripts/generate-schema.sh が rdflib で後処理して付けている。
    ここが落ちたら後処理が実行されていない。
    rdfs:label は要素名(ASCII識別子)なので対象にしない。
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


@pytest.mark.parametrize("module", MODULES)
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


@pytest.mark.parametrize("module", MODULES)
def test_pydantic_models_import(module):
    """生成されたPydanticモデルが実際に import できること。"""
    import importlib.util

    path = GENERATED / f"{module}_models.py"
    spec = importlib.util.spec_from_file_location(f"{module}_models", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "Event")
    assert hasattr(mod, "UnresolvedReference")


@pytest.mark.parametrize("module", MODULES)
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


OVERLAY = Path("schema/overlay")


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
        base = "http://localhost:8080/kg/def/"
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
    core = "http://localhost:8080/kg/def/core#"
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
