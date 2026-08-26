"""ministry_succession(C-1: 旧省庁→新府省の継承マッピング抽出)のテスト。

前半は小さな合成木(構造だけを検証する、狭い技術的性質のためのR45許容
範囲の合成データ)。後半は`412CO0000000315`の実応答fixture(無編集。R45)
を使った終端テストと、ブリーフが要求する3つの壊し確認。
"""
import copy
import json
from pathlib import Path

import pytest

from jgkg.transform import ministry_succession as ms
from jgkg.transform.old_ministries import load_old_ministries

FIXTURES = Path(__file__).parent / "fixtures"
REAL_LAW_ID = "412CO0000000315"


def _load_real_law_full_text() -> dict:
    data = json.loads(
        (FIXTURES / "egov_law_data_412CO0000000315.json").read_text(encoding="utf-8")
    )
    return data["law_full_text"]


def _header_row(old_text: str = "従前の府省", new_text: str = "新府省") -> dict:
    return {
        "tag": "TableRow",
        "attr": {},
        "children": [
            {"tag": "TableColumn", "attr": {}, "children": [old_text]},
            {"tag": "TableColumn", "attr": {}, "children": [new_text]},
        ],
    }


def _data_row(old_text: str, new_text: str) -> dict:
    return {
        "tag": "TableRow",
        "attr": {},
        "children": [
            {"tag": "TableColumn", "attr": {}, "children": [old_text]},
            {"tag": "TableColumn", "attr": {}, "children": [new_text]},
        ],
    }


def _table(*rows: dict) -> dict:
    return {"tag": "Table", "attr": {}, "children": list(rows)}


def _wrap(*tables: dict) -> dict:
    """Tableノードを、Table以外のタグを持つ入れ子(現実のTableStruct等を

    模した)の中に埋め込む。位置を仮定した走査だと見つからないことを
    保証するための最小限の入れ子。
    """
    return {
        "tag": "Law",
        "attr": {},
        "children": [
            {"tag": "LawBody", "attr": {}, "children": [
                {"tag": "SomeWrapper", "attr": {}, "children": [
                    {"tag": "TableStruct", "attr": {}, "children": list(tables)},
                ]},
            ]},
        ],
    }


# =============================================================================
# 合成木: テーブル発見・ヘッダ同定
# =============================================================================


def test_finds_a_table_regardless_of_nesting_depth_or_position():
    """位置を仮定した走査(例: children[1].children[2]...)ではなく、

    再帰的にTableタグを探すこと。深い入れ子・兄弟の中に埋まっていても
    見つかる。
    """
    tree = _wrap(_table(_header_row(), _data_row("旧A", "新A")))
    table = ms.select_succession_table(tree)
    assert table["tag"] == "Table"
    assert len(table["children"]) == 2


def test_no_qualifying_table_raises_a_clear_error():
    tree = _wrap(_table({"tag": "TableRow", "attr": {}, "children": [
        {"tag": "TableColumn", "attr": {}, "children": ["無関係な見出しA"]},
        {"tag": "TableColumn", "attr": {}, "children": ["無関係な見出しB"]},
    ]}))
    with pytest.raises(ms.NoQualifyingTableError, match="見つからない"):
        ms.select_succession_table(tree)


def test_two_qualifying_tables_are_ambiguous_and_rejected():
    """何があれば落ちるか: 「最初に見つかったTableを使う」に戻すと、

    2件目の存在に気づかず片方を黙って選んでしまう。
    """
    tree = _wrap(
        _table(_header_row(), _data_row("旧A", "新A")),
        _table(_header_row(), _data_row("旧B", "新B")),
    )
    with pytest.raises(ms.AmbiguousTableError, match="2件"):
        ms.select_succession_table(tree)


def test_header_column_roles_do_not_assume_position():
    """ヘッダの列の順序が入れ替わっても、文言から正しく同定できること。"""
    normal = ms._header_column_roles(["従前の府省", "新府省"])
    swapped = ms._header_column_roles(["新府省", "従前の府省"])
    assert normal == {"old": 0, "new": 1}
    assert swapped == {"old": 1, "new": 0}


def test_header_column_roles_returns_none_when_unrecognizable():
    assert ms._header_column_roles(["見出しA", "見出しB"]) is None
    # 「従前」も「新」も無い3列、「新」を含む列が無い、等
    assert ms._header_column_roles(["従前の府省", "従前の府省"]) is None


# =============================================================================
# 合成木: 括弧限定の除去
# =============================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("大蔵省(造幣局、印刷局及び国税庁を除く。)", "大蔵省"),
        ("大蔵省（造幣局、印刷局及び国税庁を除く。）", "大蔵省"),
        ("建設省", "建設省"),
        ("外務省", "外務省"),
    ],
)
def test_strip_trailing_qualifier(raw, expected):
    assert ms.strip_trailing_qualifier(raw) == expected


# =============================================================================
# 合成木: 行の抽出(セル数・空セル)
# =============================================================================


def test_extract_succession_rows_basic():
    tree = _wrap(_table(_header_row(), _data_row("旧A", "新A"), _data_row("旧B", "新B")))
    result = ms.extract_succession_rows(tree, source_law_id="TEST0000000001")
    assert [r.old_name for r in result.rows] == ["旧A", "旧B"]
    assert [r.new_name for r in result.rows] == ["新A", "新B"]
    assert [r.row_index for r in result.rows] == [1, 2]
    assert all(r.source_law_id == "TEST0000000001" for r in result.rows)
    assert result.dropped_rows == []


def test_ragged_row_is_rejected_not_silently_interpreted():
    bad_row = {
        "tag": "TableRow", "attr": {},
        "children": [{"tag": "TableColumn", "attr": {}, "children": ["旧A単独"]}],
    }
    tree = _wrap(_table(_header_row(), bad_row))
    with pytest.raises(ms.RaggedRowError, match="row_index=1"):
        ms.extract_succession_rows(tree, source_law_id="TEST0000000001")


def test_a_row_with_an_empty_old_cell_is_dropped_and_reported_not_silently_lost():
    """何があれば落ちるか: 空セルを無条件で残すと、意味の確定していない

    行(旧が空)が対応表の一部として紛れ込む。逆に無条件で無視すると
    ブリーフの「落とすなら件数を報告すること」に違反する——
    `dropped_rows` に(row_index, 理由)として残ることを検査する。
    """
    tree = _wrap(
        _table(
            _header_row(),
            _data_row("旧A", "新A"),
            _data_row("", "新B(旧側が結合セルで空)"),
            _data_row("旧C", "新C"),
        )
    )
    result = ms.extract_succession_rows(tree, source_law_id="TEST0000000001")
    assert [r.old_name for r in result.rows] == ["旧A", "旧C"]
    assert result.dropped_rows == [(2, "old cell empty")]


def test_a_row_with_an_empty_new_cell_is_dropped_and_reported():
    tree = _wrap(_table(_header_row(), _data_row("旧A", "")))
    result = ms.extract_succession_rows(tree, source_law_id="TEST0000000001")
    assert result.rows == []
    assert result.dropped_rows == [(1, "new cell empty")]


# =============================================================================
# 合成木: 18名称への解決(多対多の拒否)
# =============================================================================


def _row(old_name: str, new_name: str, row_index: int = 1) -> ms.SuccessionRow:
    return ms.SuccessionRow(
        source_law_id="TEST0000000001", row_index=row_index,
        old_text=old_name, new_text=new_name, old_name=old_name, new_name=new_name,
    )


def test_resolve_exact_match():
    rows = [_row("大蔵省", "財務省", row_index=1)]
    result = ms.resolve_old_ministries(rows, frozenset({"大蔵省"}))
    assert result.unresolved == []
    assert len(result.resolved) == 1
    assert result.resolved[0].mechanism == "exact"


def test_resolve_prefix_decomposition_using_another_target_name():
    """「総理府XXX」のように、対象名Aが対象名Bを接頭辞として連結された

    形でしか現れない行を解決できること(実データで確認したパターン)。
    """
    rows = [_row("総理府北海道開発庁", "国土交通省", row_index=1)]
    result = ms.resolve_old_ministries(rows, frozenset({"総理府", "北海道開発庁"}))
    resolved_by_name = {r.target_name: r for r in result.resolved}
    assert "北海道開発庁" in resolved_by_name
    assert "prefix-decomposition" in resolved_by_name["北海道開発庁"].mechanism
    # 「総理府」自身は行が無いので未解決のまま(自動で埋めない)
    assert "総理府" in result.unresolved


def test_unresolved_names_are_reported_by_name_not_silently_skipped():
    rows = [_row("大蔵省", "財務省")]
    result = ms.resolve_old_ministries(rows, frozenset({"大蔵省", "存在しない省"}))
    assert result.unresolved == ["存在しない省"]


def test_a_target_name_matching_two_rows_is_ambiguous():
    rows = [_row("大蔵省", "財務省A", row_index=1), _row("大蔵省", "財務省B", row_index=2)]
    with pytest.raises(ms.AmbiguousResolutionError, match="大蔵省"):
        ms.resolve_old_ministries(rows, frozenset({"大蔵省"}))


def test_a_row_matching_two_target_names_is_ambiguous():
    """1行が複数の対象名に一致する状況(通常は起きないはずの構造的な

    矛盾)も検出すること。「甲乙丙」は「甲省乙省丙省」自体は対象名では
    ないが、2通りの接頭辞分解(「甲」+「乙丙」、「甲乙」+「丙」)が
    どちらも対象名の組に一致してしまう、という構造的な多重解釈を作る。
    """
    rows = [_row("甲乙丙", "丁", row_index=1)]
    with pytest.raises(ms.AmbiguousResolutionError, match="row_index"):
        ms.resolve_old_ministries(rows, frozenset({"甲", "乙丙", "甲乙", "丙"}))


# =============================================================================
# 実データ: 412CO0000000315の実応答(R45。無編集)
# =============================================================================


def test_extracts_all_58_data_rows_from_the_real_law_with_no_drops():
    law_full_text = _load_real_law_full_text()
    result = ms.extract_succession_rows(law_full_text, source_law_id=REAL_LAW_ID)
    assert len(result.rows) == 58
    # 実データにブリーフが説明する空セル行は無かった(下の
    # 気になる点参照。壊し確認は合成データで別途行う)
    assert result.dropped_rows == []
    assert result.rows[0].old_name == "総理府"
    assert result.rows[0].new_name == "内閣府"
    assert result.rows[0].row_index == 1


def test_18_old_ministries_all_resolve_against_the_real_table():
    """網羅の検査(ブリーフの受け入れ条件)。対象0件でも通る形にしない

    ——実際に18件という対象集合を数え、その**具体的な名称の集合**が
    一致することまで検査する(件数だけの一致は偶然の一致を許すため)。
    """
    law_full_text = _load_real_law_full_text()
    result = ms.extract_succession_rows(law_full_text, source_law_id=REAL_LAW_ID)
    target_names = load_old_ministries()
    assert len(target_names) == 18

    coverage = ms.resolve_old_ministries(result.rows, frozenset(target_names))

    assert coverage.unresolved == []
    resolved_names = {r.target_name for r in coverage.resolved}
    assert resolved_names == target_names

    # 「総理府」+外局名の連結でしか現れない8件はprefix-decomposition経由
    # であることを明示する(黒魔術で一致させていないことの検査)
    prefix_resolved = {
        r.target_name for r in coverage.resolved if "prefix-decomposition" in r.mechanism
    }
    assert prefix_resolved == {
        "金融再生委員会", "総務庁", "北海道開発庁", "科学技術庁",
        "経済企画庁", "環境庁", "沖縄開発庁", "国土庁",
    }
    exact_resolved = resolved_names - prefix_resolved
    assert exact_resolved == target_names - prefix_resolved


def test_18_old_ministries_resolution_reports_a_manufactured_unresolved_name():
    """壊し確認: 網羅検査が実際に「解決できない名称」を報告できること。

    実データは18/18解決してしまうため(non-vacuityの検査は上の
    テストが別途担う)、対象集合に実在しない19番目の名称を混ぜて、
    それが確実に unresolved として名指しされることを確認する。
    """
    law_full_text = _load_real_law_full_text()
    result = ms.extract_succession_rows(law_full_text, source_law_id=REAL_LAW_ID)
    target_names = load_old_ministries() | {"存在しない省庁2026"}

    coverage = ms.resolve_old_ministries(result.rows, frozenset(target_names))

    assert coverage.unresolved == ["存在しない省庁2026"]


def test_header_role_detection_breaks_loudly_when_header_text_is_corrupted():
    """壊し確認: ヘッダの同定を壊すと落ちること。"""
    law_full_text = copy.deepcopy(_load_real_law_full_text())
    table = ms.select_succession_table(law_full_text)  # 壊す前に一度確認しておく
    header_cells = table["children"][0]["children"]
    header_cells[0]["children"] = ["無関係な見出しに置き換えた"]
    header_cells[1]["children"] = ["これも無関係"]

    with pytest.raises(ms.NoQualifyingTableError):
        ms.extract_succession_rows(law_full_text, source_law_id=REAL_LAW_ID)


def test_header_swap_flips_old_and_new_in_the_extracted_rows():
    """壊し確認: 列の意味が(ヘッダごと)逆になったら、位置ではなくヘッダの

    文言で追随して検出できるか。位置を決め打ちにした実装だと、ヘッダを
    入れ替えても旧・新の割り当てが変わらない(誤ったまま気づかない)。
    """
    law_full_text = copy.deepcopy(_load_real_law_full_text())
    original = ms.extract_succession_rows(
        copy.deepcopy(law_full_text), source_law_id=REAL_LAW_ID
    )

    table = ms.select_succession_table(law_full_text)
    header_cells = table["children"][0]["children"]
    header_cells[0]["children"], header_cells[1]["children"] = (
        header_cells[1]["children"],
        header_cells[0]["children"],
    )

    swapped = ms.extract_succession_rows(law_full_text, source_law_id=REAL_LAW_ID)

    assert [r.old_name for r in swapped.rows] == [r.new_name for r in original.rows]
    assert [r.new_name for r in swapped.rows] == [r.old_name for r in original.rows]


def test_dropped_row_count_is_reported_when_a_real_row_is_synthetically_emptied():
    """壊し確認: 空セルの行を落とすなら、落とした件数が報告されること。

    実データには空セルが無いため(気になる点参照)、実データの1行を
    合成的に空にして、`dropped_rows` が実際に1件を記録することを確認する
    (R45: 狭い技術的性質のための合成データとして正当化される変更)。
    """
    law_full_text = copy.deepcopy(_load_real_law_full_text())
    table = ms.select_succession_table(law_full_text)
    table["children"][5]["children"][0]["children"] = [""]

    result = ms.extract_succession_rows(law_full_text, source_law_id=REAL_LAW_ID)

    assert result.dropped_rows == [(5, "old cell empty")]
    assert len(result.rows) == 57
