"""`/overview`の検査。

**このモジュールの中心は「数字の出所がCQファイルであること」の固定である**
(裁定B103)。`overview.py`に手書きのSPARQLを書き始めたら落ちる形にしてある
——`warmup.py`が裁定B60で確立した規律と、`tests/test_api_warmup.py`が
それをspyで固定しているやり方に倣う。

**spyテストだけでは足りない層がある。** spyテストは「CQファイルの中身が
そのままclientに届くこと」しか見ない——`build_overview`が返した行を
`models.py`の型へ正しく詰め替えているか(変数名の対応・OPTIONALの扱い・
`bool`の字句形の解釈)は別に検査する必要がある。それを検査しないと、
このプロジェクトが繰り返し扱ってきた再発欠陥9「実データに一度も当てていない
層は緑でも未検証」の再発になる——そのため`test_warm_up_end_to_end_against_
the_rdflib_fixture_succeeds`(`tests/test_api_app.py`)と同じ形で、
fixtureの実データに対して`build_overview`を1本走らせる検査を最後に足す。
"""

from __future__ import annotations

import re
from pathlib import Path

_OVERVIEW_PY = Path(__file__).resolve().parents[1] / "src" / "jgkg" / "api" / "overview.py"

# SPARQLのキーワードが`overview.py`の中に現れたら、手書きのクエリを
# 持ち始めた徴候である。
_SPARQL_MARKERS = ("SELECT ", "WHERE {", "PREFIX ", "GROUP BY", "CONSTRUCT ")


def test_overview_module_contains_no_handwritten_sparql() -> None:
    """**`overview.py`に手書きのSPARQLが無い**こと(裁定B103/B60)。

    何があれば落ちるか: `overview.py`に`SELECT ... WHERE { ... }`を
    書き込むと落ちる。画面用の集計経路を作らせないための歯止めである。
    """
    source = _OVERVIEW_PY.read_text(encoding="utf-8")
    # docstring/コメント中の言及は除く(行頭の`#`と、三重引用符の中)
    code = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
    code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("#"))
    found = [m for m in _SPARQL_MARKERS if m in code]
    assert not found, (
        f"overview.py が手書きのSPARQLを持っている: {found}。"
        "数字の出所は queries/cq/*.rq でなければならない(裁定B103)"
    )


#: `OVERVIEW_QUERIES`が指すべきCQ番号を、**このテストが独立に固定する**
#: (ブリーフのSTEP2原案から強化。下のテストのdocstring「実測した事実」参照)。
_EXPECTED_OVERVIEW_QUERIES = {
    "ministries": "cq15-ministry-budget-ranking.rq",
    "budget_and_execution": "cq14-budget-and-execution-by-year.rq",
    "request_and_initial": "cq16-request-vs-initial-budget.rq",
    "recipient_identification": "cq17-recipient-identification.rq",
    "type_counts": "cq18-kg-scale.rq",
    "government_paid": "cq12-government-paid-total.rq",
    "money_through_stages": "cq13-money-passing-through-stages.rq",
}


def test_overview_reads_the_cq_files_and_sends_them_verbatim(tmp_path) -> None:
    """**CQファイルの中身がそのままclientに届く**こと。

    何があれば落ちるか: `overview.py`がCQを読まずに自分で組み立てた
    クエリを送るようになると、届いた文字列がファイルの中身と一致せず落ちる。

    **実測した事実(壊し確認2件目。ブリーフのSTEP2原案からの訂正)**:
    ブリーフ原案は`for name in overview.OVERVIEW_QUERIES.values()`で期待値を
    導いていたが、これは**モジュール自身の辞書を読み返すだけ**——
    `OVERVIEW_QUERIES`の1項目を別の(実在する)CQファイル名に向け違えても
    (例: `money_through_stages`をCQ13からCQ4に向け違える)、期待値の側も
    一緒にずれるため**検出できない**ことを実際に壊して確認した
    (task-2-report.md参照)。そのため対応表を`_EXPECTED_OVERVIEW_QUERIES`
    としてこのテストに独立して持たせ、まずそれと一致することを固定する。
    """
    sent: list[str] = []

    class SpyClient:
        def query(self, sparql: str):
            sent.append(sparql)
            return []

    from jgkg.api import overview

    overview.build_overview(SpyClient(), "https://jgkg.norr-tech.com", Path("queries/cq"))
    assert sent, "1本もクエリが送られていない"
    assert overview.OVERVIEW_QUERIES == _EXPECTED_OVERVIEW_QUERIES, (
        f"OVERVIEW_QUERIES が期待するCQ番号との対応から外れている: {overview.OVERVIEW_QUERIES}"
    )
    for name in _EXPECTED_OVERVIEW_QUERIES.values():
        expected = (Path("queries/cq") / name).read_text(encoding="utf-8")
        assert expected in sent, f"{name} の中身がそのまま送られていない"


# =============================================================================
# fixtureの実データに対する結合テスト(spyテストが見ない層を埋める)
# =============================================================================

BASE = "https://jgkg.norr-tech.com"


def test_build_overview_end_to_end_against_the_rdflib_fixture_succeeds(tmp_path, monkeypatch) -> None:
    """**実データ(fixture)に対して`build_overview`が最後まで成功し、
    7項目すべてに行が入る**こと。

    spyテストは「送ったクエリの文字列」しか見ておらず、返ってきた行を
    `MinistryBudget`等へ正しく詰め替えられるかは検査していない——
    ここでは`tests/phase1_fixture.py`の実データ(CQ12〜CQ18が既に
    `tests/test_competency_questions_phase1.py`で非空を確認済み)に対して
    実際に組み立てさせ、各項目が空でないこと・`sources`が
    `OVERVIEW_QUERIES`と一致することを見る。

    `tests/phase1_fixture.py`を手で呼ぶときは`JGKG_LAKE_DIR`等を設定する
    必要がある(設定せずに呼ぶと実レイクに書きに行く)——`monkeypatch`で
    設定し、テスト終了時に自動で元に戻す(`tests/test_api_app.py`の
    `tmp_env`fixtureと同じ形)。
    """
    import phase1_fixture as fx
    from rdflib import Dataset

    from jgkg.api.kgclient import RdflibKGClient
    from jgkg.api.overview import OVERVIEW_QUERIES, build_overview
    from jgkg.config import get_settings

    monkeypatch.setenv("JGKG_BASE_URI", BASE)
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    get_settings.cache_clear()
    try:
        kg: Dataset = fx.build_dataset(tmp_path / "out")
    finally:
        get_settings.cache_clear()

    client = RdflibKGClient(kg)
    result = build_overview(client, BASE, Path("queries/cq"))

    assert result.sources == OVERVIEW_QUERIES
    assert result.ministries, "CQ15: 府省の予算行が1件も無い"
    assert result.budget_and_execution, "CQ14: 予算年度の内訳行が1件も無い"
    assert result.request_and_initial, "CQ16: 要求額/当初予算の行が1件も無い"
    assert result.recipient_identification, "CQ17: 照合区分の行が1件も無い"
    assert result.type_counts, "CQ18: 型別件数の行が1件も無い"
    assert result.government_paid, "CQ12: 国が自ら支払った額の行が1件も無い"
    assert result.money_through_stages, "CQ13: 通過金の段の行が1件も無い"

    # `paid_by_government`が実際にPython の bool へ詰め替わっていること
    # (字句形"true"/"false"の解釈を誤ると常にTrue/Falseに偏ったり、
    # 例外になったりする)。
    assert {stage.paid_by_government for stage in result.money_through_stages} <= {True, False}
