import datetime
from pathlib import Path

import pytest
from rdflib import RDF, XSD, Dataset, Literal, URIRef
from rdflib.namespace import SKOS

from jgkg import validate
from jgkg.rdf import emit
from jgkg.transform.law import JurisdictionResult, LawRecord, UnresolvedJurisdiction
from jgkg.transform.ministry import Ministry
from jgkg.transform.ministry_succession import AbolishedMinistryRecord
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
# C-3裁定1: org:succeededByも和集合の参照整合ゲート(裁定B4)の対象になること。
#
# **新規のゲートコードは無い。** succeededByのrangeが自名前空間クラス
# (org:GovernmentOrgan)であるため、schema_lang.process()の既存の後処理
# (裁定B4実装(a))が`scripts/generate-schema.sh`実行時に自動でreference-
# classes.jsonへ登録済み(実測: cat schema/generated/reference-classes.json
# で確認)。check_reference_integrity(裁定B4実装(c))はreference-classes.json
# を汎用的に読むだけなので、既にゲートの対象に入っている。以下はそれを
# 実際に確認するテスト(正例2件・反例1件)
# =============================================================================


def test_check_reference_integrity_passes_a_correct_succeeded_by_reference():
    """succeededByが実在するMinistryを指せば和集合ゲートは合格すること。"""
    ministry = Ministry(
        uri="https://jgkg.norr-tech.com/id/org/5000012060001",
        houjin_bangou="5000012060001",
        name="金融庁",
    )
    abolished = AbolishedMinistryRecord(
        name="金融再生委員会",
        successor_houjin_bangou=["5000012060001"],
        abolition_date="2001-01-06",
    )

    ds = Dataset(default_union=True)
    _merge_into(
        ds, emit.emit_ministries([ministry], [], "ministry-codes", datetime.date(2026, 8, 22))
    )
    _merge_into(ds, emit.emit_abolished_ministries([abolished], "egov-law-data", DAY))

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations == [], violations


def test_check_reference_integrity_passes_a_jurisdiction_pointing_at_an_abolished_organ():
    """law:jurisdictionがAbolishedGovernmentOrganを指す場合も合格すること

    (期待クラスはorg:Organizationで、AbolishedGovernmentOrganはその
    サブクラス閉包に含まれる)。C-3裁定2の「所管は当時の組織を指す」形が
    ゲートを通ることの確認。
    """
    law_id = "326M50000400100"
    record = _law_record(law_id, "昭和二十六年大蔵省令第百号")
    jr = JurisdictionResult(
        law_id=law_id, ministry_names=["大蔵省"], resolved=[], resolved_abolished=["大蔵省"],
        unresolved=[],
    )
    abolished = AbolishedMinistryRecord(
        name="大蔵省", successor_houjin_bangou=["2000012050002"], abolition_date="2001-01-06",
    )
    zaimusho = Ministry(
        uri="https://jgkg.norr-tech.com/id/org/2000012050002",
        houjin_bangou="2000012050002",
        name="財務省",
    )

    ds = Dataset(default_union=True)
    _merge_into(ds, emit.emit_laws([record], {law_id: jr}, "egov-law", DAY))
    _merge_into(ds, emit.emit_abolished_ministries([abolished], "egov-law-data", DAY))
    _merge_into(
        ds, emit.emit_ministries([zaimusho], [], "ministry-codes", datetime.date(2026, 8, 22))
    )

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations == [], violations


def test_check_reference_integrity_catches_a_succeeded_by_pointing_at_a_typeless_node():
    """壊し確認: succeededByが型を持たないノードを指せば和集合ゲートが

    違反を報告すること(裁定1本体)。
    """
    abolished = AbolishedMinistryRecord(
        name="金融再生委員会",
        successor_houjin_bangou=["9999999999999"],  # 型付けされたグラフに存在しない
        abolition_date="2001-01-06",
    )
    ds = emit.emit_abolished_ministries([abolished], "egov-law-data", DAY)

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations, "型の無いsucceededByの参照先が和集合ゲートを素通りしてしまった"
    assert any(
        v.path.endswith("/def/org#succeededBy")
        and v.expected_class.endswith("/def/org#GovernmentOrgan")
        for v in violations
    ), violations


# =============================================================================
# 裁定B21: externally_typed(Task 8の`exclude`機構を置き換える。Task 10所有)
#
# 全法人約3,500万トリプル規模の和集合はrdflibに載らないため、houjin-bangou-all
# の内容は和集合には無い。Task 8時代の`exclude`(グラフを検査対象から除く)は
# 54.9k件規模の実参照(budget:recipient)を丸ごと検査放棄することになると
# 判明し(裁定B21)、「rdflibに載せていない事実を外部知識として検査に使う」
# `externally_typed`に置き換えた。既定は外部知識なし(黙って緩めない)。
# =============================================================================


def test_check_reference_integrity_reports_a_violation_without_external_knowledge():
    """否定的コントロール: 外部知識を渡さなければ、型を持たない参照先への

    参照はいつもどおり違反として検出されること(externally_typedが既定で
    空であることの確認)。
    """
    law_id = "999AC0000000001"
    ds = emit.emit_laws([_law_record(law_id)], {}, "egov-law", DAY)
    gid = URIRef("https://jgkg.norr-tech.com/graph/egov-law/2026-08-01")
    g = ds.graph(gid)
    law = emit.NS["law"]
    typeless = URIRef("https://jgkg.norr-tech.com/id/org/1234567890123")
    g.add((URIRef(f"https://jgkg.norr-tech.com/id/law/{law_id}"), law["jurisdiction"], typeless))

    violations = validate.check_reference_integrity(ds, SHAPES)
    assert violations, "外部知識が無いのに違反が検出されない"
    assert any(v.value.endswith("1234567890123") for v in violations)


def test_check_reference_integrity_externally_typed_resolves_a_budget_recipient_via_subclass_closure():
    """B21の中心: `budget:recipient`の期待クラスは`core:Agent`だが、外部知識

    (houjin-bangou-allが実際に持つ最も具体的な型)のキーは`org:Organization`
    であり、両者は文字列としては一致しない。**サブクラス閉包を経由しないと
    (`externally_typed.get(expected_class)`のような単純な辞書一致だと)この
    54.9k件規模の実際のケースは1件も解決できない**(advisorレビューで指摘された、
    最初の実装が持っていたバグそのものを固定する壊し確認)。
    """
    recipient_bangou = "3010001137944"  # _expenditure_record() の既定値
    # ministry_houjin_bangou=None にして budget:ministry 由来の別の違反を
    # 混ぜない(recipient経由の外部知識だけに焦点を絞る)。budget:project の
    # 参照先(BudgetProject自身)は projects=[_project_record(...)] を渡して
    # 実在させる(でなければ`budget:project`側の「型が無い」違反が別途残り、
    # `violations == []` を検証できない)
    ds = emit.emit_budget(
        [_project_record(ministry_houjin_bangou=None)],
        [_expenditure_record()],
        [],
        "rs-system",
        DAY,
    )
    org_ns = emit.NS["org"]
    recipient_uri = URIRef(f"https://jgkg.norr-tech.com/id/org/{recipient_bangou}")

    # 前提: 外部知識が無ければ違反になる(型を持たない民間企業への参照)
    assert validate.check_reference_integrity(ds, SHAPES), "前提が崩れている"

    violations = validate.check_reference_integrity(
        ds,
        SHAPES,
        externally_typed={org_ns["Organization"]: lambda uri, _t=recipient_uri: uri == _t},
    )
    assert violations == [], violations


def test_check_reference_integrity_externally_typed_still_flags_when_membership_test_says_no():
    """`externally_typed`を渡しても、membership_testが偽を返す参照は違反のまま残ること。

    何があれば落ちるか: `externally_typed`のキーが`allowed`に含まれることだけを
    見て、`membership_test`自体の戻り値を無視する実装だと、無関係な集合を
    渡すだけで全ての違反が消えてしまう。
    """
    ds = emit.emit_budget([], [_expenditure_record()], [], "rs-system", DAY)
    org_ns = emit.NS["org"]

    violations = validate.check_reference_integrity(
        ds, SHAPES, externally_typed={org_ns["Organization"]: lambda uri: False}
    )
    assert violations, "membership_testが常にFalseを返すのに違反が消えてしまった"


def test_check_reference_integrity_externally_typed_key_matching_the_expected_class_itself_works_too():
    """外部知識のキーが期待クラスそのもの(サブクラスを介さない直接一致)でも効くこと。"""
    law_id = "323M60000100010"
    record = _law_record(law_id)
    jr = JurisdictionResult(
        law_id=law_id, ministry_names=["厚生労働省"], resolved=["6000012070001"], unresolved=[],
    )
    ds = emit.emit_laws([record], {law_id: jr}, "egov-law", DAY)
    org_ns = emit.NS["org"]
    ministry_uri = URIRef("https://jgkg.norr-tech.com/id/org/6000012070001")

    violations = validate.check_reference_integrity(
        ds,
        SHAPES,
        externally_typed={org_ns["Organization"]: lambda uri, _t=ministry_uri: uri == _t},
    )
    assert violations == [], violations


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
        "recipient_match_category": "resolved",
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


def test_fullwidth_digit_houjin_bangou_fails_shacl_validation():
    """全角数字13桁のhoujinBangouもSHACLで不合格になること(裁定B22)。

    再生成前(pattern: "^\\d{13}$")では全角数字も`\\d`にマッチしてしまい、
    このデータはSHACL単体では**合格していた**(実測で確認済みの退行 —
    このテストは壊れた状態の鏡像: `schema/org.yaml`のpatternを`[0-9]`に
    固定し再生成した後でなければ、このテストはfailingが空のまま落ちる)。
    """
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    gid = URIRef("https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-01")
    g = ds.graph(gid)
    bad = URIRef("https://jgkg.norr-tech.com/id/org/9999999999999")
    ns = emit.NS["org"]
    g.add((bad, RDF.type, ns["Organization"]))
    # "9999999999999" の全角表記。桁数は13桁で見た目は数字だが、ASCII固定の
    # `[0-9]{13}$`にはマッチしない
    g.add((bad, ns["houjinBangou"], Literal("９９９９９９９９９９９９９")))

    results = validate.validate_dataset(ds, SHAPES)
    failing = [r for r in results if not r.conforms]
    assert failing, "全角数字の法人番号がSHACL検証を通ってしまった(patternのASCII固定が効いていない)"


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


# =============================================================================
# AbolishedGovernmentOrgan(C-2)。succeededBy・abolitionDateの必須制約と
# 閉じた形状が生成されたttlの文字列だけでなく、実際のSHACL検証で効くこと。
# ここでは`emit.emit_abolished_ministries`(C-3で追加)を経由せず、SHACLの
# 挙動そのものを狙って壊すためにトリプルを直接組み立てる(閉じた形状の
# 壊し確認は、実際のemit関数からは出ない「無関係なプロパティ」を意図的に
# 足す必要があるため)
# =============================================================================

_ABOLISHED_SUBJECT = "https://jgkg.norr-tech.com/id/org/test-old-ministry"
_ABOLISHED_GRAPH = URIRef("https://jgkg.norr-tech.com/graph/test-abolished/2026-08-26")


def _abolished_organ_dataset(
    successors: list[str], abolition_date: datetime.date | None, extra_undeclared_property: bool = False,
) -> Dataset:
    ds = Dataset()
    g = ds.graph(_ABOLISHED_GRAPH)
    ns_org = emit.NS["org"]
    subj = URIRef(_ABOLISHED_SUBJECT)
    g.add((subj, RDF.type, ns_org["AbolishedGovernmentOrgan"]))
    g.add((subj, SKOS.prefLabel, Literal("テスト用の廃止組織", lang="ja")))
    for succ in successors:
        g.add((subj, ns_org["succeededBy"], URIRef(succ)))
    if abolition_date is not None:
        g.add((subj, ns_org["abolitionDate"], Literal(abolition_date, datatype=XSD.date)))
    if extra_undeclared_property:
        # AbolishedGovernmentOrganが宣言していない、無関係なプロパティ
        # (law:lawId)を1つ足す。閉じた形状(sh:closed true)が実際に
        # 効くかどうかの検査
        g.add((subj, emit.NS["law"]["lawId"], Literal("NOT-A-DECLARED-PROPERTY")))
    return ds


def test_abolished_government_organ_with_both_required_fields_conforms():
    """完全な形(succeededBy 1件以上・abolitionDateあり)は合格すること。

    これが落ちると、以降の3件の壊し確認が「常に不合格」という別の欠陥で
    空虚に成功してしまう(何を変えても不合格なら、要求している制約を
    検査したことにならない)。
    """
    ds = _abolished_organ_dataset(
        successors=["https://jgkg.norr-tech.com/id/org/test-new-ministry"],
        abolition_date=datetime.date(2001, 1, 6),
    )
    results = validate.validate_dataset(ds, SHAPES)
    assert results, "検証対象のグラフが無い"
    assert all(r.conforms for r in results), [r.report_text for r in results if not r.conforms]


def test_abolished_government_organ_without_succeeded_by_fails_validation():
    """壊し確認: succeededByが必須(多値・minCount 1)であることが、生成された

    ttlの文字列を見るだけでなく、実際にpyshaclを走らせて効くこと。
    """
    ds = _abolished_organ_dataset(successors=[], abolition_date=datetime.date(2001, 1, 6))
    results = validate.validate_dataset(ds, SHAPES)
    assert results, "検証対象のグラフが無い"
    assert not any(r.conforms for r in results), [r.report_text for r in results]


def test_abolished_government_organ_without_abolition_date_fails_validation():
    """壊し確認: abolitionDateが必須であることが実際にpyshaclで効くこと。"""
    ds = _abolished_organ_dataset(
        successors=["https://jgkg.norr-tech.com/id/org/test-new-ministry"],
        abolition_date=None,
    )
    results = validate.validate_dataset(ds, SHAPES)
    assert results, "検証対象のグラフが無い"
    assert not any(r.conforms for r in results), [r.report_text for r in results]


def test_abolished_government_organ_shape_is_closed():
    """壊し確認: 閉じた形状(sh:closed true)が実際に効くこと。

    AbolishedGovernmentOrganが宣言していない任意のプロパティ(law:lawId)を
    1つ足すと不合格になる。
    """
    ds = _abolished_organ_dataset(
        successors=["https://jgkg.norr-tech.com/id/org/test-new-ministry"],
        abolition_date=datetime.date(2001, 1, 6),
        extra_undeclared_property=True,
    )
    results = validate.validate_dataset(ds, SHAPES)
    assert results, "検証対象のグラフが無い"
    assert not any(r.conforms for r in results), [r.report_text for r in results]
