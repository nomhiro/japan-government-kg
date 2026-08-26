"""経路1(法令番号→府省)の変換。tests/fixtures/egov_laws_page*.json と同じ、
実在の法令の実例を使う(R45)。
"""
import json
from pathlib import Path

import pytest

from jgkg.transform.law import (
    EXTRACTION_FAILED,
    JurisdictionResult,
    LawRecord,
    UnresolvedJurisdiction,
    derive_jurisdiction,
    extract_ministry_names,
    parse_laws,
    to_ministry_reference,
)
from jgkg.transform.ministry import Ministry
from jgkg.transform.old_ministries import DEFAULT_PATH as OLD_MINISTRIES_PATH
from jgkg.transform.old_ministries import load_old_ministries

# =============================================================================
# Step 1/2: 抽出
# =============================================================================

# (law_num, 期待する抽出名リスト。None=経路1の対象外)
# ブリーフ(task-4-brief.md Step 1)からそのまま引用した実在の法令番号
CASES = [
    ("令和七年厚生労働省令第十号", ["厚生労働省"]),
    ("平成十三年総務省令第一号", ["総務省"]),
    ("平成十二年総理府・大蔵省令第三号", ["総理府", "大蔵省"]),  # 共同省令
    ("昭和二十六年大蔵省令第百号", ["大蔵省"]),  # 旧省庁
    ("明治二十二年閣令第十二号", ["閣"]),  # 閣令(旧)
    ("人事院規則一―四", ["人事院"]),  # 規則
    ("令和三年法律第三十六号", None),  # 対象外(法律)
    ("平成九年政令第二百七号", None),  # 対象外(政令)
]


@pytest.mark.parametrize("law_num,expected", CASES)
def test_extract_ministry_names(law_num, expected):
    assert extract_ministry_names(law_num) == expected


def test_extract_ministry_names_none_cases_are_asserted_individually():
    """対象外(None)のケースを個別に確認する。

    何があれば落ちるか: 「対象外をスキップするループ」に退化すると、全部が
    Noneであっても(何も抽出されなくても)テストが合格してしまう。
    ここでは None になるはずの入力を明示的に集めて、実際に None であることを
    1件ずつ assert する。
    """
    none_cases = [law_num for law_num, expected in CASES if expected is None]
    assert none_cases, "対象外のケースが1件も無い(CASESの記述が壊れている)"
    for law_num in none_cases:
        result = extract_ministry_names(law_num)
        assert result is None, f"{law_num!r} は対象外のはずが {result!r} を抽出した"


# =============================================================================
# レビュー指摘1・2・6(修正ラウンド3): 抽出段の取りこぼし
# =============================================================================

# 元年表記。「平成元年」等は法令番号の公式表記(「平成一年」とは書かない)。
# ただしこの特定の組み合わせ(府省・号数)が実在するかはローカルでは確認できない
# ため、CASES(実在確認済み)には入れず、表記パターンの検査として別に置く
# (レビュー指摘1が実測した3例そのもの。Task 11で実データを確認する)
GANNEN_CASES = [
    ("令和元年厚生労働省令第一号", ["厚生労働省"]),
    ("平成元年大蔵省令第一号", ["大蔵省"]),
    ("昭和元年内務省令第一号", ["内務省"]),
]


@pytest.mark.parametrize("law_num,expected", GANNEN_CASES)
def test_extract_ministry_names_handles_gannen_year(law_num, expected):
    """`_KANJI_NUM` に「元」が無いと元年の府省令が抽出できない(指摘1)。

    何があれば落ちるか: `_KANJI_NUM` から「元」を外すと、この3例すべてが
    (resolvedでもunresolvedでもない)対象外の`None`に落ちて、経路1の
    計数から静かに消える。
    """
    assert extract_ministry_names(law_num) == expected


def test_extract_ministry_names_recovers_co_jurisdiction_with_committee_or_inspectorate():
    """共管の1区分が「委員会」「院」で終わる場合も、共管全体を捨てずに抽出できること(指摘2-1)。

    修正前は`_looks_like_ministry_segment`が省/府/庁でしか終端を認めず、
    国家公安委員会・会計検査院のような区分1つが原因で共管全体(解決できる
    総務省・大蔵省まで)が`None`に落ちていた(レビューの実測そのもの)。
    """
    assert extract_ministry_names("昭和四十七年国家公安委員会・総務省令第一号") == [
        "国家公安委員会",
        "総務省",
    ]
    assert extract_ministry_names("平成十二年会計検査院・大蔵省令第一号") == [
        "会計検査院",
        "大蔵省",
    ]


def test_extract_ministry_names_flags_unrecognized_co_jurisdiction_segment_as_extraction_failed():
    """共管の1区分が政府機関の形(省/府/庁/院/委員会で終わる)をしていない場合、
    `None`(対象外)ではなく`EXTRACTION_FAILED`(抽出失敗)を返すこと(指摘2)。

    `令令第一号`のような1文字だけの区分(政令の「政」等、既知の非府省令)は
    `None`のままだが、複数区分の共管で明らかに機関名らしくない区分が混ざる
    場合は「見た目は府省令だが抽出できなかった」として計測対象に残す。
    法人名は明らかに合成と分かる文字列にする(R45)
    """
    result = extract_ministry_names("令和五年ダミー機関・厚生労働省令第一号")
    assert result is EXTRACTION_FAILED, f"抽出失敗として区別されず {result!r} になった"


def test_extract_ministry_names_flags_bare_rule_form_as_extraction_failed():
    """年号の直後に「規則」が続き、機関名が無い場合は`EXTRACTION_FAILED`にすること(指摘6)。

    修正前は年号任意群の後戻りにより、年号そのもの(`平成十二年`)が機関名として
    誤って抽出されていた(実測)。年号を先に剥がしてから規則名を取る設計に
    したため、機関名が空になるこの形は「規則の形をしているのに名称が無い」
    という抽出失敗になる(対象外の`None`ではない)。
    """
    result = extract_ministry_names("平成十二年規則第一号")
    assert result is EXTRACTION_FAILED, f"抽出失敗として区別されず {result!r} になった"


def test_extract_ministry_names_handles_branch_suffix_after_ordinance_number():
    """`第…号の二`のような分岐番号が付いても抽出できること(指摘2-2)。

    レビューが実測に使った例そのもの(実在するかはローカルで確認できないため、
    表記パターンの検査として置く。Task 11で確認)。修正前は`号$`で終端を
    固定していたため`None`に落ちていた。
    """
    assert extract_ministry_names("昭和二十五年建設省令第四十号の二") == ["建設省"]


def test_extract_ministry_names_still_treats_known_non_ministry_ordinance_forms_as_out_of_scope():
    """政令のように、1文字区分で政府機関の形をしていない場合は
    引き続き`None`(対象外)であること(指摘2対応の副作用が無いことの固定。
    CASESの既存ケースと同じ入力をここでも明示的に固定する)。
    """
    assert extract_ministry_names("平成九年政令第二百七号") is None


# =============================================================================
# 最終レビュー要修正3(裁定B41): 「規則」経路は共管を「・」で分割しない
# =============================================================================

# 実在の法令番号(data/lake/egov-law/2026-08-24/laws.jsonl。law_id
# 430M602A1FDA001 / 503M602A1FDA002。実データ9,547法令中この2件だけが
# 該当する。R45: 法令番号そのものは実データであり合成していない)。
# どちらも同じ13機関の共管規則で、元号年だけが違う(平成三十年 / 令和三年)。
REAL_JOINT_RULE_LAW_NUMS = [
    (
        "平成三十年内閣府・公正取引委員会・個人情報保護委員会・総務省・法務省・"
        "財務省・文部科学省・厚生労働省・農林水産省・経済産業省・国土交通省・"
        "環境省・原子力規制委員会規則第一号"
    ),
    (
        "令和三年内閣府・公正取引委員会・個人情報保護委員会・総務省・法務省・"
        "財務省・文部科学省・厚生労働省・農林水産省・経済産業省・国土交通省・"
        "環境省・原子力規制委員会規則第二号"
    ),
]

EXPECTED_13_MINISTRIES = [
    "内閣府", "公正取引委員会", "個人情報保護委員会", "総務省", "法務省",
    "財務省", "文部科学省", "厚生労働省", "農林水産省", "経済産業省",
    "国土交通省", "環境省", "原子力規制委員会",
]


@pytest.mark.parametrize("law_num", REAL_JOINT_RULE_LAW_NUMS)
def test_extract_ministry_names_splits_co_jurisdiction_in_rule_form(law_num):
    """「規則」経路も「・」で共管を分割すること(最終レビュー要修正3。裁定B41)。

    修正前は`_RULE_RE`の経路が`m.group(1)`を分割せず、13機関の連結が
    **1件の機関名**として返っていた(実測。`docs/measurements-phase1.md:1448`
    に「OBSOLETE_ORGANIZATION 内閣府・公正取引委員会・…・原子力規制委員会」
    として結果だけは記録されていたが、欠陥としては読まれていなかった)。

    何があれば落ちるか: `extract_ministry_names`の「規則」経路
    (`_RULE_RE.match`が成功したブロック)が`return [m.group(1)]`のまま
    `.split("・")`を呼ばないと、このテストは13件のリストではなく
    1件(連結された1つの文字列)のリストを受け取って落ちる。
    """
    assert extract_ministry_names(law_num) == EXPECTED_13_MINISTRIES


def test_extract_ministry_names_single_institution_rule_forms_are_unaffected_by_the_split_fix():
    """人事院規則・会計検査院規則(単一機関。「・」を含まない)は、分割を
    追加しても1要素のリストのまま変わらないこと(要修正3の回帰の護り。
    裁定B41「人事院/閣の扱いが変わらないこと」に対応。「閣」は令の経路
    〔CASESの明治二十二年閣令第十二号〕であり規則経路ではないため、
    ここでは規則経路の人事院・会計検査院で固定する)。

    `"・"`を含まない文字列の`.split("・")`は要素1件のリストを返すので、
    分割の追加自体はこの2件の既存の振る舞いを変えない——ここではそれを
    明示的に固定する(CASESの`("人事院規則一―四", ["人事院"])`と合わせて、
    会計検査院規則も同様に固定する)。
    """
    assert extract_ministry_names("人事院規則一―四") == ["人事院"]
    assert extract_ministry_names("平成十二年会計検査院規則第一号") == ["会計検査院"]


def test_extract_ministry_names_non_organ_shaped_rule_name_still_extracts_for_no_candidate():
    """政府機関の形をしていない規則名は、引き続き`EXTRACTION_FAILED`にせず

    抽出に成功したものとして返すこと(要修正3の回帰の護り)。

    「規則」経路は抽出段で`_looks_like_government_organ`のゲートを
    掛けない(令の経路とは違う設計。`test_derive_jurisdiction_classifies_non_organ_shaped_name_as_no_candidate`
    のdocstring参照)。共管分割を追加したことで、令の経路と同じ
    `all(_looks_like_government_organ(s) for s in segments)` ゲートを
    誤って持ち込むと、このテスト(1区分・非機関形)は`EXTRACTION_FAILED`
    に変わり、NO_CANDIDATE分類のテストが壊れる(このタスクで実際に検討し、
    避けた設計)。
    """
    assert extract_ministry_names("ダミー機関規則第一号") == ["ダミー機関"]


# =============================================================================
# Step 3: 解決
# =============================================================================

# 実在の対応(tests/zenken_rows.py と同じ、2026-08-23にCQ実行で確認済みの値)。
# 架空の主体には明らかに合成と分かる番号を使う(R45)
KOUSEIROUDOU_BANGOU = "6000012070001"
SOUMU_BANGOU = "2000012020001"


def _law_record(law_id: str, law_num: str, **overrides) -> LawRecord:
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


def _ministry(houjin_bangou: str, name: str, ministry_code: str = "999") -> Ministry:
    return Ministry(
        uri=f"https://jgkg.norr-tech.com/id/org/{houjin_bangou}",
        houjin_bangou=houjin_bangou,
        ministry_code=ministry_code,
        name=name,
    )


def test_derive_jurisdiction_returns_none_for_out_of_scope_records():
    """法令番号に府省名を含まない法律・政令などは経路1の対象外(None)。"""
    record = _law_record("999AC0000000001", "令和三年法律第三十六号")
    assert derive_jurisdiction(record, reference={}, old_ministries=set()) is None


def test_derive_jurisdiction_propagates_extraction_failed_without_downgrading_to_none():
    """`extract_ministry_names`が`EXTRACTION_FAILED`を返したら、`derive_jurisdiction`も
    そのまま`EXTRACTION_FAILED`を返すこと(対象外の`None`に落とさない)。

    件数を集計する側(将来のTask 7の`PipelineReport`)は`is EXTRACTION_FAILED`で
    判定するため、ここで`None`に丸められると指摘2の欠陥(抽出失敗が対象外と
    区別できない)が`derive_jurisdiction`の境界で再発する。`extract_ministry_names`
    単体のテストとは別に、この伝播そのものを固定する。

    何があれば落ちるか: 誰かが`derive_jurisdiction`を単純化して
    `if names is None or names is EXTRACTION_FAILED: return None`のような
    実装に変えると、このテストだけが落ちる(extract_ministry_names側の
    テストは無傷のまま)。
    """
    record = _law_record("999AC0000000002", "令和五年ダミー機関・厚生労働省令第一号")
    result = derive_jurisdiction(record, reference={}, old_ministries=set())
    assert result is EXTRACTION_FAILED, f"EXTRACTION_FAILEDが伝播せず {result!r} になった"


def test_derive_jurisdiction_resolves_a_current_ministry():
    record = _law_record("323M60000100010", "令和七年厚生労働省令第十号")
    reference = to_ministry_reference([_ministry(KOUSEIROUDOU_BANGOU, "厚生労働省")])

    result = derive_jurisdiction(record, reference, old_ministries=set())

    assert result == JurisdictionResult(
        law_id="323M60000100010",
        ministry_names=["厚生労働省"],
        resolved=[KOUSEIROUDOU_BANGOU],
        unresolved=[],
    )


def test_derive_jurisdiction_classifies_old_ministry():
    record = _law_record("326M50000400100", "昭和二十六年大蔵省令第百号")

    result = derive_jurisdiction(record, reference={}, old_ministries={"大蔵省"})

    assert result.resolved == []
    assert result.unresolved == [UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")]


def test_derive_jurisdiction_classifies_abolished_ministry_when_succession_is_resolved():
    """C-3裁定: `abolished_ministries`(ministry_succession/C-1・C-2が

    後継・廃止日を解決できた旧省庁名)に載っている名称は、現存府省への
    読み替えではなく`resolved_abolished`(当時の組織自身)に入ること。
    「昭和二十六年大蔵省令」の所管は大蔵省であり、財務省が1951年に発した
    と主張するのは偽(裁定)。
    """
    record = _law_record("326M50000400100", "昭和二十六年大蔵省令第百号")

    result = derive_jurisdiction(
        record,
        reference={},
        old_ministries={"大蔵省"},
        abolished_ministries=frozenset({"大蔵省"}),
    )

    assert result.resolved == []
    assert result.resolved_abolished == ["大蔵省"]
    assert result.unresolved == []


def test_derive_jurisdiction_still_classifies_old_ministry_when_not_in_abolished_ministries():
    """`old_ministries`に載っているが`abolished_ministries`には無い名称は、

    C-2以前と同じくOLD_MINISTRYのまま(将来old-ministries.csvが広がった
    場合の後方互換。現時点では18/18が解決するため実質起こらない分岐)。
    """
    record = _law_record("326M50000400100", "昭和二十六年大蔵省令第百号")

    result = derive_jurisdiction(
        record,
        reference={},
        old_ministries={"大蔵省"},
        abolished_ministries=frozenset(),
    )

    assert result.resolved_abolished == []
    assert result.unresolved == [UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")]


def test_derive_jurisdiction_classifies_unlisted_organ_shaped_name_as_obsolete_organization():
    """名称が参照表にも旧省庁名リストにも無い場合は OBSOLETE_ORGANIZATION(裁定B7)。

    **Task 5(2026-08-23)で参照表は40行(裁定B15)に拡張され、人事院は今は載っている**
    (`tests/test_reference_ministries.py` の同名シナリオが「拡張後は resolved
    になる」ことを固定している)。このテスト自身は `reference={}` を明示的に
    渡す合成シナリオであり、Task 5以降は「現在のリポジトリの実際の状態」では
    なく、**分類ロジック(`_looks_like_government_organ` に基づく導出)そのもの
    を参照表の内容から独立に固定する単体テスト**という位置づけに変わった
    (以前の版はこの空のreferenceを「現在の実際の状態」と説明していたが、
    参照表拡張後は事実と異なるため訂正した)。

    **裁定B7による分類変更**: 政府機関の形(「院」で終わる)をしていて
    参照表にも旧省庁名にも無い名称は、`_looks_like_government_organ` に基づく
    判定で `OBSOLETE_ORGANIZATION` になる(2001年より前に廃止された、という
    意味ではなく、あくまで「政府機関の形をしていて現存府省の参照表に無い」
    という形からの導出)。この分類の正しさは参照表の完全性に依存する
    (現存だが未収録の機関を一時的に「廃止済み」と誤って呼ぶ副作用がある。
    裁定B7はこれを認識した上で、列挙を増やさない設計を優先した)。
    """
    record = _law_record("999RS0000000001", "人事院規則一―四")

    result = derive_jurisdiction(record, reference={}, old_ministries=set())

    assert result.resolved == []
    assert result.unresolved == [
        UnresolvedJurisdiction(name="人事院", reason="OBSOLETE_ORGANIZATION")
    ]


def test_derive_jurisdiction_classifies_non_organ_shaped_name_as_no_candidate():
    """政府機関の形にすら見えない名称は NO_CANDIDATE のまま(裁定B7)。

    `_RULE_RE` は規則名の形を検査しないため(指摘6。会計検査院規則等の
    実在の形を壊さないため)、規則経由の名称は政府機関の形をしているとは
    限らない。ここでは明らかに合成と分かる名称を使う(R45)
    """
    record = _law_record("999RS0000000002", "ダミー機関規則第一号")

    result = derive_jurisdiction(record, reference={}, old_ministries=set())

    assert result.resolved == []
    assert result.unresolved == [
        UnresolvedJurisdiction(name="ダミー機関", reason="NO_CANDIDATE")
    ]


def test_derive_jurisdiction_resolves_all_13_ministries_of_a_real_joint_rule_regulation():
    """実在の13機関共管規則(最終レビュー要修正3。裁定B41)が、修正後は

    13機関すべて`resolved`になり、`unresolved`(OBSOLETE_ORGANIZATION)には
    1件も残らないこと。

    `law_id`/`law_num`は実データそのもの(law_id=503M602A1FDA002。
    data/lake/egov-law/2026-08-24/laws.jsonl。R45に抵触しない)。
    `reference`(現存府省の参照表)は、この解決ロジックだけを検証する
    ための合成データ(houjin_bangouは検証用のダミー値。R45——実在する
    ように見せかけない、明らかに連番の合成値にする)。

    修正前は`extract_ministry_names`が13機関の連結を1件の名称として
    返すため、`reference`にその連結名と一致する行が無く、
    `_looks_like_government_organ`が真(「委員会」で終わる)と判定されて
    **`OBSOLETE_ORGANIZATION`1件**になっていた(実測。
    `docs/measurements-phase1.md:1448`)。26本の`law:jurisdiction`
    (13機関×2法令)が失われていたことに対応する、法令1件あたり13本の
    resolvedを、ここで固定する。
    """
    reference = to_ministry_reference(
        [_ministry(f"{9000000000000 + i:013d}", name) for i, name in enumerate(
            EXPECTED_13_MINISTRIES
        )]
    )
    record = _law_record(
        "503M602A1FDA002",
        "令和三年内閣府・公正取引委員会・個人情報保護委員会・総務省・法務省・"
        "財務省・文部科学省・厚生労働省・農林水産省・経済産業省・国土交通省・"
        "環境省・原子力規制委員会規則第二号",
    )

    result = derive_jurisdiction(record, reference, old_ministries=set())

    assert result.unresolved == [], f"未解決が残っている(修正漏れの疑い): {result.unresolved}"
    assert len(result.resolved) == 13, (
        f"13機関のうち{len(result.resolved)}件しかresolvedにならなかった"
    )


def test_derive_jurisdiction_classifies_ambiguous_when_reference_has_duplicate_names():
    """参照表に同名2行→AMBIGUOUS(ブリーフ Step 3)。

    `ministry.build()` の出力を `to_ministry_reference` でグループ化した結果、
    同名が複数残っていた場合を表す
    """
    # コード値そのものは重複行を作るためのダミー(実在しそうに見える値を
    # 避ける。R45)。2行が別のministry_codeを持ちながら同名であることだけが
    # このテストの前提
    reference = to_ministry_reference(
        [
            _ministry(KOUSEIROUDOU_BANGOU, "厚生労働省", ministry_code="999"),
            _ministry("8000012070099", "厚生労働省", ministry_code="999X"),
        ]
    )
    record = _law_record("323M60000100010", "令和七年厚生労働省令第十号")

    result = derive_jurisdiction(record, reference, old_ministries=set())

    assert result.resolved == []
    assert result.unresolved == [UnresolvedJurisdiction(name="厚生労働省", reason="AMBIGUOUS")]


def test_derive_jurisdiction_reports_every_extracted_name_not_only_resolved_ones():
    """共管で一部だけ解決できた場合でも、残りを黙って落とさない。

    何があれば落ちるか: 「resolved に入らなかった名前は捨てる」ような実装に
    退化すると、unresolved の件数が減って(または0件になって)気づかれずに通る
    (このタスクで踏みやすい欠陥の型の2番目)
    """
    reference = to_ministry_reference([_ministry(KOUSEIROUDOU_BANGOU, "総理府")])
    record = _law_record("999XX0000000001", "平成十二年総理府・大蔵省令第三号")

    result = derive_jurisdiction(record, reference, old_ministries={"大蔵省"})

    assert result.ministry_names == ["総理府", "大蔵省"]
    assert result.resolved == [KOUSEIROUDOU_BANGOU]
    assert result.unresolved == [UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")]


def test_to_ministry_reference_groups_by_name_without_dropping_duplicates():
    """`{m.name: m for m in ministries}` に退化していないこと。

    何があれば落ちるか: 単純な辞書内包表記に戻すと、同名2件目が1件目を
    上書きし、AMBIGUOUS を検出できなくなる
    """
    ministries = [
        _ministry(KOUSEIROUDOU_BANGOU, "厚生労働省"),
        _ministry("8000012070099", "厚生労働省"),
        _ministry(SOUMU_BANGOU, "総務省"),
    ]
    ref = to_ministry_reference(ministries)

    assert len(ref["厚生労働省"]) == 2, "同名の重複が握り潰されている"
    assert len(ref["総務省"]) == 1


def test_old_ministries_reference_file_classifies_2001_reorganization_names():
    """実際にコミットされている data/reference/old-ministries.csv を読んで判定する。

    Step 3 の「わざと壊す確認」はこのファイルを対象に行う(合成の
    old_ministries 集合を使うテストでは、ファイルを消しても何も変わらず
    確認が空振りになるため、少なくとも1つはファイルを実際に読むテストを持つ)。

    **裁定B7でこのファイルの範囲を「2001年再編分のみ」に狭めた**ため、
    「閣」(閣令。明治期の法形式で2001年より遥かに前)はもうここに載らない。
    """
    old_ministries = load_old_ministries(OLD_MINISTRIES_PATH)
    assert "大蔵省" in old_ministries
    assert "総理府" in old_ministries
    assert "閣" not in old_ministries, (
        "「閣」は2001年再編より前(明治期)に廃止された名称なので、"
        "2001年再編分に限定したこのファイルに載っていてはならない(裁定B7)"
    )

    record = _law_record("326M50000400100", "昭和二十六年大蔵省令第百号")
    result = derive_jurisdiction(record, reference={}, old_ministries=old_ministries)

    assert result.unresolved == [UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")]


def test_kaku_ordinance_reclassifies_as_obsolete_organization_after_leaving_the_csv():
    """「閣」がold-ministries.csvから外れた後も、政府機関の形(literal)からの
    導出でOBSOLETE_ORGANIZATIONになること(裁定B7。実際のファイルで確認)。
    """
    old_ministries = load_old_ministries(OLD_MINISTRIES_PATH)
    record = _law_record("999XX0000000002", "明治二十二年閣令第十二号")

    result = derive_jurisdiction(record, reference={}, old_ministries=old_ministries)

    assert result.unresolved == [
        UnresolvedJurisdiction(name="閣", reason="OBSOLETE_ORGANIZATION")
    ]


# =============================================================================
# parse_laws: laws.jsonl の正規化(実在のfixtureをJSONL化して使う)
# =============================================================================


def _write_jsonl(tmp_path: Path, laws: list[dict]) -> Path:
    path = tmp_path / "laws.jsonl"
    path.write_text(
        "\n".join(json.dumps(law, ensure_ascii=False, sort_keys=True) for law in laws) + "\n",
        encoding="utf-8",
    )
    return path


def _load_fixture_laws(name: str) -> list[dict]:
    fixture = json.loads(Path(f"tests/fixtures/{name}").read_text(encoding="utf-8"))
    return fixture["laws"]


def test_parse_laws_normalizes_a_real_jsonl_snapshot(tmp_path):
    """`tests/fixtures/egov_laws_page1.json` の実在の法令(太政官布告)を
    そのままJSONL化して読む(R45: 新しい実在値を増やさず既存fixtureを再利用)。
    """
    laws = _load_fixture_laws("egov_laws_page1.json")
    path = _write_jsonl(tmp_path, laws)

    records = list(parse_laws(path))

    assert len(records) == 3
    first = records[0]
    assert first.law_id == "105DF0000000337"
    assert first.law_num == "明治五年太政官布告第三百三十七号"
    # law_num_type が信用できない実例(このタスクの前提そのもの)。
    # 太政官布告なのに CabinetOrder に分類されている
    assert first.law_num_type == "CabinetOrder"
    assert first.law_type == "CabinetOrder"
    assert first.law_title == "明治五年太政官布告第三百三十七号（改暦ノ布告）"
    assert first.abbrev == ["改暦の布告"]
    assert first.promulgation_date == "1872-11-09"
    assert first.repeal_status == "None"
    assert len(first.revisions) == 1
    assert first.revisions[0].revision_status == "CurrentEnforced"

    # 2件目(明治六年太政官布告第六十五号)は abbrev が null → 空リストに正規化
    assert records[1].abbrev == []


@pytest.fixture
def _tmp_jsonl(tmp_path):
    laws = _load_fixture_laws("egov_laws_page1.json")
    return _write_jsonl(tmp_path, laws)


def test_old_proclamations_are_out_of_scope_for_route_1(_tmp_jsonl):
    """実在の太政官布告(law_num_type=CabinetOrder)が経路1の対象外になること。

    parse_laws → derive_jurisdiction を実際に繋いで確認する統合的なテスト。
    law_num_type を信用して判定していたら、CabinetOrder という分類から
    誤って何らかの抽出を試みる実装に流れがちだが、ここは law_num の文字列
    (太政官布告には「府」「省」等の抽出対象になる語がそもそも無い)だけで
    Noneになることを確認する
    """
    records = list(parse_laws(_tmp_jsonl))
    assert records, "fixtureから1件も読めていない"
    for record in records:
        assert derive_jurisdiction(record, reference={}, old_ministries=set()) is None, (
            f"{record.law_num!r} (law_num_type={record.law_num_type}) が"
            " 経路1の対象になってしまった"
        )
