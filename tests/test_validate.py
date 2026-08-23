import datetime
from pathlib import Path

import pytest
from rdflib import RDF, Dataset, Literal, URIRef

from jgkg import validate
from jgkg.rdf import emit
from jgkg.transform.law import JurisdictionResult, LawRecord, UnresolvedJurisdiction
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
# 裁定B4: sh:class をSHACLから除去し、参照の型検証はpipelineの和集合ゲートに
# 移す(R2と同じ扱い)。以下3本は裁定B3のゲートテストを裁定B4に合わせて
# 置き換えたもの(履歴は task-4-report.md 参照)。
# =============================================================================


def test_pure_shacl_no_longer_constrains_the_jurisdiction_class():
    """裁定B4後: `law:jurisdiction`にsh:classが無いので、値がMinistry型でも
    SHACL単体(`validate_dataset`)は普通に合格すること。

    旧テスト`test_subclass_value_satisfies_superclass_range`(裁定B3)の
    データ構成をそのまま使う。**合格する理由が変わった**: B3期は
    「ont_graphがサブクラスを辿れたから」、B4後は「sh:classそのものが
    もうSHACLに無いから」。型が本当にOrganizationの一種であることの検証は
    `test_check_reference_integrity_passes_a_correct_cross_graph_reference`
    (和集合ゲート)側に移した。
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
        ministry_code="999",  # 合成コード。013/017/020のような値は使わない(R45)
        name="厚生労働省",
    )

    ds = Dataset(default_union=True)
    _merge_into(ds, emit.emit_laws([record], {law_id: jr}, "egov-law", DAY))
    _merge_into(ds, emit.emit_ministries([ministry], [], "egov-law", DAY))

    results = validate.validate_dataset(ds, SHAPES)
    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [
        r.report_text for r in data_results if not r.conforms
    ]


def test_closed_shapes_still_conform_after_sh_class_extraction():
    """裁定B4でsh:classを抽出・除去した後処理が、Ministry自身の閉じたシェイプに
    無関係な副作用を起こしていないこと(旧`test_closed_shapes_survive_ont_graph`
    の改題。ont_graphはもう無いので、その観点のテストは意味を失った)。
    """
    ministry = Ministry(
        uri="https://jgkg.norr-tech.com/id/org/6000012070001",
        houjin_bangou="6000012070001",
        ministry_code="999",  # 合成コード。013/017/020のような値は使わない(R45)
        name="厚生労働省",
    )
    ds = emit.emit_ministries([ministry], [], "ministry-codes", DAY)

    results = validate.validate_dataset(ds, SHAPES)
    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [
        r.report_text for r in data_results if not r.conforms
    ]


def test_emit_laws_unresolved_jurisdiction_validates_with_unresolved_for(): # 裁定B8
    """未解決の管轄(`core:unresolvedFor`付き)がグラフ単位SHACLに合格すること。

    何があれば落ちるか: `schema/core.yaml` に `unresolvedFor` を足したのに
    `scripts/generate-schema.sh` を再実行し忘れると、`UnresolvedReference` の
    閉じたシェイプが `unresolvedFor` を「宣言されていないプロパティ」として
    不合格にする(このテストが再生成忘れを検出する)。
    """
    law_id = "326M50000400100"
    record = _law_record(law_id, law_num="昭和二十六年大蔵省令第百号")
    jr = JurisdictionResult(
        law_id=law_id,
        ministry_names=["大蔵省"],
        resolved=[],
        unresolved=[UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")],
    )
    ds = emit.emit_laws([record], {law_id: jr}, "egov-law", DAY)

    results = validate.validate_dataset(ds, SHAPES)
    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [
        r.report_text for r in data_results if not r.conforms
    ]


def test_pure_shacl_no_longer_catches_a_wrong_reference_type():
    """裁定B4: `sh:class`をSHACLから抽出済みなので、型が違う参照値でも
    SHACL単体(`validate_dataset`)はもう検出しないこと。

    旧`test_wrong_type_still_fails_the_class_constraint`(裁定B3)は
    「sh:classがまだ効いている」ことを確認していたが、B4はその逆(sh:classが
    もうSHACLに残っていないこと)を確認する必要がある。**このテストが
    落ちたら、schema_lang の抽出漏れでsh:classがまだSHACLに残っている疑いが
    ある**(test_no_self_namespace_sh_class_remains_in_generated_shaclと
    同じ懸念を、データを流して確かめる形)。型を実際に検出する側は
    `test_check_reference_integrity_catches_the_wrong_type` で固定する。
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
    g.add((wrong, RDF.type, core["UnresolvedReference"]))
    g.add((wrong, core["unresolved_text"], Literal("ダミー", lang="ja")))
    g.add((wrong, core["unresolved_reason"], Literal("NO_CANDIDATE")))
    g.add((wrong, core["unresolved_key"], Literal("ダミー")))
    g.add((URIRef(f"https://jgkg.norr-tech.com/id/law/{law_id}"), law["jurisdiction"], wrong))

    results = validate.validate_dataset(ds, SHAPES)
    data_results = [r for r in results if "provenance" not in r.graph_uri]
    # レビュー指摘9: data_results が空だと all(...) が空振りで真になり、
    # 何も検証していないのに合格したように見える(他の2本には既にあるガード)
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), (
        "SHACL単体がまだ型不一致を検出している"
        "(sh:classの抽出漏れの疑いがある): "
        f"{[r.report_text for r in data_results if not r.conforms]}"
    )


# =============================================================================
# 裁定B4本体: check_reference_integrity(和集合ゲート)
# =============================================================================


def test_check_reference_integrity_passes_a_correct_cross_graph_reference():
    """法令グラフと府省グラフが別々の名前付きグラフでも(実運用の形。
    pipeline.pyのsource_id別グラフ構成そのもの)、和集合ゲートは合格すること。

    **これはB3(SHACLのont_graph)では原理的に不合格だったケース**
    (Task 4懸念1で発見したABox欠落)。B3のゲートテストは law/ministry を
    「同じsource_id/fetched_on」にして同一グラフへ強制していたが、ここは
    意図的に別々のsource_id・別々の日付にして、実運用の形を再現する。
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
        ministry_code="999",  # 合成コード。013/017/020のような値は使わない(R45)
        name="厚生労働省",
    )

    ds = Dataset(default_union=True)
    _merge_into(ds, emit.emit_laws([record], {law_id: jr}, "egov-law", DAY))
    _merge_into(
        ds,
        emit.emit_ministries(
            [ministry], [], "ministry-codes", datetime.date(2026, 8, 22)
        ),
    )

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations == [], violations


def test_check_reference_integrity_catches_the_wrong_type():
    """参照先の型を期待クラス(のサブクラス)以外に差し替えると、和集合ゲートが
    違反を報告すること(裁定B4の本体。壊し確認)。

    値ノードは`core:UnresolvedReference`として最小限に妥当なものにする —
    そうしないと値ノード自身の閉じたシェイプ違反(グラフ単位のSHACL側)が
    別に発生し、このテストが確認したい「参照整合ゲートが検出するか」から
    焦点がずれる。
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
    g.add((wrong, RDF.type, core["UnresolvedReference"]))
    g.add((wrong, core["unresolved_text"], Literal("ダミー", lang="ja")))
    g.add((wrong, core["unresolved_reason"], Literal("NO_CANDIDATE")))
    g.add((wrong, core["unresolved_key"], Literal("ダミー")))
    g.add((URIRef(f"https://jgkg.norr-tech.com/id/law/{law_id}"), law["jurisdiction"], wrong))

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations, "型が違う参照が和集合ゲートを素通りしてしまった"
    assert any(
        v.path.endswith("/def/law#jurisdiction")
        and v.expected_class.endswith("/def/org#Organization")
        for v in violations
    ), violations


# =============================================================================
# Task 8: houjin-bangou-all除外機構(裁定B4の拡張。Task 8所有)
#
# 全法人約3,500万トリプル規模の和集合はrdflibに載らないため、
# houjin-bangou-allグラフはこのゲートの対象から明示的に除外できる必要がある
# (Task 8のバッチ検証がその範囲を別途担う)。既定は除外なし(黙って除外しない)。
# =============================================================================


def test_check_reference_integrity_reports_a_violation_inside_a_graph_without_exclusion():
    """否定的コントロール: 除外しなければ、houjin-bangou-all風のグラフ内の
    参照違反もいつもどおり検出されること(除外機構が既定でOFFであることの確認)。
    """
    law_id = "999AC0000000001"
    ds = emit.emit_laws([_law_record(law_id)], {}, "egov-law", DAY)
    all_graph = URIRef("https://jgkg.norr-tech.com/graph/houjin-bangou-all/2026-08-01")
    g = ds.graph(all_graph)
    law = emit.NS["law"]
    typeless = URIRef("https://jgkg.norr-tech.com/id/org/1234567890123")
    g.add((URIRef(f"https://jgkg.norr-tech.com/id/law/{law_id}"), law["jurisdiction"], typeless))

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations, "除外していないのに違反が検出されない"
    assert any(v.value.endswith("1234567890123") for v in violations)


def test_check_reference_integrity_exclude_suppresses_violations_inside_that_graph():
    """`exclude`にグラフURIを渡すと、そのグラフ内の参照はこのゲートの対象外になる。

    何があれば落ちるか: `exclude`が参照元トリプルだけ、または型情報だけの
    片方しか除外しない実装だと、除外したはずのグラフの参照が別の形の違反
    (例: 「型が無い」への化け)として残ってしまう。
    """
    law_id = "999AC0000000001"
    ds = emit.emit_laws([_law_record(law_id)], {}, "egov-law", DAY)
    all_graph_uri = "https://jgkg.norr-tech.com/graph/houjin-bangou-all/2026-08-01"
    g = ds.graph(URIRef(all_graph_uri))
    law = emit.NS["law"]
    typeless = URIRef("https://jgkg.norr-tech.com/id/org/1234567890123")
    g.add((URIRef(f"https://jgkg.norr-tech.com/id/law/{law_id}"), law["jurisdiction"], typeless))

    violations = validate.check_reference_integrity(
        ds, SHAPES, exclude={all_graph_uri: "全法人規模のため和集合ゲートの対象外(Task 8)"}
    )
    assert violations == [], violations


def test_check_reference_integrity_exclude_also_removes_the_type_evidence_from_that_graph():
    """除外したグラフが提供する型情報も一緒に取り除かれること(片側除外の禁止)。

    参照元は除外対象グラフの外にあり、参照先の型だけが除外対象グラフの中に
    ある構成にする。**exclude無し(型が見える)では合格するはずのケース**が、
    「グラフごと存在しないものとして扱う」なら型情報も消えるので、
    「型が無い」という違反に化けることを確認する。
    """
    law_id = "323M60000100010"
    record = _law_record(law_id)
    jr = JurisdictionResult(
        law_id=law_id, ministry_names=["厚生労働省"], resolved=["6000012070001"], unresolved=[],
    )
    all_graph_uri = "https://jgkg.norr-tech.com/graph/houjin-bangou-all/2026-08-01"

    ds = Dataset(default_union=True)
    _merge_into(ds, emit.emit_laws([record], {law_id: jr}, "egov-law", DAY))
    # 型情報(org:Organization)を通常のministry-codesグラフではなく、
    # houjin-bangou-all風のグラフに直接置く(emit_ministriesは"houjin-bangou-all"
    # というsource_idの出典登録を要求するため、ここでは検査対象の型トリプルだけを
    # 直接addする既存テストの作法(test_malformed_houjin_bangou_fails_validation
    # 等と同じ)を使う)
    all_graph = ds.graph(URIRef(all_graph_uri))
    all_graph.add(
        (
            URIRef("https://jgkg.norr-tech.com/id/org/6000012070001"),
            RDF.type,
            URIRef("https://jgkg.norr-tech.com/def/org#Organization"),
        )
    )

    # 除外なしでは、型がどこかのグラフに実在するので合格する(前提の確認)
    assert validate.check_reference_integrity(ds, SHAPES) == []

    violations = validate.check_reference_integrity(
        ds, SHAPES, exclude={all_graph_uri: "型情報の提供元を除外(テスト)"}
    )
    assert violations, "除外したグラフの型情報が別経路(和集合)から見えてしまっている"
    assert any(v.reason == "型が無い" for v in violations), violations


# =============================================================================
# Task 4の申し送り: _load_shapes のモジュールレベルキャッシュ
# =============================================================================


def test_load_shapes_is_cached_across_calls_for_the_same_directory():
    """同じshapes_dirへの2回目の呼び出しは、同じGraphオブジェクトを再利用すること。

    validate_streamは581万件÷batch_sizeの回数だけ_load_shapesを呼ぶため、
    キャッシュが無いとバッチ数に比例してall.shacl.ttlを再パースし続ける
    (実測+25〜30%のコスト。Task 4の申し送り)。
    """
    validate._shapes_cache.clear()
    first = validate._load_shapes(SHAPES)
    second = validate._load_shapes(SHAPES)
    assert first is second, "2回目の呼び出しで再パースが起きている(キャッシュが効いていない)"


def test_load_shapes_cache_key_is_insensitive_to_relative_vs_resolved_path():
    """同じディレクトリを指す表記(相対/絶対)が違っても同じキャッシュ実体を返すこと。"""
    validate._shapes_cache.clear()
    first = validate._load_shapes(SHAPES)
    second = validate._load_shapes(SHAPES.resolve())
    assert first is second


# =============================================================================
# Task 7 Step 6: budgetが入ったことで参照整合ゲートの検査対象が0件でなくなること
#
# Task 7以前は、pipeline.pyがhoujin-bangou/ministry-codesしか流していなかった
# ため、自名前空間への参照述語(law:jurisdiction等)を実際に使うトリプルは
# 生成物に1件も無かった。`check_reference_integrity` はreference-classes.json
# の各エントリについて `ds.subject_objects(path)` を試すが、predicateが
# 1件も無ければ0件のまま「合格」する(空振り。test_pipeline.py
# test_run_reports_no_reference_violations_for_current_pipeline_outputが
# この状態を固定していた)。budgetのministry/recipient/basisLawがこのゲートの
# 初めての実消費者になることを、否定的コントロール(解決済み・違反なし)と
# 肯定的コントロール(型を持たない対象・違反を検出)の対で示す。
# =============================================================================


def _project_record(**overrides):
    from jgkg.transform.rs import BudgetProjectRecord

    defaults = {
        "project_id": "1", "fiscal_year": "2025", "project_name": "内閣人事局経費（研修事業）",
        "ministry_houjin_bangou": "5000012010023", "budget_amount": 34482000, "basis_law_ids": (),
    }
    defaults.update(overrides)
    return BudgetProjectRecord(**defaults)


def _expenditure_record(**overrides):
    from jgkg.transform.rs import ExpenditureRecord

    defaults = {
        "project_id": "1", "fiscal_year": "2025", "seq": 0, "recipient_houjin_bangou": "3010001137944",
        "amount": 3025000, "label": "株式会社ウルフスタイル", "is_bundled": False,
    }
    defaults.update(overrides)
    return ExpenditureRecord(**defaults)


def test_check_reference_integrity_examines_a_resolved_budget_ministry_reference():
    """否定的コントロール: budget:ministryが実際に検査対象になり、解決済みなら

    違反が出ないこと。**検査対象になっていること自体**(ds.subject_objectsが
    空でないこと)を先にassertする — 実装がministry edgeを1本も出さない
    退行をしても`violations == []`だけでは検出できないため。
    """
    ministry = Ministry(
        uri="https://jgkg.norr-tech.com/id/org/5000012010023",
        houjin_bangou="5000012010023", name="内閣官房",
    )
    ds = Dataset(default_union=True)
    _merge_into(ds, emit.emit_ministries([ministry], [], "ministry-codes", datetime.date(2026, 8, 22)))
    _merge_into(ds, emit.emit_budget([_project_record()], [], [], "rs-system", DAY))

    ministry_path = URIRef("https://jgkg.norr-tech.com/def/budget#ministry")
    examined = list(ds.subject_objects(ministry_path))
    assert examined, "budget:ministryのトリプルが1件も無い(検査対象が0件のまま)"

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations == [], violations


def test_check_reference_integrity_examines_unresolved_budget_references_via_entity():
    """否定的コントロール: 未解決のbasis_law/ministryが core:unresolvedFor 経由で

    Entityの検査対象を実際に増やし、違反にならないこと(BudgetProjectは
    core:Entityのサブクラスなので、`unresolvedFor`の期待クラスを満たす)。
    """
    from jgkg.transform.rs import UnresolvedBudgetReference

    unresolved = [
        UnresolvedBudgetReference(
            kind="basis_law", fiscal_year="2025", project_id="1", seq=None,
            key="存在しない法令", reason="NO_CANDIDATE",
        )
    ]
    ds = emit.emit_budget([_project_record(ministry_houjin_bangou=None)], [], unresolved, "rs-system", DAY)

    unresolved_for_path = URIRef("https://jgkg.norr-tech.com/def/core#unresolvedFor")
    assert list(ds.subject_objects(unresolved_for_path)), (
        "core:unresolvedForのトリプルが1件も無い(検査対象が0件のまま)"
    )
    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations == [], violations


def test_check_reference_integrity_catches_a_budget_recipient_pointing_at_a_typeless_organization():
    """肯定的コントロール(壊し確認): budget:recipientが指すOrganizationに

    rdf:type が1つも無い場合、和集合ゲートが違反として検出すること。

    **これは今のPhase 0/1の実運用で実際に起こり得る状態そのものである**:
    houjin-bangouの取り込みは国の機関(kind_code=101)だけをOrganizationとして
    emitする(pipeline.pyのメモリ制約。全法人はTask 8の別グラフの担当)ため、
    支出先の多くを占める民間企業はOrganization型のトリプルを持たない。
    budgetがこのゲートに接続されて初めて、この既知の欠落を機械的に検出できる
    ようになる(Task 7報告書の懸念として記載する対象そのもの)。
    """
    # 意図的にOrganizationの型トリプルを一切emitしない(民間企業は
    # emit_organizationsの対象外という実際のPhase 0/1の状態を再現する)
    ds = emit.emit_budget([], [_expenditure_record()], [], "rs-system", DAY)

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations, "型を持たない支出先への参照が和集合ゲートを素通りしてしまった"
    assert any(
        v.path.endswith("/def/budget#recipient")
        and v.expected_class.endswith("/def/core#Agent")
        for v in violations
    ), violations


def test_check_reference_integrity_raises_if_reference_classes_json_is_missing(tmp_path):
    """`reference-classes.json`が読めなかったら例外にする(空リストで素通ししない)。

    `_assert_shapes_cover`が閉じたシェイプについて防いでいる「対象0件で合格」の
    退化と同じ形の欠陥を、参照整合ゲート側でも防ぐ。
    """
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    with pytest.raises(FileNotFoundError, match="reference-classes.json"):
        validate.check_reference_integrity(ds, tmp_path)


def test_check_reference_integrity_raises_if_reference_classes_json_is_empty(tmp_path):
    """`reference-classes.json`の中身が`[]`でも素通ししない(裁定B9)。

    このスキーマには自名前空間へのsh:class(jurisdiction/involves_agent/
    unresolvedFor)が現に存在するため、空は「抽出対象が無い」という妥当な
    状態ではなく、`schema_lang.process()`の後処理が二重適用された疑いを
    示す。空ファイルを書いてから読ませ、例外になることを確認する
    (OWLファイルは読む前に例外が飛ぶので用意しない)。

    何があれば落ちるか: `_load_reference_classes`が空リストをそのまま返すよう
    退行すると、参照整合ゲートが「チェック対象0件」で常に合格してしまい、
    レビューが実測で確認した非冪等性の穴が再び黙って通る。
    """
    path = tmp_path / validate.REFERENCE_CLASSES_FILENAME
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="二重適用"):
        validate._load_reference_classes(tmp_path)


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
