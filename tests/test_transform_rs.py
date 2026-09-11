"""budgetモジュールの変換(parse_rs / build_projects)のテスト。Task 7 brief Step 2〜4。

**実在の値を使う**(R45)。project_id は実在のRS実データ(2026-08-23取得、
rs_columns.pyの照合記録と同一スナップショット)由来: 1(内閣人事局経費)/
4・11・5551(デジタル庁)/828(消防庁。政策所管府省庁≠府省庁の実例)/
159(内閣府。特別会計detail行3件の実例)。法令IDは523AC…ではなく実在の
503AC0000000036(デジタル庁設置法)・322AC0000000120(国家公務員法)を使う。
法人番号は3010001137944(株式会社ウルフスタイル。実在)。
架空にする必要があるケース(AMBIGUOUS等の負例)は明らかに合成と分かる値
(事業ID999999等)を使う。

**`9999999999999`は本fixtureの一部では「明らかに合成」の負例として使うが、
project_id=177/284の実データではRS自身が実際に書き込むセンチネル法人番号
(個人・職員等の非法人支払先を表す。法人番号としては存在しない。
task-7-review.md指摘1・`rs.SENTINEL_HOUJIN_BANGOU`参照)としてそのまま
引用している。同じ文字列だが目的が異なる — 混同しないこと。**
"""
import csv
import json
from pathlib import Path

import pytest

from jgkg.transform import rs
from jgkg.transform.law import LawRecord, parse_laws
from jgkg.transform.ministry import Ministry

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _ministry(name: str, bangou: str) -> Ministry:
    return Ministry(
        uri=f"https://jgkg.norr-tech.com/id/org/{bangou}", houjin_bangou=bangou, name=name
    )


# 実在の府省(法人番号は houjin_bangou_sample.csv / test_reference_ministries.py と
# 独立に、このテストが必要とする3府省だけを明示的に用意する)
NAIKAKUKANBOU = _ministry("内閣官房", "5000012010023")
DIGITAL_AGENCY = _ministry("デジタル庁", "7000012090001")
SOUMUSHO = _ministry("総務省", "6000012110001")
NAIKAKUFU = _ministry("内閣府", "9000012060001")

MINISTRY_REF = {
    m.name: [m] for m in (NAIKAKUKANBOU, DIGITAL_AGENCY, SOUMUSHO, NAIKAKUFU)
}

# 実在の法令(rs_law_sample.csv / test_transform_law.py と同じ法令ID)
DEJITARUCHOU_HOUCHIHOU = LawRecord(
    law_id="503AC0000000036",
    law_num="令和三年法律第三十六号",
    law_num_type="Act",
    law_type="Act",
    law_title="デジタル庁設置法",
    abbrev=[],
    promulgation_date="2021-05-19",
    repeal_status="None",
    revisions=[],
)
KOKKA_KOUMUIN_HOU = LawRecord(
    law_id="322AC0000000120",
    law_num="昭和二十二年法律第百二十号",
    law_num_type="Act",
    law_type="Act",
    law_title="国家公務員法",
    abbrev=[],
    promulgation_date="1947-10-21",
    repeal_status="None",
    revisions=[],
)
# デジタル社会形成基本法(実在。法令ID は e-Gov 上の実在値。RS引用側は
# 末尾に全角括弧書きの公布情報を付けて表記する実例そのもの)
DEJITARU_SHAKAI_KEISEI_KIHONHOU = LawRecord(
    law_id="503AC0000000035",
    law_num="令和三年法律第三十五号",
    law_num_type="Act",
    law_type="Act",
    law_title="デジタル社会形成基本法",
    abbrev=[],
    promulgation_date="2021-05-19",
    repeal_status="None",
    revisions=[],
)

LAWS_BY_ID = {r.law_id: r for r in (DEJITARUCHOU_HOUCHIHOU, KOKKA_KOUMUIN_HOU, DEJITARU_SHAKAI_KEISEI_KIHONHOU)}
LAWS_BY_TITLE = rs.laws_index_by_title(LAWS_BY_ID.values())


# =============================================================================
# 金額の正規化(Step 2)
# =============================================================================


def test_normalize_amount_accepts_a_plain_integer_string():
    assert rs.normalize_amount("34482000") == 34482000


def test_normalize_amount_strips_commas():
    assert rs.normalize_amount("34,482,000") == 34482000


def test_normalize_amount_converts_zenkaku_digits():
    assert rs.normalize_amount("３４４８２０００") == 34482000


def test_normalize_amount_drops_a_trailing_dot_zero():
    """budget_summaryの一部の列に現れる小数点付き文字列(rs_columns.py参照)。"""
    assert rs.normalize_amount("50617000.0") == 50617000


def test_normalize_amount_treats_empty_string_as_missing_not_zero():
    """空金額は0ではなく欠損(None)として扱う(Step 2の指示)。"""
    assert rs.normalize_amount("") is None
    assert rs.normalize_amount("   ") is None


def test_normalize_amount_treats_the_string_zero_as_a_real_zero():
    """'0'という文字列は有効なゼロ予算(rs_columns.find_budget_aggregate_rowと同じ判定)。"""
    assert rs.normalize_amount("0") == 0


def test_normalize_amount_rejects_an_unrecognized_decimal_form():
    """'.0'以外の小数は未知の形なので黙って切り捨てず例外にする。"""
    with pytest.raises(ValueError):
        rs.normalize_amount("1234.5")


# =============================================================================
# 法人名の正規化(Step 3)
# =============================================================================


def test_normalize_corporate_name_unifies_corporate_type_words():
    """株式会社/(株)/㈱ の表記ゆれを統一する(Step 3の指示)。"""
    a = rs.normalize_corporate_name("株式会社ウルフスタイル")
    b = rs.normalize_corporate_name("ウルフスタイル(株)")
    c = rs.normalize_corporate_name("ウルフスタイル㈱")
    assert a == b == c


def test_normalize_corporate_name_unifies_width_and_strips_whitespace():
    a = rs.normalize_corporate_name("ＡＢＣ　商事")
    b = rs.normalize_corporate_name("ABC商事")
    assert a == b


def test_normalize_corporate_name_does_not_collapse_genuinely_different_names():
    """血縁のある正規化のみ(曖昧照合はしない)。似ているだけの別名は別のまま。"""
    a = rs.normalize_corporate_name("株式会社ウルフスタイル")
    b = rs.normalize_corporate_name("株式会社ウルフ")
    assert a != b


# =============================================================================
# laws_index_by_title(Step 4準備。titleとabbrevの両方をキーに引ける)
# =============================================================================


def test_laws_index_by_title_is_keyed_by_title():
    idx = rs.laws_index_by_title([DEJITARUCHOU_HOUCHIHOU])
    assert idx["デジタル庁設置法"] == [DEJITARUCHOU_HOUCHIHOU]


def test_laws_index_by_title_also_indexes_abbrev():
    record = LawRecord(
        law_id="999AC0000000999", law_num="テスト法令番号", law_num_type="Act",
        law_type="Act", law_title="長い正式題名法", abbrev=["長題名法"],
        promulgation_date="2020-01-01", repeal_status="None", revisions=[],
    )
    idx = rs.laws_index_by_title([record])
    assert idx["長い正式題名法"] == [record]
    assert idx["長題名法"] == [record]


def test_laws_index_by_title_detects_ambiguity_via_list_length():
    """同じ題名/略称を持つ複数の法令があれば、そのキーは複数件のリストになる。"""
    a = LawRecord(law_id="1", law_num="a", law_num_type="Act", law_type="Act",
                  law_title="同じ名前の法令", abbrev=[], promulgation_date="2020-01-01",
                  repeal_status="None", revisions=[])
    b = LawRecord(law_id="2", law_num="b", law_num_type="Act", law_type="Act",
                  law_title="同じ名前の法令", abbrev=[], promulgation_date="2021-01-01",
                  repeal_status="None", revisions=[])
    idx = rs.laws_index_by_title([a, b])
    assert idx["同じ名前の法令"] == [a, b]


# =============================================================================
# resolve_basis_law(Step 4: B13 law_id直結が主、titleフォールバックは
# law_id欠落行のみ)
# =============================================================================


def test_resolve_basis_law_resolves_directly_by_law_id():
    citation = rs.BasisLawCitation(law_id="503AC0000000036", law_title="デジタル庁設置法")
    result = rs.resolve_basis_law(citation, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.record is DEJITARUCHOU_HOUCHIHOU
    assert result.reason is None
    assert result.method == "law_id"


def test_resolve_basis_law_law_id_present_but_absent_from_snapshot_is_no_candidate():
    """law_idがあるのにe-Govスナップショットに存在しない → UnresolvedReference。

    B13: law_idが存在する行はtitleへフォールバックしない(決定的な経路なので、
    見つからなければそれ自体が結果)。
    """
    citation = rs.BasisLawCitation(law_id="999AC0000099999", law_title="デジタル庁設置法")
    result = rs.resolve_basis_law(citation, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.record is None
    assert result.reason == "NO_CANDIDATE"
    assert result.method is None
    assert result.key == "999AC0000099999"


def test_resolve_basis_law_falls_back_to_title_when_law_id_is_absent():
    citation = rs.BasisLawCitation(law_id=None, law_title="デジタル庁設置法")
    result = rs.resolve_basis_law(citation, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.record is DEJITARUCHOU_HOUCHIHOU
    assert result.method == "title_raw"


def test_resolve_basis_law_strips_one_trailing_parenthetical_before_matching():
    """RS表記の末尾の全角括弧書き(公布情報)を1回だけ剥がして再試行する(Trap 1)。

    実データ(rs_columns.py照合記録「検証5」): 'デジタル社会形成基本法（令和３年
    ５月19日法律第35号）' のような表記がそのまま完全一致しないため。
    """
    citation = rs.BasisLawCitation(
        law_id=None, law_title="デジタル社会形成基本法（令和３年５月19日法律第35号）"
    )
    result = rs.resolve_basis_law(citation, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.record is DEJITARU_SHAKAI_KEISEI_KIHONHOU
    assert result.method == "title_stripped"


def test_resolve_basis_law_no_candidate_when_title_does_not_match_even_after_stripping():
    """カンマ区切りの複数法令並記など、剥がしても一致しない実例(rs_columns.py参照)。

    完全一致のみを実装するので、これは曖昧照合をしないことの直接の帰結として
    NO_CANDIDATEになる(解決率が100%にならないことの実例)。
    """
    citation = rs.BasisLawCitation(law_id=None, law_title="沖縄振興特別措置法、水道法")
    result = rs.resolve_basis_law(citation, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.record is None
    assert result.reason == "NO_CANDIDATE"


def test_resolve_basis_law_ambiguous_when_title_matches_multiple_laws():
    laws_by_id = dict(LAWS_BY_ID)
    dup_a = LawRecord(law_id="1", law_num="a", law_num_type="Act", law_type="Act",
                       law_title="重複法令", abbrev=[], promulgation_date="2020-01-01",
                       repeal_status="None", revisions=[])
    dup_b = LawRecord(law_id="2", law_num="b", law_num_type="Act", law_type="Act",
                       law_title="重複法令", abbrev=[], promulgation_date="2021-01-01",
                       repeal_status="None", revisions=[])
    laws_by_title = rs.laws_index_by_title([dup_a, dup_b])
    citation = rs.BasisLawCitation(law_id=None, law_title="重複法令")
    result = rs.resolve_basis_law(citation, laws_by_id, laws_by_title)
    assert result.record is None
    assert result.reason == "AMBIGUOUS"


def test_resolve_basis_law_no_candidate_when_title_is_absent_too():
    citation = rs.BasisLawCitation(law_id=None, law_title="")
    result = rs.resolve_basis_law(citation, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.record is None
    assert result.reason == "NO_CANDIDATE"


# =============================================================================
# resolve_recipient(B14: 法人番号直結 → 名称正規化の一意一致 → UnresolvedReference。
# 束ね行は解決対象にしない)
# =============================================================================


def test_resolve_recipient_resolves_directly_by_houjin_bangou():
    row = rs.ExpenditureLine(
        recipient_name="株式会社ウルフスタイル", recipient_houjin_bangou="3010001137944",
        is_bundled=False, amount=3025000,
    )
    result = rs.resolve_recipient(row, name_index={})
    assert result.houjin_bangou == "3010001137944"
    assert result.method == "houjin_bangou"
    assert result.reason is None


def test_resolve_recipient_falls_back_to_normalized_name_when_bangou_is_absent():
    row = rs.ExpenditureLine(
        recipient_name="ウルフスタイル(株)", recipient_houjin_bangou=None,
        is_bundled=False, amount=1000,
    )
    name_index = {rs.normalize_corporate_name("株式会社ウルフスタイル"): ["3010001137944"]}
    result = rs.resolve_recipient(row, name_index=name_index)
    assert result.houjin_bangou == "3010001137944"
    assert result.method == "name"


def test_resolve_recipient_ambiguous_when_the_normalized_name_has_multiple_candidates():
    row = rs.ExpenditureLine(
        recipient_name="ウルフスタイル(株)", recipient_houjin_bangou=None,
        is_bundled=False, amount=1000,
    )
    name_index = {rs.normalize_corporate_name("株式会社ウルフスタイル"): ["3010001137944", "9999999999999"]}
    result = rs.resolve_recipient(row, name_index=name_index)
    assert result.houjin_bangou is None
    assert result.reason == "AMBIGUOUS"


def test_resolve_recipient_no_candidate_when_name_has_no_match():
    row = rs.ExpenditureLine(
        recipient_name="実在しない架空商事株式会社", recipient_houjin_bangou=None,
        is_bundled=False, amount=1000,
    )
    result = rs.resolve_recipient(row, name_index={})
    assert result.houjin_bangou is None
    assert result.reason == "NO_CANDIDATE"


def test_resolve_recipient_never_resolves_a_bundled_row():
    """束ね行(その他フラグ/名称='その他')は名称解決の対象にしない(B14)。

    たとえ name_index にたまたま一致するキーがあっても解決を試みない
    (「その他」という文字列そのものがどこかの法人名の正規化結果と偶然一致する
    事故を避ける)。
    """
    row = rs.ExpenditureLine(
        recipient_name="その他", recipient_houjin_bangou=None, is_bundled=True, amount=1379101,
    )
    name_index = {rs.normalize_corporate_name("その他"): ["9999999999999"]}
    result = rs.resolve_recipient(row, name_index=name_index)
    assert result.houjin_bangou is None
    assert result.reason is None, "束ね行はUnresolvedReferenceの理由を持たない(解決の対象外)"
    assert result.method is None


def test_resolve_recipient_excludes_the_rs_sentinel_houjin_bangou():
    """`9999999999999`(RSが個人・職員等の支払先に使うセンチネル。実データに
    実在する値。task-7-review.md指摘1・B18)は、法人番号として非空であっても
    直結しない。束ね行ではないので method/reason は None(未解決ではない
    — 照合すべき実体がそもそも無い)。`is_sentinel` だけが立つ。
    """
    row = rs.ExpenditureLine(
        recipient_name="個人Ａ", recipient_houjin_bangou="9999999999999",
        is_bundled=False, amount=93000,
    )
    result = rs.resolve_recipient(row, name_index={})
    assert result.houjin_bangou is None
    assert result.method is None
    assert result.reason is None
    assert result.is_sentinel is True


def test_resolve_recipient_a_real_houjin_bangou_is_not_flagged_as_sentinel():
    """壊し確認の裏取り: 実在の法人番号(3010001137944)はis_sentinelにならない。"""
    row = rs.ExpenditureLine(
        recipient_name="株式会社ウルフスタイル", recipient_houjin_bangou="3010001137944",
        is_bundled=False, amount=3025000,
    )
    result = rs.resolve_recipient(row, name_index={})
    assert result.is_sentinel is False
    assert result.method == "houjin_bangou"


# =============================================================================
# resolve_recipient: 実在しない法人番号(Ruling B27。task-10-review.md裁定要1)
# =============================================================================


def test_resolve_recipient_excludes_a_houjin_bangou_that_does_not_exist():
    """`houjin_bangou_exists`が偽と判定する法人番号は直結しない(B18のセンチネル

    と同じ形)。実データで全法人フラグONでも60件・distinct53件が残ることが
    確定している(ダミー値`1234567890123`等)。method/reasonはNone(未解決
    ではない — 照合すべき実体がそもそも無い)。`is_nonexistent`だけが立つ。
    """
    row = rs.ExpenditureLine(
        recipient_name="実在しない架空商事株式会社", recipient_houjin_bangou="1234567890123",
        is_bundled=False, amount=1000,
    )
    result = rs.resolve_recipient(row, name_index={}, houjin_bangou_exists=lambda s: False)
    assert result.houjin_bangou is None
    assert result.method is None
    assert result.reason is None
    assert result.is_nonexistent is True
    assert result.is_sentinel is False


def test_resolve_recipient_a_houjin_bangou_that_exists_is_not_flagged_as_nonexistent():
    """壊し確認の裏取り: `houjin_bangou_exists`が真を返す値はis_nonexistentにならない。"""
    row = rs.ExpenditureLine(
        recipient_name="株式会社ウルフスタイル", recipient_houjin_bangou="3010001137944",
        is_bundled=False, amount=3025000,
    )
    result = rs.resolve_recipient(row, name_index={}, houjin_bangou_exists=lambda s: True)
    assert result.is_nonexistent is False
    assert result.method == "houjin_bangou"
    assert result.houjin_bangou == "3010001137944"


def test_resolve_recipient_skips_the_existence_check_when_not_given():
    """`houjin_bangou_exists`を渡さない既定の呼び出しでは、実在確認を行わず

    従来どおり直結すること(既存の全呼び出し元との後方互換性)。
    """
    row = rs.ExpenditureLine(
        recipient_name="実在しない架空商事株式会社", recipient_houjin_bangou="1234567890123",
        is_bundled=False, amount=1000,
    )
    result = rs.resolve_recipient(row, name_index={})
    assert result.is_nonexistent is False
    assert result.method == "houjin_bangou"
    assert result.houjin_bangou == "1234567890123"


def test_resolve_recipient_sentinel_takes_priority_over_the_existence_check():
    """センチネル(`9999999999999`)は`houjin_bangou_exists`が何を返しても

    センチネル判定が先に効くこと(§8.1と同じ順序。センチネルはそもそも
    実在確認の対象ではない)。
    """
    row = rs.ExpenditureLine(
        recipient_name="個人Ａ", recipient_houjin_bangou="9999999999999",
        is_bundled=False, amount=93000,
    )
    result = rs.resolve_recipient(row, name_index={}, houjin_bangou_exists=lambda s: False)
    assert result.is_sentinel is True
    assert result.is_nonexistent is False


def test_build_projects_excludes_a_nonexistent_houjin_bangou_and_keeps_the_display_name_via_payee_label():
    """実在しない法人番号(Ruling B27)の行はExpenditureは作るが

    budget:recipientは張らず、payeeLabelに表示名を残し、UnresolvedReferenceも
    作らない(B18のセンチネルと全く同じ機構)。BuildStatsの専用カウンタに
    計上する。
    """
    expenditures = [
        rs.ExpenditureLine(
            recipient_name="実在しない架空商事株式会社", recipient_houjin_bangou="1234567890123",
            is_bundled=False, amount=93000,
        )
    ]
    result = rs.build_projects(
        [_row(project_id="9001", expenditures=expenditures)], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
        houjin_bangou_exists=lambda s: False,
    )
    assert len(result.expenditures) == 1
    exp = result.expenditures[0]
    assert exp.recipient_houjin_bangou is None
    assert exp.payee_label == "実在しない架空商事株式会社"
    assert exp.label == "実在しない架空商事株式会社"
    assert not [u for u in result.unresolved if u.kind == "recipient"], (
        "実在しない法人番号は照合すべき実体が無いので「未解決」ではない"
    )
    assert result.stats.recipients_nonexistent_houjin_bangou == 1
    assert result.stats.recipients_unresolved == 0
    assert result.stats.recipients_resolved_by_houjin_bangou == 0
    assert result.stats.recipients_sentinel == 0


# =============================================================================
# build_recipient_name_index(Step 3: RSの支出先名の集合に限定してストリーミング)
# =============================================================================


def test_build_recipient_name_index_only_includes_targeted_names():
    """target_names に無い法人名は辞書に載せない(5.8M行を全載せしない対策)。"""
    from jgkg.transform.organization import Organization

    orgs = [
        Organization(uri="https://jgkg.norr-tech.com/id/org/3010001137944",
                     houjin_bangou="3010001137944", name="株式会社ウルフスタイル", kind_code="301"),
        Organization(uri="https://jgkg.norr-tech.com/id/org/9999999999998",
                     houjin_bangou="9999999999998", name="関係ない別の会社", kind_code="301"),
    ]
    target = {rs.normalize_corporate_name("ウルフスタイル(株)")}
    idx = rs.build_recipient_name_index(orgs, target)
    assert idx == {rs.normalize_corporate_name("株式会社ウルフスタイル"): ["3010001137944"]}


def test_build_recipient_name_index_collects_multiple_candidates_for_ambiguity():
    from jgkg.transform.organization import Organization

    name = "同名商事株式会社"
    orgs = [
        Organization(uri="https://jgkg.norr-tech.com/id/org/1000000000001",
                     houjin_bangou="1000000000001", name=name, kind_code="301"),
        Organization(uri="https://jgkg.norr-tech.com/id/org/1000000000002",
                     houjin_bangou="1000000000002", name=name, kind_code="301"),
    ]
    idx = rs.build_recipient_name_index(orgs, {rs.normalize_corporate_name(name)})
    assert sorted(idx[rs.normalize_corporate_name(name)]) == ["1000000000001", "1000000000002"]


# =============================================================================
# parse_rs(ファイル読み込み+結合。zip/生CSVどちらも受ける)
# =============================================================================


def test_parse_rs_reads_a_fully_joined_project_from_plain_csv_fixtures():
    """project_id=1(内閣人事局経費)が4ファイルすべてに実在し、フルに結合できる。"""
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    assert "1" in rows, f"project_id=1 が読めていない: {sorted(rows)}"
    row = rows["1"]
    assert row.fiscal_year == "2025"
    assert row.project_name == "内閣人事局経費（研修事業）"
    assert row.ministry_name == "内閣官房"


def test_parse_rs_verifies_headers_against_the_matching_record():
    """列がずれた入力はColumnLayoutErrorで止まる(rs_columns.verify_header経由)。"""
    from jgkg.transform import rs_columns

    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_sample.csv",  # 意図的に違うファイルを渡す
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    with pytest.raises(rs_columns.ColumnLayoutError):
        list(rs.parse_rs(paths))


def test_parse_rs_reports_basis_law_citations_deduplicated_by_law_id():
    """project_id=4は2行が同じ法令ID(503AC0000000036)を引用する(rs_columns.py検証4)。

    行単位では2件だが、citationsとしては両方保持してよい(重複除去はbuild_projects
    側が行う設計。ここはparse_rsが「行をそのまま持つ」ことだけを確認する)。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    citations = rows["4"].basis_law_citations
    assert len(citations) == 2
    assert all(c.law_id == "503AC0000000036" for c in citations)


def test_parse_rs_extracts_the_aggregate_row_recipient_and_ignores_the_block_row():
    """project_id=1の支出先(rs_sample.csv)。ブロック行(支出先名が空)は無視し、

    支出先行から法人番号・金額を取ること。role([16])はブロック行にしか
    現れない値なので、ブロック番号を介して伝播できていること(B20)も
    ここで確認する。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    expenditures = rows["1"].expenditures
    assert len(expenditures) == 1
    line = expenditures[0]
    assert line.recipient_name == "株式会社ウルフスタイル"
    assert line.recipient_houjin_bangou == "3010001137944"
    assert line.amount == 3025000
    assert line.is_bundled is False
    assert line.role == "ウェブ会議システムを利用した研修の運営支援に関する業務"


def test_parse_rs_role_uses_the_last_block_row_when_two_disagree_for_project_1409():
    """project_id=1409(財務省)ブロックAは、[15]支出先の数/[16]役割が異なる

    ブロック行を**2件**持つ(task-7-review.md 指摘8フォローアップの実データ調査で
    発見した実例。全20,700ブロックのうち、複数のブロック行を持つのはこの1件
    だけ)。単純な「後勝ち」(この1件のためだけの複雑な判定規則は作らない)で、
    ファイル出現順で最後に読んだブロック行の役割が使われることを固定する。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    expenditures = rows["1409"].expenditures
    assert len(expenditures) == 1
    line = expenditures[0]
    assert line.recipient_name == "株式会社日本政策金融公庫"
    assert line.amount == 46600000000
    assert line.role == (
        "※信用保証協会が代位弁済を行った場合、代位弁済額にてん補率を乗じた金額を信用保証協会に支払う"
    )


def test_parse_rs_flags_the_other_bundled_row_for_project_11():
    """project_id=11(rs_sample.csv)。「その他」束ね行はis_bundled=Trueで保持される
    (rs_columns.py検証7。黙って落とさない)。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    expenditures = rows["11"].expenditures
    assert len(expenditures) == 1
    line = expenditures[0]
    assert line.recipient_name == "その他"
    assert line.is_bundled is True
    assert line.amount == 1379101


def test_parse_rs_flags_the_sonota_name_as_bundled_even_without_the_other_flag_for_project_177():
    """project_id=177(内閣府)ブロックFの「その他」行。[22]その他支出先フラグは

    'FALSE' だが [18]支出先名='その他'(task-7-review.md 指摘2。変異実験で
    `_is_bundled_row` の名称半分を削除しても既存の79件が全部通ってしまうと
    指摘された箇所 — フラグが立っている pid=11 の実例だけでは、フラグ・名称
    どちらの判定が効いているのか区別できないため、名称だけが立っている実例を
    別に固定する)。センチネル法人番号(9999999999999)も持つが、束ね行判定が
    先に効くため is_bundled=True になり、`recipient_houjin_bangou` はNoneに
    落とされる(束ね行は法人番号を見ない。§8.1と同じ順序)。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    expenditures = rows["177"].expenditures
    assert len(expenditures) == 1
    line = expenditures[0]
    assert line.recipient_name == "その他"
    assert line.is_bundled is True
    assert line.recipient_houjin_bangou is None
    assert line.amount == 55359000


def test_parse_rs_treats_a_fiscal_year_mismatch_as_a_missing_budget_amount_for_project_159():
    """project_id=159(内閣府)。budget_summary側の3行は全て予算年度[13]='2023'で、

    spine側の事業年度(2025)と一致しない(task-7-review.md指摘3。Task 6指摘2
    (C4級)が作った「予算年度でフィルタする」守衛に、これまでテストが無かった
    — 変異実験でフィルタ条件を削除しても48件全部が通っていた)。正しい実装は
    この事業年度の集計行が0件なので欠損(None)になる。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    assert rows["159"].budget_amount is None


def test_parse_rs_resolves_the_current_fiscal_year_budget_aggregate_for_project_828():
    """project_id=828(消防庁。ministry_name=総務省)。ゼロでない実額を取れること。"""
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    row828 = rows["828"]
    assert row828.ministry_name == "総務省"
    assert row828.budget_amount == 95667000


def test_parse_rs_treats_zero_budget_as_a_real_value_for_project_5551():
    """project_id=5551(デジタル庁)。ゼロ予算は欠損ではない(rs_columns.py参照)。"""
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    assert rows["5551"].budget_amount == 0


def test_parse_rs_reports_no_basis_law_citations_when_the_project_has_none():
    """project_id=828/159/5551はrs_law_sample.csvに1行も無い(架空の欠落ではなく、

    このfixtureが元々その3事業の根拠法令行を収録していないだけ。それでも
    build_projectsが動くよう、空リストとして表現できることを確認する)。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = {r.project_id: r for r in rs.parse_rs(paths)}
    assert rows["828"].basis_law_citations == ()


def test_parse_rs_counts_a_genuinely_missing_payee_amount_without_creating_an_expenditure():
    """project_id=284(内閣府「クールジャパン戦略推進経費」)ブロックF・個人Ｊの実例
    (rs_columns.py照合記録「検証6追記」)。[23]支出先の合計支出額と[25]契約単位の
    内訳が2物理行ともに空(金額が本当に欠落している)。Expenditureは作らず、
    `RsParseStats.payee_rows_missing_amount` に2行分を数える(欠陥型4対策 —
    `stats`を渡さなければ誰にも見えなくなる件数)。同じブロックの個人Ａ(正常に
    [23]/[25]どちらかから金額が取れる)は数えず、通常どおりExpenditureになる
    ことも確認する。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    stats = rs.RsParseStats()
    rows = {r.project_id: r for r in rs.parse_rs(paths, stats=stats)}
    expenditures = rows["284"].expenditures
    assert len(expenditures) == 1
    assert expenditures[0].recipient_name == "個人Ａ"
    assert expenditures[0].amount == 93000
    assert stats.payee_rows_missing_amount == 2  # 個人Ｊの2物理行


# =============================================================================
# build_projects(rows, ministry_ref, laws_by_id, laws_by_title)
# =============================================================================


def _row(
    project_id="1",
    fiscal_year="2025",
    project_name="テスト事業",
    ministry_name="内閣官房",
    budget_amount=100,
    prior_year_executed_amount=None,
    basis_law_citations=(),
    expenditures=(),
):
    return rs.RsRow(
        project_id=project_id,
        fiscal_year=fiscal_year,
        project_name=project_name,
        ministry_name=ministry_name,
        budget_amount=budget_amount,
        prior_year_executed_amount=prior_year_executed_amount,
        basis_law_citations=tuple(basis_law_citations),
        expenditures=tuple(expenditures),
    )


def test_build_projects_resolves_ministry_via_the_reference_table():
    result = rs.build_projects([_row(ministry_name="デジタル庁")], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE)
    assert len(result.projects) == 1
    assert result.projects[0].ministry_houjin_bangou == DIGITAL_AGENCY.houjin_bangou
    assert result.stats.ministries_resolved == 1
    assert result.stats.ministries_unresolved == 0


def test_build_projects_carries_prior_year_executed_amount_through():
    """B24(6): RsRowのprior_year_executed_amountがBudgetProjectRecordまで

    そのまま伝わること(観測用。RDFへは出さない=emit_budgetの対象外)。
    """
    result = rs.build_projects(
        [_row(prior_year_executed_amount=34482000)], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert result.projects[0].prior_year_executed_amount == 34482000


def test_build_projects_prior_year_executed_amount_defaults_to_none():
    result = rs.build_projects([_row()], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.projects[0].prior_year_executed_amount is None


# =============================================================================
# B24(6): parse_rs が budget_summary から直前年度の執行額を実際に抜き出すこと
# =============================================================================


def _write_csv(path: Path, header: tuple[str, ...], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def test_parse_rs_extracts_the_prior_fiscal_years_executed_amount(tmp_path: Path):
    """budget_summaryに当該事業年度(2025)と直前年度(2024)の集計行が両方あるとき、

    prior_year_executed_amountは2024年度の[19]執行額(合計)を取ること
    (B19: 支出はレビューシート年度ではなく直前年度の執行実績と対応する)。
    """
    from jgkg.transform import rs_columns

    project_spec = rs_columns.RS_FILES["project_summary"]
    _write_csv(
        tmp_path / "project_summary.csv",
        project_spec.full_header,
        [_full_row(project_spec, {"project_id": "1", "fiscal_year": "2025", "project_name": "テスト事業", "ministry_name": "内閣官房"})],
    )
    budget_spec = rs_columns.RS_FILES["budget_summary"]
    _write_csv(
        tmp_path / "budget_summary.csv",
        budget_spec.full_header,
        [
            _full_row(budget_spec, {
                "project_id": "1", "budget_fiscal_year": "2025",
                "budget_amount": "100", "executed_amount": "0",
            }),
            _full_row(budget_spec, {
                "project_id": "1", "budget_fiscal_year": "2024",
                "budget_amount": "90", "executed_amount": "34482000",
            }),
        ],
    )
    law_spec = rs_columns.RS_FILES["policy_measure_laws_and_regulations"]
    _write_csv(tmp_path / "law.csv", law_spec.full_header, [])
    payee_spec = rs_columns.RS_FILES["payee_payment_information"]
    _write_csv(tmp_path / "payee.csv", payee_spec.full_header, [])

    paths = {
        "project_summary": tmp_path / "project_summary.csv",
        "budget_summary": tmp_path / "budget_summary.csv",
        "policy_measure_laws_and_regulations": tmp_path / "law.csv",
        "payee_payment_information": tmp_path / "payee.csv",
    }
    rows = list(rs.parse_rs(paths))
    assert len(rows) == 1
    assert rows[0].budget_amount == 100
    assert rows[0].prior_year_executed_amount == 34482000


def test_parse_rs_prior_year_executed_amount_is_none_when_the_prior_row_is_absent(tmp_path: Path):
    """直前年度の行がbudget_summaryに存在しない事業は、欠損としてNoneになること

    (ColumnLayoutErrorにしない — `_current_year_budget_amount`と同じ判断)。
    """
    from jgkg.transform import rs_columns

    project_spec = rs_columns.RS_FILES["project_summary"]
    _write_csv(
        tmp_path / "project_summary.csv",
        project_spec.full_header,
        [_full_row(project_spec, {"project_id": "1", "fiscal_year": "2025", "project_name": "テスト事業", "ministry_name": "内閣官房"})],
    )
    budget_spec = rs_columns.RS_FILES["budget_summary"]
    _write_csv(
        tmp_path / "budget_summary.csv",
        budget_spec.full_header,
        [_full_row(budget_spec, {
            "project_id": "1", "budget_fiscal_year": "2025",
            "budget_amount": "100", "executed_amount": "0",
        })],
    )
    law_spec = rs_columns.RS_FILES["policy_measure_laws_and_regulations"]
    _write_csv(tmp_path / "law.csv", law_spec.full_header, [])
    payee_spec = rs_columns.RS_FILES["payee_payment_information"]
    _write_csv(tmp_path / "payee.csv", payee_spec.full_header, [])

    paths = {
        "project_summary": tmp_path / "project_summary.csv",
        "budget_summary": tmp_path / "budget_summary.csv",
        "policy_measure_laws_and_regulations": tmp_path / "law.csv",
        "payee_payment_information": tmp_path / "payee.csv",
    }
    rows = list(rs.parse_rs(paths))
    assert rows[0].prior_year_executed_amount is None


def _full_row(spec, values: dict) -> list[str]:
    """`spec.full_header`と同じ長さの行を作り、`spec.col`名で指定した値だけ埋める。

    それ以外の列は空文字(実データの空欄と同じ)。
    """
    row = [""] * len(spec.full_header)
    for name, value in values.items():
        row[spec.col[name]] = value
    return row


def test_build_projects_reports_unresolved_ministry_with_no_candidate():
    result = rs.build_projects(
        [_row(project_id="999999", ministry_name="存在しない省")],
        MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert result.projects[0].ministry_houjin_bangou is None
    unresolved = [u for u in result.unresolved if u.kind == "ministry"]
    assert len(unresolved) == 1
    assert unresolved[0].reason == "NO_CANDIDATE"
    assert unresolved[0].project_id == "999999"
    assert result.stats.ministries_unresolved == 1


def test_build_projects_reports_unresolved_ministry_as_ambiguous_on_duplicate_reference_rows():
    ref = dict(MINISTRY_REF)
    ref["二重府省"] = [DIGITAL_AGENCY, SOUMUSHO]
    result = rs.build_projects([_row(ministry_name="二重府省")], ref, LAWS_BY_ID, LAWS_BY_TITLE)
    unresolved = [u for u in result.unresolved if u.kind == "ministry"]
    assert unresolved[0].reason == "AMBIGUOUS"


def test_build_projects_resolves_basis_law_by_id_and_dedupes_repeated_citations():
    """project_id=4式: 同じ法令IDを2回引用しても、basisLawとしては1件分。"""
    citations = [
        rs.BasisLawCitation(law_id="503AC0000000036", law_title="デジタル庁設置法"),
        rs.BasisLawCitation(law_id="503AC0000000036", law_title="デジタル庁設置法"),
    ]
    result = rs.build_projects(
        [_row(ministry_name="デジタル庁", basis_law_citations=citations)],
        MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    project = result.projects[0]
    assert project.basis_law_ids == ("503AC0000000036",)
    assert result.stats.basis_law_resolved_by_id == 2, "引用は2件とも解決済みとして計数する"


def test_build_projects_skips_rows_with_no_citation_at_all():
    """law_id・law_titleともに空の引用行は「引用そのものが無い」ので対象外
    (未解決にも数えない。rs_columns.py検証4参照)。
    """
    citations = [rs.BasisLawCitation(law_id=None, law_title="")]
    result = rs.build_projects(
        [_row(basis_law_citations=citations)], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert result.projects[0].basis_law_ids == ()
    assert result.stats.basis_law_out_of_scope == 1
    assert result.stats.basis_law_unresolved == 0
    assert not [u for u in result.unresolved if u.kind == "basis_law"]


def test_build_projects_reports_unresolved_basis_law_when_id_absent_from_snapshot():
    citations = [rs.BasisLawCitation(law_id="000AC0000000000", law_title="存在しない法令")]
    result = rs.build_projects(
        [_row(project_id="999998", basis_law_citations=citations)],
        MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert result.projects[0].basis_law_ids == ()
    unresolved = [u for u in result.unresolved if u.kind == "basis_law"]
    assert len(unresolved) == 1
    assert unresolved[0].reason == "NO_CANDIDATE"
    assert unresolved[0].project_id == "999998"


def test_build_projects_creates_an_expenditure_with_the_resolved_recipient():
    expenditures = [
        rs.ExpenditureLine(
            recipient_name="株式会社ウルフスタイル", recipient_houjin_bangou="3010001137944",
            is_bundled=False, amount=3025000,
        )
    ]
    result = rs.build_projects(
        [_row(project_id="1", fiscal_year="2025", expenditures=expenditures)],
        MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert len(result.expenditures) == 1
    exp = result.expenditures[0]
    assert exp.project_id == "1"
    assert exp.fiscal_year == "2025"
    assert exp.seq == 0
    assert exp.recipient_houjin_bangou == "3010001137944"
    assert exp.amount == 3025000
    assert exp.label == "株式会社ウルフスタイル"
    assert result.stats.recipients_resolved_by_houjin_bangou == 1


def test_build_projects_creates_an_expenditure_for_a_bundled_row_without_a_recipient_edge():
    expenditures = [
        rs.ExpenditureLine(
            recipient_name="その他", recipient_houjin_bangou=None, is_bundled=True, amount=1379101,
        )
    ]
    result = rs.build_projects(
        [_row(project_id="11", expenditures=expenditures)], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert len(result.expenditures) == 1, "束ね行でも支出そのものは黙って落とさない(B14)"
    exp = result.expenditures[0]
    assert exp.recipient_houjin_bangou is None
    assert exp.label == "その他"
    assert not [u for u in result.unresolved if u.kind == "recipient"], (
        "束ね行はUnresolvedReferenceの対象ではない"
    )
    assert result.stats.expenditures_bundled == 1


def test_build_projects_excludes_the_sentinel_and_keeps_the_display_name_via_payee_label():
    """センチネル法人番号(B18・task-7-review.md指摘1)の行はExpenditureは作るが

    budget:recipientは張らず、payeeLabelに表示名を残し、
    UnresolvedReferenceも作らない(束ね行ではないが「未解決」でもない —
    照合すべき実体がそもそも存在しないため)。
    """
    expenditures = [
        rs.ExpenditureLine(
            recipient_name="個人Ａ", recipient_houjin_bangou="9999999999999",
            is_bundled=False, amount=93000,
        )
    ]
    result = rs.build_projects(
        [_row(project_id="284", expenditures=expenditures)], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert len(result.expenditures) == 1
    exp = result.expenditures[0]
    assert exp.recipient_houjin_bangou is None
    assert exp.payee_label == "個人Ａ"
    assert exp.label == "個人Ａ"
    assert not [u for u in result.unresolved if u.kind == "recipient"], (
        "センチネルは照合すべき実体が無いので「未解決」ではない"
    )
    assert result.stats.recipients_sentinel == 1
    assert result.stats.recipients_unresolved == 0
    assert result.stats.recipients_resolved_by_houjin_bangou == 0


def test_parse_rs_and_build_projects_together_resolve_project_284s_sentinel_recipient_end_to_end():
    """内閣府 project_id=284 ブロックF「個人Ａ」の実データ(parse_rsの実データ

    テストとは別に、`build_projects`まで通した終端的な確認)。単体テスト
    (上記)は手組みのExpenditureLineを使うが、ここは実データがparse_rsを
    通ってもセンチネル除外が働くことを確認する。
    """
    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = list(rs.parse_rs(paths))
    result = rs.build_projects(rows, MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE)
    exp = next(e for e in result.expenditures if e.project_id == "284" and e.amount == 93000)
    assert exp.recipient_houjin_bangou is None
    assert exp.payee_label == "個人Ａ"
    assert exp.role == "ワーキンググループにおける有識者、外国人向けクールジャパン審査会委員"
    assert result.stats.recipients_sentinel >= 1


def test_build_projects_reports_unresolved_recipient_when_neither_signal_matches():
    expenditures = [
        rs.ExpenditureLine(
            recipient_name="実在しない架空商事株式会社", recipient_houjin_bangou=None,
            is_bundled=False, amount=500,
        )
    ]
    result = rs.build_projects(
        [_row(project_id="1", expenditures=expenditures)], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    exp = result.expenditures[0]
    assert exp.recipient_houjin_bangou is None
    unresolved = [u for u in result.unresolved if u.kind == "recipient"]
    assert len(unresolved) == 1
    assert unresolved[0].reason == "NO_CANDIDATE"
    assert unresolved[0].seq == 0
    assert result.stats.recipients_unresolved == 1


def test_build_projects_assigns_sequence_numbers_in_encounter_order():
    expenditures = [
        rs.ExpenditureLine("会社A", None, False, 100),
        rs.ExpenditureLine("会社B", None, False, 200),
    ]
    result = rs.build_projects(
        [_row(project_id="1", expenditures=expenditures)], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    seqs = [e.seq for e in result.expenditures]
    assert seqs == [0, 1]


def test_build_projects_resolves_recipient_by_name_when_name_index_is_supplied():
    """name_index を渡すと、法人番号の無い支出先が名称正規化で解決されること。

    build_projects内部でresolve_recipientに空辞書を固定で渡すバグがあると、
    このテストだけが失敗する(houjin_bangou直結の経路は別テストで別に確認済み)。
    """
    expenditures = [
        rs.ExpenditureLine(
            recipient_name="ウルフスタイル(株)", recipient_houjin_bangou=None,
            is_bundled=False, amount=1000,
        )
    ]
    name_index = {rs.normalize_corporate_name("株式会社ウルフスタイル"): ["3010001137944"]}
    result = rs.build_projects(
        [_row(project_id="1", expenditures=expenditures)],
        MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE, name_index=name_index,
    )
    exp = result.expenditures[0]
    assert exp.recipient_houjin_bangou == "3010001137944"
    assert result.stats.recipients_resolved_by_name == 1


def test_build_projects_counts_projects_seen():
    result = rs.build_projects(
        [_row(project_id="1"), _row(project_id="2", ministry_name="デジタル庁")],
        MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE,
    )
    assert result.stats.projects_seen == 2
    assert len(result.projects) == 2


# =============================================================================
# 経路2(1) law_id直結・経路2(2) 名称フォールバックのend-to-end確認
# (task-7-review.md 指摘4: これまでの根拠法令解決テストはすべて手組みの
# LawRecordを使い、e-Gov形式のfixtureをparse_lawsで実際にパースした結果を
# rs.parse_rs/build_projectsに通す経路が1本もテストされていなかった)
# =============================================================================


def _laws_from_egov_fixture(tmp_path: Path) -> list[LawRecord]:
    """`tests/fixtures/egov_laws_rs_crosslink.json`(実在の3法令。同fixtureの

    _commentキー参照)を、test_transform_law.pyと同じ手順(「laws」配列を
    JSONLに書き出してparse_lawsに通す)で実際にパースする。RSのfixtureが
    引用する実在のlaw_idと、この関数が返すLawRecordのlaw_idが文字列一致
    することで、経路1(egov-law)と経路2(RS)が独立に正しく実装されていることを
    確認する(手組みのLawRecordだけでは、e-Gov側パーサの出力形とRS側の
    law_id表記がずれていても誰も検知できない)。`tmp_path`(pytest標準
    フィクスチャ)にJSONLを書く — tests/fixtures/配下に書かない
    (テスト間で共有される追跡対象ディレクトリに一時ファイルを残さないため)。
    """
    fixture = json.loads(
        (FIXTURES / "egov_laws_rs_crosslink.json").read_text(encoding="utf-8")
    )
    laws = fixture["laws"]
    jsonl_path = tmp_path / "laws.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(law, ensure_ascii=False, sort_keys=True) for law in laws) + "\n",
        encoding="utf-8",
    )
    return list(parse_laws(jsonl_path))


def test_law_id_direct_link_resolves_end_to_end_through_real_parse_laws_and_parse_rs(tmp_path):
    """project_id=1(内閣人事局経費)の国家公務員法引用(law_id=322AC0000000120)が、

    `law.parse_laws`が実際にパースしたLawRecordと`rs.parse_rs`が実際に
    パースしたRS実データを介して、B13(law_id直結が主)どおりに解決すること
    (指摘4指摘の「end-to-endの正のコントロールが無い」を埋める)。
    """
    laws = _laws_from_egov_fixture(tmp_path)
    laws_by_id = {r.law_id: r for r in laws}
    laws_by_title = rs.laws_index_by_title(laws)

    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = list(rs.parse_rs(paths))
    result = rs.build_projects(rows, MINISTRY_REF, laws_by_id, laws_by_title)

    project1 = next(p for p in result.projects if p.project_id == "1")
    assert "322AC0000000120" in project1.basis_law_ids
    assert result.stats.basis_law_resolved_by_id >= 1


def test_title_fallback_with_parenthetical_stripping_resolves_end_to_end_for_project_26(tmp_path):
    """project_id=26(デジタル庁「法人共通認証基盤」)の引用

    'デジタル社会形成基本法（令和３年５月19日法律第35号）' はlaw_idが空
    (rs_columns.py検証5の実例そのもの)。e-Govのlaw_titleは公布情報を含まない
    ため、末尾の全角括弧書きを1回剥がして初めて一致する
    (method="title_stripped")。この経路もこれまでhand-builtな
    `BasisLawCitation`単体でしかテストされておらず、parse_rsを実際に通る
    経路は無かった(指摘4)。
    """
    laws = _laws_from_egov_fixture(tmp_path)
    laws_by_id = {r.law_id: r for r in laws}
    laws_by_title = rs.laws_index_by_title(laws)

    paths = {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }
    rows = list(rs.parse_rs(paths))
    result = rs.build_projects(rows, MINISTRY_REF, laws_by_id, laws_by_title)

    project26 = next(p for p in result.projects if p.project_id == "26")
    assert "503AC0000000035" in project26.basis_law_ids
    assert result.stats.basis_law_resolved_by_title_stripped >= 1


# =============================================================================
# 恒等式(task-7-review.md「修正ラウンドの提案」完了条件・欠陥型4対策)。
#
# 元の指示「読んだ行数 = emit + 束ね + センチネル + 未解決 + 欠損 + ブロック行 +
# spine重複」は次元が合わない(束ね・センチネル・未解決はemitの部分集合であり、
# 別々に加算すると二重に数える。かつ構造上の明細行(欠陥型4以前から存在する
# カテゴリ)が抜けている)ため、次の3つの入れ子の恒等式に直した(報告書に明記):
#
#   payee:        全行           = ブロック行 + 構造上の明細行 + 真の欠落 + Expenditure
#   expenditures: Expenditure    = 束ね + センチネル + 法人番号直結 + 名称解決 + 未解決
#   spine:        project_summary全行 = 事業数(distinct) + 重複行
#
# 数値はこのfixture全体(project_id=1/4/11/159/177/185/284/828/1409/5551/26の
# 11事業)に対する実測。fixtureが増えても恒等式自体は保たれるはず(このテストの
# 目的は「特定の数を覚える」ことではなく「3つの式が閉じている」ことの検算)。
# =============================================================================


def _full_fixture_paths() -> dict[str, Path]:
    return {
        "project_summary": FIXTURES / "rs_project_summary_sample.csv",
        "budget_summary": FIXTURES / "rs_budget_sample.csv",
        "policy_measure_laws_and_regulations": FIXTURES / "rs_law_sample.csv",
        "payee_payment_information": FIXTURES / "rs_sample.csv",
    }


def _count_data_rows(path: Path) -> int:
    """CSVのヘッダを除いた行数を、RS_COL経由ではなく素の`csv.reader`で数える

    (`parse_rs`が数えた値と独立な、検算のための対抗計算)。
    """
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader)
        return sum(1 for _ in reader)


def test_payee_row_accounting_identity_holds_across_the_full_fixture():
    """payee_payment_informationの全行が、ブロック行・構造上の明細行・

    真の欠落・Expenditureのいずれか1つに必ず属し、他のどれとも重複しない
    (欠陥型4「消費者のいない記録」の最終的な検算)。
    """
    paths = _full_fixture_paths()
    stats = rs.RsParseStats()
    rows = list(rs.parse_rs(paths, stats=stats))
    result = rs.build_projects(rows, {}, {}, {})

    total = _count_data_rows(paths["payee_payment_information"])
    assert total == 16
    assert (
        stats.payee_rows_block
        + stats.payee_rows_contract_detail
        + stats.payee_rows_missing_amount
        + result.stats.expenditures_seen
        == total
    )


def test_expenditure_resolution_accounting_identity_holds_across_the_full_fixture():
    """emitされる全Expenditureが、束ね・センチネル・実在しない法人番号(B27)・

    法人番号直結・名称解決・未解決のいずれか1つに必ず属する
    (`resolve_recipient`の5分岐+束ね早期リターンが全域を尽くしていることの
    検算)。このfixtureへの呼び出しは`houjin_bangou_exists`を渡さないため
    `recipients_nonexistent_houjin_bangou`は常に0だが、恒等式には項として
    含めておく(将来この呼び出しにも実在確認を結線した場合の回帰を検知する)。
    """
    paths = _full_fixture_paths()
    rows = list(rs.parse_rs(paths))
    result = rs.build_projects(rows, {}, {}, {})

    assert (
        result.stats.expenditures_bundled
        + result.stats.recipients_sentinel
        + result.stats.recipients_nonexistent_houjin_bangou
        + result.stats.recipients_resolved_by_houjin_bangou
        + result.stats.recipients_resolved_by_name
        + result.stats.recipients_unresolved
        == result.stats.expenditures_seen
    )


def test_spine_row_accounting_identity_holds_across_the_full_fixture():
    """project_summaryの全行が、採用された事業(distinct project_id)か

    重複として捨てた行のいずれかに属する(task-7-review.md指摘5)。
    """
    paths = _full_fixture_paths()
    stats = rs.RsParseStats()
    rows = list(rs.parse_rs(paths, stats=stats))

    total = _count_data_rows(paths["project_summary"])
    assert total == 12
    assert len(rows) + stats.project_summary_duplicate_rows == total


# =============================================================================
# 資金の流れ(支出先ブロック・国自らが支出する間接経費。裁定B97)
#
# **同じお金が流れの段ごとに何度も記録される**ため、段を区別せず合計すると
# 全体で29.9兆円を二重に数える(実測2026-09-11)。この節のテストは
# 「段を区別できること」そのものを縛る。
#
# 実データ由来の実例(R45。すべて2026-09-11取得の5-1/5-2から引用):
#   6494 児童手当等交付金に必要な経費 — 同額が2ブロックに現れる典型
#   1406 独立行政法人国際協力機構有償資金協力部門への出資 — 出どころが3つ、
#        借入金ブロックは国の支出ではない
#   1409 中小企業信用保険事業 — 5-2にしか現れないブロック/入口と流入の混在
# =============================================================================


def _block_connection_fixture_paths() -> dict[str, Path]:
    """`_full_fixture_paths()` に5-2(支出先_支出ブロックのつながり)を足したもの。

    既存の3つの恒等式テストは意図的に5-2を渡さない4ファイル版
    (`_full_fixture_paths`)を使い続ける —— あちらは「5-2が無いときも既存の
    勘定が閉じている」ことを見ており、こちらは「5-2があるときの勘定」を見る。
    """
    return _full_fixture_paths() | {
        "payee_payment_block_connection": FIXTURES / "rs_block_connection_sample.csv",
    }


def _write_five_files(
    tmp_path: Path,
    *,
    project_id: str,
    project_name: str,
    ministry_name: str,
    payee_rows: list[list[str]],
    connection_rows: list[list[str]],
) -> dict[str, Path]:
    """1事業分の5ファイル(必須4本+5-2)をtmp_pathに書き、`parse_rs`用のpathsを返す。

    `_write_csv`/`_full_row`(既存)と同じ作法。budget_summary・法令は空にする
    (このテスト群が見るのは資金の流れだけで、予算額・根拠法令は無関係)。
    """
    from jgkg.transform import rs_columns

    project_spec = rs_columns.RS_FILES["project_summary"]
    _write_csv(
        tmp_path / "project_summary.csv",
        project_spec.full_header,
        [
            _full_row(project_spec, {
                "project_id": project_id, "fiscal_year": "2025",
                "project_name": project_name, "ministry_name": ministry_name,
            })
        ],
    )
    budget_spec = rs_columns.RS_FILES["budget_summary"]
    _write_csv(tmp_path / "budget_summary.csv", budget_spec.full_header, [])
    law_spec = rs_columns.RS_FILES["policy_measure_laws_and_regulations"]
    _write_csv(tmp_path / "law.csv", law_spec.full_header, [])
    _write_csv(
        tmp_path / "payee.csv",
        rs_columns.RS_FILES["payee_payment_information"].full_header,
        payee_rows,
    )
    _write_csv(
        tmp_path / "connection.csv",
        rs_columns.RS_FILES["payee_payment_block_connection"].full_header,
        connection_rows,
    )
    return {
        "project_summary": tmp_path / "project_summary.csv",
        "budget_summary": tmp_path / "budget_summary.csv",
        "policy_measure_laws_and_regulations": tmp_path / "law.csv",
        "payee_payment_information": tmp_path / "payee.csv",
        "payee_payment_block_connection": tmp_path / "connection.csv",
    }


def _block_row(values: dict) -> list[str]:
    from jgkg.transform import rs_columns

    return _full_row(rs_columns.RS_FILES["payee_payment_information"], values)


def _connection_row(values: dict) -> list[str]:
    from jgkg.transform import rs_columns

    return _full_row(rs_columns.RS_FILES["payee_payment_block_connection"], values)


# 児童手当等交付金(project_id=6494・こども家庭庁)の実データ。同じ
# 1,401,293,745,413円が「国→市町村(1,741先)」と「市町村→児童手当受給者
# (7,789,939人)」の2ブロックに現れる(schema/budget.yaml ExpenditureBlock参照)
JIDOU_TEATE_AMOUNT = 1401293745413


def _jidou_teate_paths(tmp_path: Path) -> dict[str, Path]:
    return _write_five_files(
        tmp_path,
        project_id="6494",
        project_name="児童手当等交付金に必要な経費",
        ministry_name="こども家庭庁",
        payee_rows=[
            _block_row({
                "project_id": "6494", "fiscal_year": "2025", "block_number": "A",
                "block_name": "市町村", "block_payee_count": "1741",
                "expenditure_role": "児童手当の支給事務",
                "block_amount": str(JIDOU_TEATE_AMOUNT),
            }),
            _block_row({
                "project_id": "6494", "fiscal_year": "2025", "block_number": "B",
                "block_name": "児童手当受給者", "block_payee_count": "7789939",
                "expenditure_role": "児童手当の受給",
                "block_amount": str(JIDOU_TEATE_AMOUNT),
            }),
        ],
        connection_rows=[
            _connection_row({
                "project_id": "6494", "fiscal_year": "2025",
                "block_from_name": "こども家庭庁", "paid_by_government": "TRUE",
                "block_to": "A", "block_to_name": "市町村",
            }),
            _connection_row({
                "project_id": "6494", "fiscal_year": "2025",
                "block_from": "A", "block_from_name": "市町村",
                "paid_by_government": "FALSE",
                "block_to": "B", "block_to_name": "児童手当受給者",
            }),
        ],
    )


def test_blocks_entry_only_total_is_half_of_the_naive_total_for_jidou_teate(tmp_path: Path):
    """児童手当型の2段構造で、**入口ブロックだけの合計が片方の額になる**こと。

    何があれば落ちるか: `paid_by_government` が全ブロックで真になる実装
    (例: [15]を見ずに「5-2に現れたら入口」とする)だと、入口だけの合計が
    単純合計と同じ2,802,587,490,826円になってここで落ちる。逆に[15]がTRUEの
    行を取りこぼすと入口が0件になり、こちらも落ちる。**これが29.9兆円の
    二重計上を避けられることの最小の証明**である。
    """
    rows = list(rs.parse_rs(_jidou_teate_paths(tmp_path)))
    assert len(rows) == 1
    blocks = {b.block_id: b for b in rows[0].blocks}
    assert sorted(blocks) == ["A", "B"]

    naive_total = sum(b.amount for b in blocks.values() if b.amount is not None)
    entry_total = sum(
        b.amount for b in blocks.values() if b.paid_by_government and b.amount is not None
    )
    assert naive_total == 2 * JIDOU_TEATE_AMOUNT
    assert entry_total == JIDOU_TEATE_AMOUNT
    assert blocks["A"].paid_by_government is True
    assert blocks["B"].paid_by_government is False


def test_blocks_carry_the_payee_count_and_role_from_the_5_1_block_row(tmp_path: Path):
    """ブロック名・役割・支出先の数が5-1のブロック行から来ること。

    何があれば落ちるか: 支出先の数を5-2側で探すと(5-2はこの列を持たない)
    7,789,939がNoneになる。**この値は法人数ではなく人数である**(budget.yaml
    `payeeCount`)ため、支出先行を数え直す実装でも落ちる。
    """
    rows = list(rs.parse_rs(_jidou_teate_paths(tmp_path)))
    blocks = {b.block_id: b for b in rows[0].blocks}
    assert blocks["A"].block_name == "市町村"
    assert blocks["A"].role == "児童手当の支給事務"
    assert blocks["A"].payee_count == 1741
    assert blocks["B"].block_name == "児童手当受給者"
    assert blocks["B"].payee_count == 7789939
    assert blocks["B"].funded_by == ("A",)


# 独立行政法人国際協力機構有償資金協力部門への出資(project_id=1406・財務省)の
# 実データ。ブロックDに3つの出どころ(A一般会計出資金 / B財政融資資金借入金 /
# C回収金等)が流れ込み、Bは国の支出ではない(budget.yaml `fundedBy` 参照)
JICA_BLOCK_ROWS = [
    ("A", "一般会計出資金", "1", "一般会計出資金", "81330000000"),
    ("B", "財政融資資金借入金", "1", "財政融資資金借入金", "1033400000000"),
    ("C", "回収金等", "1", "回収金等", "712241152858"),
    ("D", "独立行政法人国際協力機構", "1", "有償資金協力業務の実施", "1826971152858"),
    ("E", "開発途上地域の政府等", "1", "開発援助", "1826971153000"),
]


def _jica_paths(tmp_path: Path) -> dict[str, Path]:
    return _write_five_files(
        tmp_path,
        project_id="1406",
        project_name="独立行政法人国際協力機構有償資金協力部門への出資",
        ministry_name="財務省",
        payee_rows=[
            _block_row({
                "project_id": "1406", "fiscal_year": "2025", "block_number": block_id,
                "block_name": name, "block_payee_count": count,
                "expenditure_role": role, "block_amount": amount,
            })
            for block_id, name, count, role, amount in JICA_BLOCK_ROWS
        ],
        connection_rows=[
            _connection_row({
                "project_id": "1406", "fiscal_year": "2025",
                "block_from_name": "財務省", "paid_by_government": "TRUE",
                "block_to": "A", "block_to_name": "一般会計出資金",
            }),
        ] + [
            _connection_row({
                "project_id": "1406", "fiscal_year": "2025",
                "block_from": source, "block_from_name": source_name,
                "paid_by_government": "FALSE",
                "block_to": "D", "block_to_name": "独立行政法人国際協力機構",
            })
            for source, source_name in (
                ("A", "一般会計出資金"), ("B", "財政融資資金借入金"), ("C", "回収金等"),
            )
        ] + [
            _connection_row({
                "project_id": "1406", "fiscal_year": "2025",
                "block_from": "D", "block_from_name": "独立行政法人国際協力機構",
                "paid_by_government": "FALSE",
                "block_to": "E", "block_to_name": "開発途上地域の政府等",
            }),
        ],
    )


def test_funded_by_is_multivalued_and_the_loan_block_is_not_paid_by_government(tmp_path: Path):
    """JICA型: ブロックDの`funded_by`が3値になり、借入金ブロックBの

    `paid_by_government`が偽であること。

    何があれば落ちるか: `funded_by`を単値(後勝ち等)にすると、A/Cのどちらかが
    消えて("C",)等になる。また「5-1に金額があるブロックは国が払った」と
    みなす実装だと、1,033,400,000,000円の財政融資資金借入金(国の支出では
    なく事業に流れ込む資金)が入口として数えられ、Bが真になって落ちる。
    """
    rows = list(rs.parse_rs(_jica_paths(tmp_path)))
    blocks = {b.block_id: b for b in rows[0].blocks}
    assert blocks["D"].funded_by == ("A", "B", "C")
    assert blocks["B"].paid_by_government is False
    assert blocks["B"].funded_by == ()
    assert blocks["B"].amount == 1033400000000
    # 入口はAだけ。国が出した額(815億)と、事業に流れ込む総額との違いが出る
    assert [b.block_id for b in rows[0].blocks if b.paid_by_government] == ["A"]
    assert blocks["A"].amount == 81330000000


def test_funded_by_only_blocks_are_created_so_that_the_edges_stay_closed(tmp_path: Path):
    """出どころとしてしか現れないブロックも作られること(参照整合のため)。

    何があれば落ちるか: 「5-2の支出先ブロック([16])だけをブロックにする」
    実装だと、どこの支出先にもならないブロック(実測2件。事業274ブロックA・
    事業19873ブロックC)が作られず、`budget:fundedBy`が型の無いURIを指して
    参照整合ゲート(裁定B4)がリリース全体を止める。ここでは5-1に金額行を
    持たない純粋な出どころを1つ足して、それがブロックになることを見る。
    """
    paths = _write_five_files(
        tmp_path,
        project_id="274",
        project_name="合成: 出どころにしか現れないブロック",
        ministry_name="内閣府",
        payee_rows=[
            _block_row({
                "project_id": "274", "fiscal_year": "2025", "block_number": "B",
                "block_name": "受け取る側", "block_amount": "1000",
            })
        ],
        connection_rows=[
            _connection_row({
                "project_id": "274", "fiscal_year": "2025",
                "block_from": "A", "block_from_name": "出どころだけのブロック",
                "paid_by_government": "FALSE",
                "block_to": "B", "block_to_name": "受け取る側",
            })
        ],
    )
    rows = list(rs.parse_rs(paths))
    blocks = {b.block_id: b for b in rows[0].blocks}
    assert set(blocks) == {"A", "B"}, "出どころ側のブロックが作られていない"
    assert blocks["A"].amount is None
    assert blocks["A"].block_name == "出どころだけのブロック"
    assert blocks["B"].funded_by == ("A",)
    # funded_byの各値が必ずブロックとして実在すること(参照が閉じている)
    for block in rows[0].blocks:
        for source in block.funded_by:
            assert source in blocks, (block.block_id, source)


def test_blocks_present_only_in_5_2_are_kept_with_a_none_amount_for_project_1409():
    """5-2にあって5-1に金額行が無いブロックが、金額Noneのブロックとして作られること。

    project_id=1409(中小企業信用保険事業)のブロックB(信用保証協会)・
    C(金融機関)・D(中小企業等)は5-2にしか現れない(事業全体の資金の流れを
    示す参考記載)。名前は5-2の[17]から取る。

    何があれば落ちるか: 5-1のブロック行だけをブロックにする実装だと、
    B/C/Dが作られず`funded_by`の鎖(A→B→C→D)が切れる — 資金の流れを
    辿れなくなるのと、`budget:fundedBy`が参照整合ゲートに落ちるのが同時に起こる。
    """
    rows = {r.project_id: r for r in rs.parse_rs(_block_connection_fixture_paths())}
    blocks = {b.block_id: b for b in rows["1409"].blocks}
    assert sorted(blocks) == ["A", "B", "C", "D"]
    # Aだけが5-1に金額行を持つ
    assert blocks["A"].amount == 46600000000
    for block_id in ("B", "C", "D"):
        assert blocks[block_id].amount is None, block_id
        assert blocks[block_id].payee_count is None, block_id
        assert blocks[block_id].role == "", block_id
    assert blocks["B"].block_name == "信用保証協会"
    assert blocks["C"].block_name == "金融機関"
    assert blocks["D"].block_name == "中小企業等"
    # 鎖が閉じている: A→B→C→D(受け取る側から見た向きで持つ)
    assert blocks["B"].funded_by == ("A",)
    assert blocks["C"].funded_by == ("B",)
    assert blocks["D"].funded_by == ("C",)


def test_paid_by_government_and_funded_by_coexist_for_project_1409_block_a():
    """入口フラグと出どころは**排他ではない**こと(実測9件のうちの1件)。

    project_id=1409のブロックA(株式会社日本政策金融公庫)は、国(財務省)からの
    出資と信用保証協会からの保険料支払の両方を受ける。

    何があれば落ちるか: 「`funded_by`があるなら入口ではない」と正規化する
    実装(あるいはその逆)だと、どちらか一方が消える。budget.yaml の
    `paidByGovernment` はこの9件のために「入口の合計は過大になりうる」と
    明記しており、その前提がコード側で保たれていることをここで固定する。
    """
    rows = {r.project_id: r for r in rs.parse_rs(_block_connection_fixture_paths())}
    block_a = {b.block_id: b for b in rows["1409"].blocks}["A"]
    assert block_a.paid_by_government is True
    assert block_a.funded_by == ("B",)


def test_flow_notes_are_kept_verbatim_on_the_block_for_project_1409():
    """[18]資金の流れの補足情報がブロック側にverbatimで載ること。

    何があれば落ちるか: `role`と同じ列から取る実装だと空になる(両者は別物 —
    budget.yaml `flowNote`。同じブロックAが役割「※信用保証協会が…」と
    補足情報「保険料支払」を別々に持つ)。またブロック側ではなく辺側に持つ
    設計に変えると、このアクセス経路自体が消える。
    """
    rows = {r.project_id: r for r in rs.parse_rs(_block_connection_fixture_paths())}
    blocks = {b.block_id: b for b in rows["1409"].blocks}
    assert blocks["B"].flow_notes == (
        "保険金支払（事業全体を把握するための参考標記。以下同様。）",
    )
    assert blocks["C"].flow_notes == ("代位弁済",)
    assert blocks["A"].flow_notes == ("保険料支払",)
    assert blocks["A"].role.startswith("※信用保証協会が代位弁済を行った場合")


def test_flow_notes_deduplicate_repeated_values_within_a_block(tmp_path: Path):
    """同じ補足情報が複数の辺に付いていても、ブロック側では1回だけ持つこと。

    何があれば落ちるか: 素朴にappendする実装だと('再委託','再委託')になり、
    emitが同じトリプルを2回書く(RDF上は無害だが、件数を数えたときに
    辺の数とブロックの数が混ざる)。異なる補足情報は両方残ること(実測:
    4,481ブロック中14件)も同時に見る。
    """
    paths = _write_five_files(
        tmp_path,
        project_id="999999",
        project_name="合成: 同じ補足情報が2つの辺に付くブロック",
        ministry_name="内閣府",
        payee_rows=[],
        connection_rows=[
            _connection_row({
                "project_id": "999999", "fiscal_year": "2025",
                "block_from": source, "block_from_name": f"出どころ{source}",
                "paid_by_government": "FALSE",
                "block_to": "Z", "block_to_name": "受け取る側", "flow_note": note,
            })
            for source, note in (("A", "再委託"), ("B", "再委託"), ("C", "間接補助"))
        ],
    )
    rows = list(rs.parse_rs(paths))
    block_z = {b.block_id: b for b in rows[0].blocks}["Z"]
    assert block_z.funded_by == ("A", "B", "C")
    assert block_z.flow_notes == ("再委託", "間接補助")


def test_indirect_costs_are_read_from_the_block_connection_file_for_project_1():
    """国自らが支出する間接経費が5-2から取れること(5-1には現れない金額)。

    project_id=1(内閣人事局経費)の講師謝金1,034,000円・委員等旅費9,000円。

    何があれば落ちるか: [19]を「間接経費」という固定文言のフラグとして
    判定する実装だと、[19]が「旅費」である project_id=284 の2件
    (委員等旅費830,000円・職員旅費299,000円)が落ちる(rs_columns.pyの
    `indirect_flag` の注記: [19]は自由記述である)。
    """
    rows = {r.project_id: r for r in rs.parse_rs(_block_connection_fixture_paths())}
    assert rows["1"].indirect_costs == (
        rs.IndirectCostLine(item="講師謝金", amount=1034000),
        rs.IndirectCostLine(item="委員等旅費", amount=9000),
    )
    # [19]が「間接経費」ではない実例([19]='旅費')も取れていること
    assert rows["284"].indirect_costs == (
        rs.IndirectCostLine(item="委員等旅費", amount=830000),
        rs.IndirectCostLine(item="職員旅費", amount=299000),
    )


def test_indirect_costs_keep_the_first_row_when_an_item_name_repeats(tmp_path: Path):
    """同じ事業に同じ項目名が2回現れたら先頭を採り、件数を統計に残すこと。

    項目名がURIの鍵(`uris.indirect_cost_uri`)なので、両方emitすると1ノードが
    `core:amount_jpy`を2つ持ち、閉じたシェイプの`sh:maxCount 1`違反で
    rs-systemグラフ全体が隔離される。実測(2026-09-11)は0件だが、黙って
    落とすと将来の金額消失が見えなくなる。

    何があれば落ちるか: 重複除去を入れずに両方返す実装(件数3になる)、
    あるいは黙って捨てて数えない実装(統計が0のまま)。
    """
    paths = _write_five_files(
        tmp_path,
        project_id="999999",
        project_name="合成: 同じ項目名の間接経費が2行",
        ministry_name="内閣府",
        payee_rows=[],
        connection_rows=[
            _connection_row({
                "project_id": "999999", "fiscal_year": "2025",
                "indirect_flag": "間接経費", "indirect_item": item,
                "indirect_amount": amount,
            })
            for item, amount in (("講師謝金", "1000"), ("講師謝金", "2000"), ("旅費", "3000"))
        ],
    )
    stats = rs.RsParseStats()
    rows = list(rs.parse_rs(paths, stats=stats))
    assert rows[0].indirect_costs == (
        rs.IndirectCostLine(item="講師謝金", amount=1000),
        rs.IndirectCostLine(item="旅費", amount=3000),
    )
    assert stats.block_connection_indirect_cost_duplicate_item == 1


def test_parse_rs_leaves_blocks_empty_and_says_so_when_the_file_is_absent():
    """5-2を渡さないとき、ブロックと間接経費が空になり、**そのことが統計から

    観測できる**こと(`block_connection_read`が偽)。

    何があれば落ちるか: 5-2をREQUIRED_GROUPSに入れると、この4ファイル呼び出し
    自体がValueErrorで落ちる。逆に「無いから空」を記録しない実装だと、
    資金の流れが丸ごと欠けたリリースが「ブロック0件」として正常に見える
    ——`block_connection_read`が真なのにブロックが0、という区別が付かなくなる。
    """
    stats = rs.RsParseStats()
    rows = list(rs.parse_rs(_full_fixture_paths(), stats=stats))
    assert rows, "背骨の事業が読めていない"
    assert all(r.blocks == () for r in rows)
    assert all(r.indirect_costs == () for r in rows)
    assert stats.block_connection_read is False
    assert stats.block_connection_rows == 0

    # 同じ入力に5-2を足すと、同じ統計が「読んだ」側に振れる(偽が既定値の
    # まま固まっているのではないことの対抗確認)
    with_connection = rs.RsParseStats()
    rows = list(rs.parse_rs(_block_connection_fixture_paths(), stats=with_connection))
    assert with_connection.block_connection_read is True
    assert with_connection.block_connection_rows == 71
    assert sum(len(r.blocks) for r in rows) == 63
    assert sum(len(r.indirect_costs) for r in rows) == 7


def test_block_connection_row_accounting_identity_holds_across_the_full_fixture():
    """5-2の全行が、入口・辺・間接経費・無内容のいずれか1つに必ず属すること。

    実測(2026-09-11、実データ全23,381行): 13,219 + 7,494 + 2,432 + 236。
    このfixture(71行)では 34 + 30 + 7 + 0。

    何があれば落ちるか: 行の種別判定に抜けがあると和が全行に足りない
    (`_counted_block_connection_rows`は未知の形の行をColumnLayoutErrorに
    するので、そちらの経路でも気付ける)。既存の3つの恒等式テストと同じ
    「消費者のいない記録を作らない」ための検算。
    """
    paths = _block_connection_fixture_paths()
    stats = rs.RsParseStats()
    list(rs.parse_rs(paths, stats=stats))

    total = _count_data_rows(paths["payee_payment_block_connection"])
    assert total == 71
    assert stats.block_connection_rows == total
    assert (
        stats.block_connection_rows_paid_by_government
        + stats.block_connection_rows_edge
        + stats.block_connection_rows_indirect_cost
        + stats.block_connection_rows_without_payload
        == total
    )
    assert stats.block_connection_rows_paid_by_government == 34
    assert stats.block_connection_rows_edge == 30
    assert stats.block_connection_rows_indirect_cost == 7


def test_build_projects_counts_blocks_and_indirect_costs():
    """`BuildStats`が件数を持つこと(入口ブロック数を含む)。

    何があれば落ちるか: `blocks_paid_by_government`を数えない実装だと、
    「国が払った額」の分母になるブロック数がリリース記録から消える
    (pipeline-report.jsonのbudget_blocks_paid_by_governmentの入力)。
    """
    rows = list(rs.parse_rs(_block_connection_fixture_paths()))
    result = rs.build_projects(rows, {}, {}, {})
    assert result.stats.blocks_seen == len(result.blocks) == 63
    assert result.stats.indirect_costs_seen == len(result.indirect_costs) == 7
    assert result.stats.blocks_paid_by_government == 34
    assert result.stats.blocks_paid_by_government == sum(
        1 for b in result.blocks if b.paid_by_government
    )
    assert result.stats.expenditures_block_unknown == 0


def test_build_projects_gives_every_expenditure_the_block_it_belongs_to():
    """支出が属するブロック(`inBlock`の材料)が付くこと。

    何があれば落ちるか: ブロック番号を支出側に伝えない実装だと全件None。
    **段が付かない支出は段を区別せず合計されるので、29.9兆円の二重計上に
    そのまま戻る。**
    """
    rows = list(rs.parse_rs(_block_connection_fixture_paths()))
    result = rs.build_projects(rows, {}, {}, {})
    assert result.expenditures, "支出が1件も無い"
    assert {(e.project_id, e.seq): e.block_id for e in result.expenditures} == {
        ("1", 0): "A", ("11", 0): "C", ("284", 0): "F", ("177", 0): "F", ("1409", 0): "A",
    }
    # 張り先が必ずブロックとして実在すること(参照整合ゲートが見る条件)
    known = {(b.project_id, b.fiscal_year, b.block_id) for b in result.blocks}
    for exp in result.expenditures:
        if exp.block_id is not None:
            assert (exp.project_id, exp.fiscal_year, exp.block_id) in known, exp


def test_build_projects_leaves_the_expenditure_block_unset_without_the_connection_file():
    """5-2が無いリリースでは`block_id`が全件Noneになり、警報にもならないこと。

    何があれば落ちるか: 列の値をそのまま入れる実装だと、ブロックが1つも
    emitされないのに`budget:inBlock`が張られ、参照整合ゲートが
    リリース全体を止める。逆にこれを`expenditures_block_unknown`に数えると、
    5-2を渡さない既存の呼び出し全部で異常件数が立ち続けて意味を失う。
    """
    rows = list(rs.parse_rs(_full_fixture_paths()))
    result = rs.build_projects(rows, {}, {}, {})
    assert result.blocks == ()
    assert result.indirect_costs == ()
    assert result.expenditures, "支出が1件も無い"
    assert [e.block_id for e in result.expenditures] == [None] * len(result.expenditures)
    assert result.stats.expenditures_block_unknown == 0


def test_build_projects_counts_an_expenditure_whose_block_cannot_be_assembled(tmp_path: Path):
    """同じ事業に他のブロックはあるのに、その支出のブロック番号だけ解決できない

    場合は`inBlock`を張らず、件数を`expenditures_block_unknown`に数えること
    (実測0件。存在しないブロックURIを張ると参照整合ゲートがリリースを止める)。

    何があれば落ちるか: 列の値を無条件に使う実装だと件数0のまま`block_id`が
    'Z'になる(=グラフに型の無いURIが出る)。逆に黙って落とす実装だと
    `block_id`はNoneになるが件数が0のままで、段の付いていない支出の存在が
    誰にも見えない(欠陥型4)。
    """
    paths = _write_five_files(
        tmp_path,
        project_id="999999",
        project_name="合成: 支出先行のブロック番号がブロックに無い",
        ministry_name="内閣府",
        payee_rows=[
            _block_row({
                "project_id": "999999", "fiscal_year": "2025", "block_number": "A",
                "block_name": "実在するブロック", "block_amount": "1000",
            }),
            _block_row({
                "project_id": "999999", "fiscal_year": "2025", "block_number": "A",
                "recipient_name": "株式会社ウルフスタイル",
                "recipient_houjin_bangou": "3010001137944",
                "recipient_other_flag": "FALSE", "expenditure_amount": "1000",
            }),
            # ブロックZは5-1にも5-2にもブロックとして現れない(金額行も辺も無い)
            _block_row({
                "project_id": "999999", "fiscal_year": "2025", "block_number": "Z",
                "recipient_name": "株式会社日本政策金融公庫",
                "recipient_houjin_bangou": "8010001120391",
                "recipient_other_flag": "FALSE", "expenditure_amount": "2000",
            }),
        ],
        connection_rows=[
            _connection_row({
                "project_id": "999999", "fiscal_year": "2025",
                "block_from_name": "内閣府", "paid_by_government": "TRUE",
                "block_to": "A", "block_to_name": "実在するブロック",
            })
        ],
    )
    rows = list(rs.parse_rs(paths))
    assert [b.block_id for b in rows[0].blocks] == ["A"]
    # parse段階では列の値をそのまま持つ(verbatim)
    assert [line.block_id for line in rows[0].expenditures] == ["A", "Z"]

    result = rs.build_projects(rows, {}, {}, {})
    assert [e.block_id for e in result.expenditures] == ["A", None]
    assert result.stats.expenditures_block_unknown == 1


# =============================================================================
# 年度ごとの予算と執行(裁定B99)
#
# 実データ由来の実例(R45。2026-08-23取得の2-1から引用): project_id=828
# 「危険物事故防止対策の推進」。直近5年度分すべてを持ち、**FY2024の予備費等が
# -400,000円という負値**で、FY2023→FY2024・FY2024→FY2025の繰越しが
# 実際に連鎖している(翌年度への繰越し == 次年度の前年度からの繰越し)。
# レビューシート年度(2025)の執行額は0(まだ執行されていない)
# =============================================================================

#: 828の5年度分(予算年度 → (当初, 補正, 前年度繰越, 予備費等, 歳出予算現額,
#: 執行額, 翌年度繰越, 翌年度要求額))。**実データそのまま**
KIKENBUTSU_HISTORY = {
    "2021": (95_000_000, 0, 23_000_000, 0, 118_000_000, 99_000_000, 0, 85_000_000),
    "2022": (85_000_000, 44_000_000, 0, 0, 129_000_000, 77_000_000, 29_877_000, 25_259_000),
    "2023": (
        85_394_000, 12_980_000, 29_877_000, 0, 128_251_000, 96_455_000, 12_980_000, 110_110_000
    ),
    "2024": (
        97_130_000, 14_194_000, 12_980_000, -400_000, 123_904_000, 97_738_000, 7_594_000,
        109_861_000,
    ),
    "2025": (95_667_000, 40_150_000, 7_594_000, 0, 143_411_000, 0, 0, 136_095_000),
}


def _write_budget_history_files(
    tmp_path: Path, budget_rows: list[list[str]], *, project_id: str = "828"
) -> dict[str, Path]:
    """必須4ファイルをtmp_pathに書き、budget_summaryだけに中身を持たせる。

    `_write_five_files`(資金の流れ用)と同じ作法で、こちらは予算履歴を見るので
    支出先・法令を空にする。project_summaryは1事業(事業年度2025)だけ持つ。
    """
    from jgkg.transform import rs_columns

    project_spec = rs_columns.RS_FILES["project_summary"]
    _write_csv(
        tmp_path / "project_summary.csv",
        project_spec.full_header,
        [_full_row(project_spec, {
            "project_id": project_id, "fiscal_year": "2025",
            "project_name": "危険物事故防止対策の推進", "ministry_name": "総務省",
        })],
    )
    _write_csv(
        tmp_path / "budget_summary.csv",
        rs_columns.RS_FILES["budget_summary"].full_header,
        budget_rows,
    )
    _write_csv(
        tmp_path / "law.csv",
        rs_columns.RS_FILES["policy_measure_laws_and_regulations"].full_header,
        [],
    )
    _write_csv(
        tmp_path / "payee.csv",
        rs_columns.RS_FILES["payee_payment_information"].full_header,
        [],
    )
    return {
        "project_summary": tmp_path / "project_summary.csv",
        "budget_summary": tmp_path / "budget_summary.csv",
        "policy_measure_laws_and_regulations": tmp_path / "law.csv",
        "payee_payment_information": tmp_path / "payee.csv",
    }


def _budget_row(values: dict) -> list[str]:
    from jgkg.transform import rs_columns

    return _full_row(rs_columns.RS_FILES["budget_summary"], values)


def _history_rows(
    history: dict[str, tuple[int, ...]], *, project_id: str = "828"
) -> list[list[str]]:
    """`KIKENBUTSU_HISTORY` の形から集計行を作る(列の並びは実データと同じ)。

    **[22]翌年度要求額だけは `'85000000.0'` という小数表記で書く** ——
    実データの集計行23,036件すべてがこの形を取る(このファイルで唯一)。
    他の列と同じ整数表記にすると、fixtureだけが現実より易しい形になり、
    数字判定を自前で書いた実装がここを通ってしまう(rs_columns.py 検証13の
    訂正が記録している実際の事故がそれである)。
    """
    return [
        _budget_row({
            "project_id": project_id, "fiscal_year": "2025",
            "budget_fiscal_year": budget_fiscal_year,
            "budget_amount": str(initial),
            "supplementary_budget": str(supplementary),
            "carried_over_from_previous_year": str(carried_in),
            "reserve_fund": str(reserve),
            "total_budget_available": str(total),
            "executed_amount": str(executed),
            "carried_over_to_next_year": str(carried_out),
            "next_year_request": f"{next_year_request}.0",
        })
        for budget_fiscal_year, (
            initial, supplementary, carried_in, reserve, total, executed, carried_out,
            next_year_request,
        ) in history.items()
    ]


def test_parse_rs_gives_one_project_an_annual_budget_for_every_year_in_the_sheet(
    tmp_path: Path,
):
    """1事業が**年度ごとに別の**AnnualBudgetを持つこと(実測: 3,574事業が5年度分)。

    何があれば落ちるか: レビューシート年度の1件だけを取る実装(=このクラスを
    作る前の`budget_amount`だけの状態)なら1件しか出ずに落ちる。5年度分を
    1件に畳んでしまう実装でも落ちる —— **「増えた・減った」に答えるには
    年度ごとに別の記録である必要がある**。
    """
    paths = _write_budget_history_files(tmp_path, _history_rows(KIKENBUTSU_HISTORY))
    rows = list(rs.parse_rs(paths))
    assert len(rows) == 1
    annual = rows[0].annual_budgets
    assert [a.budget_fiscal_year for a in annual] == ["2021", "2022", "2023", "2024", "2025"]
    assert [a.initial_budget for a in annual] == [
        95_000_000, 85_000_000, 85_394_000, 97_130_000, 95_667_000
    ]
    # レビューシート年度の1件は`budget_amount`と同じ値(同じ列・同じ行から来る)
    assert rows[0].budget_amount == 95_667_000


def test_parse_rs_derives_the_year_set_from_the_data_not_from_a_hardcoded_range(
    tmp_path: Path,
):
    """年度の集合がデータ側の[13]予算年度から導出されること。

    何があれば落ちるか: 「2021〜2025」を定数で持つ実装だと、(a)1年度分しか
    配られていない事業(実測554事業)で存在しない4年度分を作ろうとし、
    (b)将来RSが6年度分を配ったときに最新年度を黙って捨てる。ここでは
    **2026年度を含み2021年度を含まない**集合を渡して両方を縛る。
    """
    history = {
        "2024": KIKENBUTSU_HISTORY["2024"],
        "2026": (100_000_000, 0, 0, 0, 100_000_000, 0, 0, 0),
    }
    paths = _write_budget_history_files(tmp_path, _history_rows(history))
    rows = list(rs.parse_rs(paths))
    assert [a.budget_fiscal_year for a in rows[0].annual_budgets] == ["2024", "2026"]


def test_parse_rs_keeps_a_zero_executed_amount_instead_of_dropping_it(tmp_path: Path):
    """レビューシート年度の執行額0が**欠損ではなく0として**残ること。

    何があれば落ちるか: `if executed:`や`or None`で判定する実装だと0がNoneに
    化け、emit側で述語ごと消える。**実測でレビューシート年度(2025)の執行額は
    5,794事業すべて0**なので、これを欠損として落とすと最新年度の執行額が
    「調べていない」と区別できなくなる(§8.2「欠損を0と混同しない」の逆向き)。
    予備費等0(2025)と翌年度への繰越し0も同じ理由で縛る。
    """
    paths = _write_budget_history_files(tmp_path, _history_rows(KIKENBUTSU_HISTORY))
    rows = list(rs.parse_rs(paths))
    latest = rows[0].annual_budgets[-1]
    assert latest.budget_fiscal_year == "2025"
    assert latest.executed_amount == 0
    assert latest.reserve_fund == 0
    assert latest.carried_over_to_next_year == 0


def test_parse_rs_keeps_negative_amounts_verbatim(tmp_path: Path):
    """減額(負値)がそのまま残ること。

    何があれば落ちるか: 金額を非負と仮定して`abs()`や0クリップをかける実装だと
    828のFY2024の予備費等-400,000円が符号を失い、**恒等式
    (当初+補正+前年度繰越+予備費等=歳出予算現額)が成立しなくなる** ——
    97,130,000+14,194,000+12,980,000-400,000=123,904,000。実測では
    補正予算589件・予備費等825件・繰越し各1件が負値を取る。
    """
    paths = _write_budget_history_files(tmp_path, _history_rows(KIKENBUTSU_HISTORY))
    row = next(iter(rs.parse_rs(paths)))
    annual = {a.budget_fiscal_year: a for a in row.annual_budgets}
    fy2024 = annual["2024"]
    assert fy2024.reserve_fund == -400_000
    assert (
        fy2024.initial_budget
        + fy2024.supplementary_budget
        + fy2024.carried_over_from_previous_year
        + fy2024.reserve_fund
        == fy2024.total_budget_available
    )


def test_parse_rs_reads_annual_budgets_from_the_aggregate_row_not_the_detail_rows(
    tmp_path: Path,
):
    """明細行(会計区分ごとの行。[14]当初予算（合計）が空)を集計行と混同しないこと。

    何があれば落ちるか: 「その予算年度の行」を無条件に採る実装だと、明細行を
    拾って8項目すべてがNoneのAnnualBudgetを作る(実測: 全47,100行のうち
    24,064行が明細行)。選択規則は`rs_columns.find_budget_aggregate_row`に
    1箇所だけ在るべきもので、ここはそれを使っていることを縛る。
    """
    rows_csv = _history_rows({"2024": KIKENBUTSU_HISTORY["2024"]})
    # 実データと同じ形の明細行([14]〜[22]がすべて空)
    rows_csv.append(_budget_row({
        "project_id": "828", "fiscal_year": "2025", "budget_fiscal_year": "2024",
    }))
    paths = _write_budget_history_files(tmp_path, rows_csv)
    rows = list(rs.parse_rs(paths))
    assert len(rows[0].annual_budgets) == 1
    assert rows[0].annual_budgets[0].initial_budget == 97_130_000


def test_parse_rs_counts_a_year_whose_aggregate_row_is_missing_instead_of_dropping_it(
    tmp_path: Path,
):
    """集計行が無い予算年度を黙って捨てず、parse段階で数えること。

    何があれば落ちるか: `continue`だけして数えない実装だと、予算履歴が丸ごと
    欠けたリリースが「AnnualBudget 0件」として正常に見える(実測では
    23,036組すべてが集計行をちょうど1件持つので、この数が0でなくなること
    自体が配布形態の変化の合図である)。
    """
    rows_csv = _history_rows({"2024": KIKENBUTSU_HISTORY["2024"]})
    # 2023年度は明細行しか無い(集計行が存在しない)
    rows_csv.append(_budget_row({
        "project_id": "828", "fiscal_year": "2025", "budget_fiscal_year": "2023",
    }))
    paths = _write_budget_history_files(tmp_path, rows_csv)
    stats = rs.RsParseStats()
    rows = list(rs.parse_rs(paths, stats=stats))
    assert [a.budget_fiscal_year for a in rows[0].annual_budgets] == ["2024"]
    assert stats.budget_summary_years_without_aggregate_row == 1


def test_parse_rs_represents_a_missing_amount_column_as_none_not_zero(tmp_path: Path):
    """金額8項目のうち空欄のものが`None`になること(0にしない)。

    何があれば落ちるか: 空文字を0として読む実装だと、欠損が合計に0円として
    混ざり「調べたら0だった」と区別できなくなる。実データの集計行では
    8列すべてが全件非空(rs_columns.py 検証13)なので、この経路は現時点の
    実データには現れない —— だからこそテストで縛る。
    """
    row = _budget_row({
        "project_id": "828", "fiscal_year": "2025", "budget_fiscal_year": "2024",
        "budget_amount": "97130000", "executed_amount": "97738000",
    })
    paths = _write_budget_history_files(tmp_path, [row])
    annual = next(iter(rs.parse_rs(paths))).annual_budgets[0]
    assert annual.initial_budget == 97_130_000
    assert annual.executed_amount == 97_738_000
    assert annual.supplementary_budget is None
    assert annual.carried_over_from_previous_year is None
    assert annual.reserve_fund is None
    assert annual.total_budget_available is None
    assert annual.carried_over_to_next_year is None
    assert annual.next_year_request is None


def test_parse_rs_gives_an_annual_budget_for_a_year_the_budget_project_does_not_cover():
    """事業年度の集計行が無い事業(`budget_amount`がNone)でも、別年度の

    AnnualBudgetは作られること(共有fixtureのproject_id=159は2023年度分だけを
    持つ)。**これがこのクラスを足した理由そのもの**である —— BudgetProjectの
    `budgetAmount`が答えられない年度について、AnnualBudgetが答える。
    """
    rows = {r.project_id: r for r in rs.parse_rs(_full_fixture_paths())}
    assert rows["159"].budget_amount is None
    assert [
        (a.budget_fiscal_year, a.initial_budget, a.executed_amount)
        for a in rows["159"].annual_budgets
    ] == [("2023", 10_041_533_000, 9_130_510_658)]


def test_build_projects_counts_annual_budgets_and_keeps_the_two_years_apart():
    """`BuildStats`が件数を持ち、`AnnualBudgetRecord`が2つの年度を別々に持つこと。

    何があれば落ちるか: `budget_fiscal_year`を`fiscal_year`で上書きする実装
    (=2つの年度を混同する)だと、159の記録が「2025年のシートが2025年度に
    ついて言っている」ことになり、`budgetAmount`との突き合わせ検査
    (`pipeline._annual_budget_project_amount_mismatches`)が誤って発火する。
    """
    rows = list(rs.parse_rs(_full_fixture_paths()))
    result = rs.build_projects(rows, MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.stats.annual_budgets_seen == len(result.annual_budgets) == 3
    by_project = {a.project_id: a for a in result.annual_budgets}
    assert by_project["159"].fiscal_year == "2025"
    assert by_project["159"].budget_fiscal_year == "2023"
    assert by_project["828"].fiscal_year == by_project["828"].budget_fiscal_year == "2025"


def test_build_projects_leaves_annual_budgets_empty_for_a_directly_built_row():
    """`RsRow`を直接組み立てる呼び出し元(tests/phase1_fixture.py等)では空のまま

    通ること(既定値を持つ理由)。`blocks`/`indirect_costs`と同じ扱い。
    """
    result = rs.build_projects([_row()], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE)
    assert result.annual_budgets == ()
    assert result.stats.annual_budgets_seen == 0


def test_parse_rs_reads_the_next_year_request_despite_its_decimal_form(tmp_path: Path):
    """[22]翌年度要求額の小数表記(`'45013000.0'`)が45013000として取り込まれること。

    実データ(project_id=1「内閣人事局経費（研修事業）」のFY2021)そのままの値。
    **集計行23,036件すべてがこの形を取り、このファイルで小数表記の列はここだけ**
    である。

    何があれば落ちるか: `str.isdigit()`のような自前の数字判定でこの列を読む
    実装だと、値のある行が全件「空」に見えて`None`になる ——
    **それが実際に起きて、この列は一度「集計行23,036件すべてで空」と記録され
    モデル化の対象外にされていた**(rs_columns.py 検証13の訂正)。
    `int()`に素で渡す実装なら`ValueError`で落ちる。正しい経路は
    `normalize_amount`(末尾の`.0`を落とす実装がTask 7の時点からある)。
    """
    row = _budget_row({
        "project_id": "1", "fiscal_year": "2025", "budget_fiscal_year": "2021",
        "budget_amount": "29457000", "supplementary_budget": "0",
        "carried_over_from_previous_year": "0", "reserve_fund": "0",
        "total_budget_available": "29457000", "executed_amount": "23771000",
        "carried_over_to_next_year": "0", "next_year_request": "45013000.0",
    })
    paths = _write_budget_history_files(tmp_path, [row], project_id="1")
    annual = next(iter(rs.parse_rs(paths))).annual_budgets[0]
    assert annual.next_year_request == 45013000
    assert isinstance(annual.next_year_request, int)


def test_parse_rs_reads_a_zero_next_year_request_as_zero_not_missing(tmp_path: Path):
    """`'0.0'`が**0として**取り込まれること(`None`にしない)。

    ゼロ要求は端のケースではなく主流である —— 実測で集計行23,036件のうち
    **3,838件が`'0.0'`**(残り19,198件が非ゼロ)。

    何があれば落ちるか: `.0`を落とした後の`'0'`を空と同じ扱いにする実装、
    あるいは`float(s) or None`のような書き方だと0がNoneに化け、
    「要求しなかった」が「調べていない」と区別できなくなる。
    """
    row = _budget_row({
        "project_id": "4", "fiscal_year": "2025", "budget_fiscal_year": "2021",
        "budget_amount": "29457000", "next_year_request": "0.0",
    })
    paths = _write_budget_history_files(tmp_path, [row], project_id="4")
    annual = next(iter(rs.parse_rs(paths))).annual_budgets[0]
    assert annual.next_year_request == 0


def test_parse_rs_next_year_request_lines_up_with_the_following_years_initial_budget(
    tmp_path: Path,
):
    """年度Yの翌年度要求額と年度Y+1の当初予算が**同じ事業の別ノードから引ける**こと。

    これが`nextYearRequest`をモデル化する理由そのもの ——「いくら要求して、
    いくら付いたか」。828では FY2021 に85,000,000円を要求して FY2022 の
    当初予算が85,000,000円(比1.00)、FY2022 に25,259,000円を要求して
    FY2023 が85,394,000円(比3.38)である。**一致を仮定しない**
    (`carriedOverToNextYear`と同じ理由: 事業の分割・統合・終了がある)。

    何があれば落ちるか: 翌年度要求額を年度Y+1のノードに載せる実装(1年
    ずらして持たせる)だと、この対応が取れなくなる。
    """
    paths = _write_budget_history_files(tmp_path, _history_rows(KIKENBUTSU_HISTORY))
    annual = {a.budget_fiscal_year: a for a in next(iter(rs.parse_rs(paths))).annual_budgets}
    assert annual["2021"].next_year_request == 85_000_000
    assert annual["2022"].initial_budget == 85_000_000
    assert annual["2022"].next_year_request == 25_259_000
    assert annual["2023"].initial_budget == 85_394_000


def test_build_projects_carries_the_next_year_request_onto_the_record(tmp_path: Path):
    """`AnnualBudgetRecord`が翌年度要求額を持つこと(emitの入力)。

    何があれば落ちるか: `AnnualBudgetLine`では読めているのに
    `build_projects`の転記を忘れた実装だと、parse層のテストは緑のまま
    RDFにだけ出ない(資金の流れのブロックで同型の欠陥を踏んだ経路)。
    """
    paths = _write_budget_history_files(tmp_path, _history_rows(KIKENBUTSU_HISTORY))
    result = rs.build_projects(
        list(rs.parse_rs(paths)), MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE
    )
    by_year = {a.budget_fiscal_year: a for a in result.annual_budgets}
    assert by_year["2024"].next_year_request == 109_861_000
    assert by_year["2025"].next_year_request == 136_095_000
