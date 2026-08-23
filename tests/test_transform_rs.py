"""budgetモジュールの変換(parse_rs / build_projects)のテスト。Task 7 brief Step 2〜4。

**実在の値を使う**(R45)。project_id は実在のRS実データ(2026-08-23取得、
rs_columns.pyの照合記録と同一スナップショット)由来: 1(内閣人事局経費)/
4・11・5551(デジタル庁)/828(消防庁。政策所管府省庁≠府省庁の実例)/
159(内閣府。特別会計detail行3件の実例)。法令IDは523AC…ではなく実在の
503AC0000000036(デジタル庁設置法)・322AC0000000120(国家公務員法)を使う。
法人番号は3010001137944(株式会社ウルフスタイル。実在)。
架空にする必要があるケース(NO_CANDIDATE等の負例)は明らかに合成と分かる値
(法人番号9999999999999、事業ID999999等)を使う。
"""
from pathlib import Path

import pytest

from jgkg.transform import rs
from jgkg.transform.law import LawRecord
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

    支出先行から法人番号・金額を取ること。
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
    basis_law_citations=(),
    expenditures=(),
):
    return rs.RsRow(
        project_id=project_id,
        fiscal_year=fiscal_year,
        project_name=project_name,
        ministry_name=ministry_name,
        budget_amount=budget_amount,
        basis_law_citations=tuple(basis_law_citations),
        expenditures=tuple(expenditures),
    )


def test_build_projects_resolves_ministry_via_the_reference_table():
    result = rs.build_projects([_row(ministry_name="デジタル庁")], MINISTRY_REF, LAWS_BY_ID, LAWS_BY_TITLE)
    assert len(result.projects) == 1
    assert result.projects[0].ministry_houjin_bangou == DIGITAL_AGENCY.houjin_bangou
    assert result.stats.ministries_resolved == 1
    assert result.stats.ministries_unresolved == 0


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
