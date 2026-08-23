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


def test_derive_jurisdiction_classifies_no_candidate_when_absent_from_both():
    """人事院が参照表にも旧省庁名リストにも無い場合は NO_CANDIDATE。

    2026-08-23時点の data/reference/ministry-codes.csv は3行(総務省/財務省/
    厚生労働省)のみで、人事院はまだ載っていない(Task 5 で拡張予定)。ここでの
    空の reference は合成した値ではなく、現在のリポジトリの実際の状態を表す
    """
    record = _law_record("999RS0000000001", "人事院規則一―四")

    result = derive_jurisdiction(record, reference={}, old_ministries=set())

    assert result.resolved == []
    assert result.unresolved == [UnresolvedJurisdiction(name="人事院", reason="NO_CANDIDATE")]


def test_derive_jurisdiction_classifies_ambiguous_when_reference_has_duplicate_names():
    """参照表に同名2行→AMBIGUOUS(ブリーフ Step 3)。

    `ministry.build()` の出力を `to_ministry_reference` でグループ化した結果、
    同名が複数残っていた場合を表す
    """
    reference = to_ministry_reference(
        [
            _ministry(KOUSEIROUDOU_BANGOU, "厚生労働省", ministry_code="020"),
            _ministry("8000012070099", "厚生労働省", ministry_code="020X"),
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
    """
    old_ministries = load_old_ministries(OLD_MINISTRIES_PATH)
    assert "大蔵省" in old_ministries
    assert "総理府" in old_ministries
    assert "閣" in old_ministries

    record = _law_record("326M50000400100", "昭和二十六年大蔵省令第百号")
    result = derive_jurisdiction(record, reference={}, old_ministries=old_ministries)

    assert result.unresolved == [UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")]


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
