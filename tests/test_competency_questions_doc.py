"""CQのファイルと `schema/competency-questions.md` の対応を機械的に確かめる。

**なぜ必要か。** 2026-09-11〜12に**CQを6本足した**(CQ15〜CQ20。裁定B103)。
そのたびに文書の3箇所を手で直した ——一覧の表・問いの節・「答えの例」の表。
**手で3箇所を直す作業は、いつか1箇所を忘れる。**

忘れたときに何が起きるか:

- **一覧に無いCQ**: `scripts/run_cq.py`のゲートは`cq*.rq`のglobなので実行はされるが、
  **そのCQが何に答えるのかを書いた場所が無い。** オントロジーの正本は
  `schema/competency-questions.md`であり(設計書§4)、そこに無い問いは
  「このKGが答えられること」の一覧から漏れる
- **「答えの例」に無いCQ**: fixtureでの期待値が文書に無いので、
  **テストの期待値が正しいかどうかを文書と突き合わせられない** ——
  このプロジェクトが繰り返し使う「独立した2経路で一致を見る」が片方欠ける
- **文書にあってファイルが無いCQ**: 存在しない問いに答えられると書いている
  (再発欠陥6: 文書が嘘を書いている)

`tests/test_decision_log_references.py`が裁定の参照について同じことを
しているので、その形に倣う。

**`p0-*.rq`と`legacy-*.rq`は対象外。** Phase 0の作業用クエリと、
役目を終えた旧版であり、CQの一覧に載せるものではない(実際に載っていない)。
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CQ_DIR = _REPO_ROOT / "queries" / "cq"
_DOC = _REPO_ROOT / "schema" / "competency-questions.md"

#: 「答えの例」テーブルの行(`| CQ15 | 厚生労働省: … |`)。
_ANSWER_ROW_RE = re.compile(r"^\|\s*CQ(\d+)\s*\|", re.MULTILINE)

# **この検査が空回りしないための下限。** globが壊れて0本になると、
# 「対応が取れていないCQは無い」という主張は自動的に真になる(欠陥型2)。
# 2026-09-12の実測はCQ20本。
_MIN_CQ_FILES = 14


def _cq_files() -> dict[int, str]:
    """CQ番号 → ファイル名。`p0-*`と`legacy-*`は含めない。"""
    found: dict[int, str] = {}
    for path in sorted(_CQ_DIR.glob("cq*.rq")):
        match = re.match(r"cq(\d+)", path.name)
        assert match, f"CQファイルの名前から番号を取れない: {path.name}"
        found[int(match.group(1))] = path.name
    return found


def test_every_cq_file_is_described_in_the_document() -> None:
    """**すべてのCQファイルが文書に登場する**こと(ファイル名で参照されている)。

    何があれば落ちるか: `queries/cq/cq21-….rq`を足して
    `schema/competency-questions.md`に何も書かないと落ちる。
    """
    files = _cq_files()
    assert len(files) >= _MIN_CQ_FILES, (
        f"CQファイルが{len(files)}本しか見つからない(実測20本)。"
        "globが壊れて検査が空回りしている疑い"
    )
    doc = _DOC.read_text(encoding="utf-8")
    missing = sorted(name for name in files.values() if name not in doc)
    assert not missing, (
        f"`schema/competency-questions.md`がこれらのCQファイルに触れていない: {missing}。"
        "CQは正本の文書に問いを書いてから足すこと(設計書§4)"
    )


def test_every_cq_number_in_the_document_has_a_file() -> None:
    """**文書が挙げるCQ番号にファイルが実在する**こと。

    何があれば落ちるか: 文書に「CQ21」と書いてファイルを作らないと落ちる
    ——存在しない問いに答えられると書いている状態(再発欠陥6)。
    """
    files = _cq_files()
    doc = _DOC.read_text(encoding="utf-8")
    # 本文中の言及も拾う(`CQ12`・`CQ12・CQ13`等)。`CQ`+数字だけを見る。
    mentioned = {int(n) for n in re.findall(r"\bCQ(\d+)\b", doc)}
    dangling = sorted(mentioned - set(files))
    assert not dangling, (
        f"文書が挙げているのにファイルが無いCQ: {dangling}。"
        f"実在するのは {sorted(files)}"
    )


def test_every_cq_has_a_row_in_the_expected_answers_table() -> None:
    """**すべてのCQが「答えの例」テーブルに行を持つ**こと。

    そこがfixtureでの期待値を人間が読める形で書いてある唯一の場所であり、
    **テストの期待値と突き合わせる相手**である(独立した2経路のうちの片方)。

    何があれば落ちるか: CQを足してクエリとテストだけ書き、
    「答えの例」に行を足さないと落ちる。
    """
    files = _cq_files()
    doc = _DOC.read_text(encoding="utf-8")
    rows = {int(n) for n in _ANSWER_ROW_RE.findall(doc)}
    assert rows, "「答えの例」テーブルの行を1つも取れていない(検査が空回り)"
    without_row = sorted(set(files) - rows)
    assert not without_row, (
        f"「答えの例」テーブルに行が無いCQ: {without_row}。"
        "fixtureでの期待値を文書に書くこと(テストの期待値と突き合わせる相手になる)"
    )
