import datetime
from pathlib import Path

import pytest
from rdflib import RDF, Dataset, Literal, URIRef

from jgkg import validate
from jgkg.rdf import emit
from jgkg.transform.law import JurisdictionResult, LawRecord
from jgkg.transform.ministry import Ministry
from jgkg.transform.organization import Organization

DAY = datetime.date(2026, 8, 1)
SHAPES = Path("schema/generated")
# ドリフト検査用の別ベースURI。IRIを文字列リテラルで書かないのは、
# tests/*.py 自体が jgkg.base_uri の整合検査の対象だから(test_base_uri.py 参照)
DRIFT_BASE = "https://example.test/drift-kg"
# Windowsがファイル名に使えない文字。**実装の `_UNSAFE_IN_FILENAME` から
# 導出してはならない。** 導出すると、定数から1文字外したときテストの入力からも
# 消えて常に合格する(fixtureを COL から逆算したのと同じ円環。実際に一度作った)。
# 出典: Windowsのファイル名規則(予約文字9種のうち、パス区切りを含む)
WINDOWS_RESERVED = '<>:"/\\|?*'


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _valid_org():
    return Organization(
        uri="https://jgkg.norr-tech.com/id/org/6000012070001",
        houjin_bangou="6000012070001",
        name="厚生労働省",
        kind_code="101",
        is_government_organ=True,
    )


def _law_record(law_id: str, law_num: str = "令和七年厚生労働省令第十号", **overrides) -> LawRecord:
    defaults: dict = {
        "law_num_type": "MinisterialOrdinance",
        "law_type": "MinisterialOrdinance",
        "law_title": "テスト用の題名",
        "abbrev": [],
        "promulgation_date": "2020-01-01",
        "repeal_status": "None",
        "revisions": [],
    }
    defaults.update(overrides)
    return LawRecord(law_id=law_id, law_num=law_num, **defaults)


def _merge_into(target: Dataset, source: Dataset) -> None:
    for ctx in source.graphs():
        if len(ctx) == 0:
            continue
        g = target.graph(ctx.identifier)
        for triple in ctx:
            g.add(triple)


def test_valid_dataset_conforms():
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    results = validate.validate_dataset(ds, SHAPES)

    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [r.report_text for r in data_results if not r.conforms]


# =============================================================================
# 裁定B3: ont_graph(inferenceなし)でも sh:class がサブクラスを辿れること
# =============================================================================


def test_subclass_value_satisfies_superclass_range():
    """`law:jurisdiction`(range: Organization)の値がMinistry型でも通ること(B3の本体)。

    Ministryの型トリプルとjurisdictionのトリプルを**同一グラフ**に置く
    (source_id/fetched_onを揃えて強制する)。`org:Ministry`は`org:Organization`の
    サブクラスだが、その`rdfs:subClassOf`知識はデータグラフにはなく
    `all.owl.ttl`にしかない。

    何があれば落ちるか: `validate_dataset`が`ont_graph`を渡していない
    (または渡していても機能していない)と、値ノードの型が`org:Ministry`
    としか分からず`sh:class org:Organization`に違反し続ける。
    """
    law_id = "323M60000100010"
    record = _law_record(law_id)
    jr = JurisdictionResult(
        law_id=law_id,
        ministry_names=["厚生労働省"],
        resolved=["6000012070001"],
        unresolved=[],
    )
    ministry = Ministry(
        uri="https://jgkg.norr-tech.com/id/org/6000012070001",
        houjin_bangou="6000012070001",
        ministry_code="020",
        name="厚生労働省",
    )

    ds = Dataset(default_union=True)
    # 同じsource_id/fetched_onにして、law と ministry を強制的に同一グラフへ入れる
    _merge_into(ds, emit.emit_laws([record], {law_id: jr}, "egov-law", DAY))
    _merge_into(ds, emit.emit_ministries([ministry], [], "egov-law", DAY))

    results = validate.validate_dataset(ds, SHAPES)
    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [
        r.report_text for r in data_results if not r.conforms
    ]


def test_closed_shapes_survive_ont_graph():
    """`ont_graph`を渡しても、Ministry自身の閉じたシェイプが偽の違反を出さないこと。

    何があれば落ちるか: `ont_graph`の導入で`org:Organization`の閉じたシェイプが
    (サブクラスだからという理由で)`org:Ministry`型のノードにも適用される
    ようになると、Ministry固有の`ministryCode`が「宣言されていないプロパティ」
    として誤って違反になる(Phase 0のR24と同種の、推論経由の二重シェイプ問題)。
    このテストは既存の`test_valid_dataset_conforms`が`org:Organization`しか
    検証していない(`org:Ministry`を検証していない)穴を塞ぐ。
    """
    ministry = Ministry(
        uri="https://jgkg.norr-tech.com/id/org/6000012070001",
        houjin_bangou="6000012070001",
        ministry_code="020",
        name="厚生労働省",
    )
    ds = emit.emit_ministries([ministry], [], "ministry-codes", DAY)

    results = validate.validate_dataset(ds, SHAPES)
    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [
        r.report_text for r in data_results if not r.conforms
    ]


def test_wrong_type_still_fails_the_class_constraint():
    """`org:Organization`のどのサブクラスでもない値は、`ont_graph`を渡しても
    `sh:class`に違反し続けること(`sh:class`が死んでいない証拠)。

    値ノード自身は`core:UnresolvedReference`として最小限に妥当なものにする
    (閉じたシェイプの必須プロパティを満たす)。**そうしないと、値ノード自身の
    閉じたシェイプ違反がconforms=Falseの原因になり、sh:classが実際に発火した
    かどうかが分からなくなる**(何があれば落ちるか、を測るテスト自体の穴)。
    """
    law_id = "999AC0000000001"
    ds = emit.emit_laws([_law_record(law_id)], {}, "egov-law", DAY)

    gid = URIRef("https://jgkg.norr-tech.com/graph/egov-law/2026-08-01")
    g = ds.graph(gid)
    core = emit.NS["core"]
    law = emit.NS["law"]
    wrong = URIRef(
        "https://jgkg.norr-tech.com/id/unresolved/jurisdiction/999AC0000000001/dummy"
    )
    # core:UnresolvedReference として最小限に妥当(必須プロパティを埋める)
    g.add((wrong, RDF.type, core["UnresolvedReference"]))
    g.add((wrong, core["unresolved_text"], Literal("ダミー", lang="ja")))
    g.add((wrong, core["unresolved_reason"], Literal("NO_CANDIDATE")))
    g.add((wrong, core["unresolved_key"], Literal("ダミー")))
    # law:jurisdiction を、Organizationでも何のサブクラスでもないこのノードへ張る
    g.add((URIRef(f"https://jgkg.norr-tech.com/id/law/{law_id}"), law["jurisdiction"], wrong))

    results = validate.validate_dataset(ds, SHAPES)
    data_results = [r for r in results if "provenance" not in r.graph_uri]
    failing = [r for r in data_results if not r.conforms]
    assert failing, "Organizationでない値がsh:classを素通りしてしまった"
    assert any("ClassConstraintComponent" in r.report_text for r in failing), (
        "落ちてはいるが、sh:classではない別の理由で落ちている可能性がある: "
        f"{[r.report_text for r in failing]}"
    )


def test_malformed_houjin_bangou_fails_validation():
    """法人番号のパターン制約に違反するデータは不合格になること。"""
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    gid = URIRef("https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-01")
    g = ds.graph(gid)
    bad = URIRef("https://jgkg.norr-tech.com/id/org/9999999999999")
    ns = emit.NS["org"]
    g.add((bad, RDF.type, ns["Organization"]))
    g.add((bad, ns["houjinBangou"], Literal("BROKEN")))

    results = validate.validate_dataset(ds, SHAPES)
    failing = [r for r in results if not r.conforms]
    assert failing, "不正な法人番号が検証を通ってしまった"


def test_quarantine_writes_failing_graphs(tmp_path):
    ds = Dataset()
    gid = URIRef("https://jgkg.norr-tech.com/graph/broken/2026-08-01")
    g = ds.graph(gid)
    ns = emit.NS["org"]
    subj = URIRef("https://jgkg.norr-tech.com/id/org/1")
    g.add((subj, RDF.type, ns["Organization"]))
    g.add((subj, ns["houjinBangou"], Literal("NOPE")))

    results = validate.validate_dataset(ds, SHAPES)
    written = validate.quarantine(ds, results, tmp_path)

    assert written, "隔離ファイルが書かれていない"
    assert any(p.suffix == ".txt" for p in written), "違反内容の報告が書かれていない"

    # **返り値の Path を見るだけでは足りない。** Windowsでは名前にコロンが残ると
    # NTFSの代替データストリームになり、`exists()` も `stat()` も成功するのに
    # ディレクトリを列挙すると 0 バイトのファイル1個しか見えない。
    # ディレクトリの実際の中身とサイズで確認する
    on_disk = sorted(p.name for p in tmp_path.iterdir())
    assert on_disk == sorted(p.name for p in written), (
        f"返り値と実際のディレクトリの中身が違う: written={sorted(p.name for p in written)}"
        f" iterdir={on_disk}"
    )
    for p in tmp_path.iterdir():
        assert p.is_file(), f"{p} が通常ファイルでない"
        assert p.stat().st_size > 0, f"{p} が空である(内容がADSに消えている疑い)"

    # ADSはWindows固有なので、Linuxでも再発を検出できるように名前そのものを見る。
    # 既定のベースURIはポート番号のコロンを含むので、置換されていなければ落ちる
    for p in written:
        illegal = set(p.name) & set('<>:"|?*\\')
        assert not illegal, f"ファイル名に使えない文字が残っている: {p.name} ({illegal})"


def test_safe_stem_replaces_every_windows_reserved_character():
    """名前生成が予約文字を残さないこと。

    **何があれば落ちるか**: `_UNSAFE_IN_FILENAME` からどれか1文字を外したら落ちる。
    入力には**予約文字を1文字ずつ全部**入れる。以前はバックスラッシュが入力に
    無かったため、`\\` だけを置換対象から外しても落ちなかった(再レビュー Minor 1)。
    """
    # 実装の定数を**参照して合格させないこと**を先に固定する。
    # `set(WINDOWS_RESERVED) <= set(_UNSAFE_IN_FILENAME)` が、定数から1文字
    # 外したことを直接検出する
    assert set(WINDOWS_RESERVED) <= set(validate._UNSAFE_IN_FILENAME), (
        f"置換対象から漏れている文字がある: "
        f"{sorted(set(WINDOWS_RESERVED) - set(validate._UNSAFE_IN_FILENAME))}"
    )

    body = "".join(f"a{ch}" for ch in WINDOWS_RESERVED)
    stem = validate._safe_stem(f"https://jgkg.norr-tech.com/graph/{body}/2026-08-01")
    assert not set(stem) & set(WINDOWS_RESERVED), stem
    assert stem.endswith("2026-08-01")


def test_namespace_drift_raises_instead_of_passing_with_zero_targets(monkeypatch):
    """ベースURIがずれたら例外になること(「対象0件で合格」に退化しないこと)。

    設計書§4.2の手順どおり `.env` の `JGKG_BASE_URI` を変えても、生成済みの
    `all.shacl.ttl` の `sh:targetClass` は旧名前空間のままである。この状態では
    どのシェイプもどのノードも対象にせず、**明白な違反を含むグラフが
    `conforms=True` になる**。それを例外に変える。

    **何があれば落ちるか**: `validate_dataset` の `_assert_shapes_cover` を外すか、
    シェイプの対象クラス集合の取り方を間違えたら落ちる(例外が出なくなる)。
    """
    monkeypatch.setenv("JGKG_BASE_URI", DRIFT_BASE)
    from jgkg.config import get_settings
    get_settings.cache_clear()

    # 新しい名前空間で、しかも明白な sh:pattern 違反を含むデータを作る
    org = Organization(
        uri=f"{DRIFT_BASE}/id/org/6000012070001",
        houjin_bangou="これは法人番号ではない",
        name="厚生労働省",
        kind_code="101",
        is_government_organ=True,
    )
    ds = emit.emit_organizations([org], "houjin-bangou", DAY)

    with pytest.raises(ValueError, match="対応するSHACLシェイプが1つも無い"):
        validate.validate_dataset(ds, SHAPES)


def test_provenance_only_graph_is_not_flagged_by_the_coverage_guard():
    """`rdf:type` を持たない出典グラフは網羅性ガードの対象外であること。

    ガードを「対象ノードが0なら例外」と素朴に書くと、自オントロジーのクラスを
    1つも名指ししない出典グラフで必ず例外になる。**何があれば落ちるか**:
    ガードの条件を `declared` の有無ではなく対象ノード数だけで判定したら落ちる。
    """
    ds = emit.emit_organizations([], "houjin-bangou", DAY)
    results = validate.validate_dataset(ds, SHAPES)

    graphs = {r.graph_uri for r in results}
    assert any("provenance" in g for g in graphs), f"出典グラフが検証されていない: {graphs}"
    assert all(r.conforms for r in results)


def test_passing_dataset_excludes_failing_graphs():
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    broken_gid = URIRef("https://jgkg.norr-tech.com/graph/broken/2026-08-01")
    bg = ds.graph(broken_gid)
    ns = emit.NS["org"]
    subj = URIRef("https://jgkg.norr-tech.com/id/org/2")
    bg.add((subj, RDF.type, ns["Organization"]))
    bg.add((subj, ns["houjinBangou"], Literal("NOPE")))

    results = validate.validate_dataset(ds, SHAPES)
    clean = validate.passing_dataset(ds, results)

    contexts = {str(c.identifier) for c in clean.graphs() if len(c) > 0}
    assert str(broken_gid) not in contexts, "不合格グラフがロード対象に残っている"
