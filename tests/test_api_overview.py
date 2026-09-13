"""`/overview`の検査。

**このモジュールの中心は「数字の出所がCQファイルであること」の固定である**
(裁定B103)。`overview.py`に手書きのSPARQLを書き始めたら落ちる形にしてある
——`warmup.py`が裁定B60で確立した規律と、`tests/test_api_warmup.py`が
それをspyで固定しているやり方に倣う。

**spyテストだけでは足りない層がある。** spyテストは「CQファイルの中身が
そのままclientに届くこと」しか見ない——`build_overview`が返した行を
`models.py`の型へ正しく詰め替えているか(変数名の対応・`bool`の字句形の
解釈)は別に検査する必要がある。それを検査しないと、このプロジェクトが
繰り返し扱ってきた再発欠陥9「実データに一度も当てていない層は緑でも
未検証」の再発になる——そのため`test_warm_up_end_to_end_against_the_
rdflib_fixture_succeeds`(`tests/test_api_app.py`)と同じ形で、fixtureの
実データに対して`build_overview`を1本走らせる検査を最後に足す。

**修正ラウンド1(レビュー`task-2-review.md`)で、このモジュールの検査を
2つ強化した。** 詳細は各テストのdocstring参照:

1. 手書きSPARQL検査(`test_overview_module_contains_no_handwritten_sparql`)
   は文字列の字面を見るだけの検査であり、**振る舞いを見る検査
   (`test_overview_reads_the_cq_files_and_sends_them_verbatim`)より弱い**
   ——三重引用符の定数文字列で手書きすれば素通りできた(レビューで実証)。
   後者を「届いた本数+内容の完全一致」に強化し、これが主たる歯止めになる。
2. `OverviewResponse`のフィールド名が`OVERVIEW_QUERIES`のキーと一致する
   ことを固定するテストを足した(無いとPython側で作った数字を応答に
   足しても検出できない——B103の別の迂回口)。
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OVERVIEW_PY = _REPO_ROOT / "src" / "jgkg" / "api" / "overview.py"
#: **cwd依存にしない(レビュー要検討13)。** `Path("queries/cq")`を
#: このファイル内で複数回書くと、実行時のcwdが変わったときに
#: `FileNotFoundError`で落ちる(大声で落ちるので実害は小さいが、
#: `_OVERVIEW_PY`と同じ`_REPO_ROOT`起点に揃える)。
_CQ_DIR = _REPO_ROOT / "queries" / "cq"

BASE = "https://jgkg.norr-tech.com"

# SPARQLのキーワードが`overview.py`の中に現れたら、手書きのクエリを
# 持ち始めた徴候である。
_SPARQL_MARKERS = ("SELECT ", "WHERE {", "PREFIX ", "GROUP BY", "CONSTRUCT ")


def _strip_docstrings(source: str) -> str:
    """モジュール/クラス/関数の**docstringだけ**を取り除く(構文木で判定する)。

    **訂正(レビュー要修正1)。** 前の版は正規表現で、三重引用符
    (トリプルクォート)で囲まれた文字列リテラルを丸ごと消していた——
    これはdocstringに限らず、三重引用符で書いた手書きSPARQLの定数文字列
    (代入文の右辺)も一緒に消してしまう(レビューが独立したスクリプトで
    実証: 単一引用符の1行手書きは検出できるが、複数行の三重引用符や
    トリプルクォートのf-stringで書いた手書きは検出0件になった)。

    ASTで「これはdocstringである」と判定できるノード
    (モジュール/クラス/関数の**先頭の文だけ**)だけを対象にする。
    定数文字列を代入する文はdocstringではないので消えず、
    `_SPARQL_MARKERS`の走査対象に残る。
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        _blank_span(lines, first.value)
    return "".join(lines)


def _blank_span(lines: list[str], node: ast.AST) -> None:
    """`node`(ASTの`Constant`)が占める範囲を、行の配列上で空白化する。"""
    start_line, start_col = node.lineno - 1, node.col_offset
    end_line, end_col = node.end_lineno - 1, node.end_col_offset
    if start_line == end_line:
        line = lines[start_line]
        lines[start_line] = line[:start_col] + line[end_col:]
        return
    first = lines[start_line]
    lines[start_line] = first[:start_col] + "\n"
    for i in range(start_line + 1, end_line):
        lines[i] = ""
    last = lines[end_line]
    lines[end_line] = last[end_col:]


def test_overview_module_contains_no_handwritten_sparql() -> None:
    """**`overview.py`に手書きのSPARQLが無い**こと(裁定B103/B60)。

    何があれば落ちるか: `overview.py`にモジュール/クラス/関数のdocstring
    **以外**の場所で`SELECT ... WHERE { ... }`を書き込むと落ちる
    (1行の文字列・三重引用符・f-stringのどれでも。`_strip_docstrings`が
    docstringだけを消すため)。

    **この検査は補助であり、主たる歯止めではない(レビュー指摘)。**
    テキストの字面を見る検査は、振る舞い(実際にclientへ届いた物)を見る
    検査より弱い——マーカー文字列を避けた書き方(変数名を分割して結合する
    等)は原理的に見逃せる。**主たる歯止めは
    `test_overview_reads_the_cq_files_and_sends_them_verbatim`の
    本数+内容の完全一致検査である。** この検査は「うっかり手書きした」
    ケースを早く・分かりやすいメッセージで捕まえるための早期警戒に過ぎない。
    """
    source = _OVERVIEW_PY.read_text(encoding="utf-8")
    code = _strip_docstrings(source)
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
    # Task 2b: CQ19(第4節「予算に対し記録を全部足すと合わない」の中心の主張)。
    "naive_sum_vs_entry_only": "cq19-naive-sum-vs-entry-only.rq",
    # Task 2b(追加): CQ20(第3節「事業ごとの完全一致率」。CQ16の誤読防止)。
    "request_exactly_granted": "cq20-request-exactly-granted.rq",
    # 裁定B111: 鮮度。**この対応表は独立に手で書く**(上のdocstringの理由)
    # ので、`OVERVIEW_QUERIES` からの転記ではなく「CQ10がKGのリリースの
    # 鮮度を答える」という事実から書いた ——
    # `queries/cq/cq10-release-freshness.rq` のヘッダがそう宣言している。
    "release_freshness": "cq10-release-freshness.rq",
}


def test_overview_reads_the_cq_files_and_sends_them_verbatim() -> None:
    """**CQファイルの中身がそのままclientに届く**こと。これが裁定B103の
    主たる歯止めである(上のテストは補助)。

    何があれば落ちるか:

    - `overview.py`がCQを読まずに自分で組み立てたクエリを送るようになると、
      届いた文字列が期待するCQの中身と一致せず落ちる
    - **`OVERVIEW_QUERIES`の7本に加えて8本目の(手書きの)クエリを送っても
      落ちる**(レビュー要修正1。本数を見るようにした——詳細は下記)

    **実測した事実その1(壊し確認2件目。ブリーフのSTEP2原案からの訂正)**:
    ブリーフ原案は`for name in overview.OVERVIEW_QUERIES.values()`で期待値を
    導いていたが、これは**モジュール自身の辞書を読み返すだけ**——
    `OVERVIEW_QUERIES`の1項目を別の(実在する)CQファイル名に向け違えても
    (例: `money_through_stages`をCQ13からCQ4に向け違える)、期待値の側も
    一緒にずれるため**検出できない**ことを実際に壊して確認した
    (task-2-report.md参照)。そのため対応表を`_EXPECTED_OVERVIEW_QUERIES`
    としてこのテストに独立して持たせ、まずそれと一致することを固定する。

    **実測した事実その2(レビュー要修正1)**: `expected in sent`という
    **包含**だけの検査は、期待する7本が全部含まれていれば8本目の手書き
    クエリが混ざっても素通りする(手書きSPARQL検査が三重引用符を素通りする
    穴と組み合わさると、B103を完全に迂回できることをレビューが実証した)。
    **`sorted(sent) == sorted(expected_contents)`という「届いた物の集合」
    での完全一致に変えた** ——本数のずれも内容のずれも同時に検出する。
    """
    sent: list[str] = []

    class SpyClient:
        def query(self, sparql: str):
            sent.append(sparql)
            return []

    from jgkg.api import overview

    overview.build_overview(SpyClient(), BASE, _CQ_DIR)
    assert sent, "1本もクエリが送られていない"
    assert overview.OVERVIEW_QUERIES == _EXPECTED_OVERVIEW_QUERIES, (
        f"OVERVIEW_QUERIES が期待するCQ番号との対応から外れている: {overview.OVERVIEW_QUERIES}"
    )

    expected_contents = [
        (_CQ_DIR / name).read_text(encoding="utf-8") for name in _EXPECTED_OVERVIEW_QUERIES.values()
    ]
    assert sorted(sent) == sorted(expected_contents), (
        f"clientに届いたクエリの集合が、期待する{len(expected_contents)}本と一致しない"
        f"(届いた本数: {len(sent)})。余分な(手書きの)クエリが混ざっているか、"
        "期待するCQの中身とずれている"
    )


def test_overview_response_fields_match_the_declared_cq_sources() -> None:
    """**`OverviewResponse`の全フィールドが、`OVERVIEW_QUERIES`のキーと
    一致する**こと(レビュー要検討7)。

    何があれば落ちるか: `OverviewResponse`にCQ経由でない項目(Python側で
    `len(...)`等から作った値)を足すと落ちる。この検査が無いと、そういう
    項目は`sources`にも現れないため画面から出所を辿れなくなる——
    裁定B103の迂回口を、モデルの側からも塞ぐ。
    """
    from jgkg.api.models import OverviewResponse
    from jgkg.api.overview import OVERVIEW_QUERIES

    non_cq_fields = {"computed_at", "sources"}
    field_names = {n for n in OverviewResponse.model_fields if n not in non_cq_fields}
    assert field_names == set(OVERVIEW_QUERIES), (
        f"OverviewResponse のフィールドと OVERVIEW_QUERIES のキーが一致しない: "
        f"fields={field_names} keys={set(OVERVIEW_QUERIES)}"
    )


# =============================================================================
# `_bool`の単体テスト(レビュー要修正3・4)
# =============================================================================


def test_bool_accepts_the_lexical_forms_xsd_boolean_actually_allows() -> None:
    """**`_bool`が`xsd:boolean`の正当な字句形をすべて受理する**こと。

    **訂正(レビュー要修正3・4)。** 前の版はfixtureに対する
    `{stage.paid_by_government for stage in ...} <= {True, False}`という
    アサートで「詰め替えを検査している」と主張していたが、これは
    **`bool`型である以上どんな集合に対しても真になり、原理的に落ちない**
    (レビューで指摘・実証)。ここでは`_bool`をfixtureの分布に依存せず
    直接呼び、`Term`の字句形ごとに正しい値を返すこと・解釈できない値は
    例外にすることを固定する。
    """
    from jgkg.api.kgclient import Term
    from jgkg.api.overview import _bool

    for value in ("true", "1"):
        assert _bool({"paid": Term(value=value, kind="literal")}, "paid") is True, value
    for value in ("false", "0"):
        assert _bool({"paid": Term(value=value, kind="literal")}, "paid") is False, value


def test_bool_raises_on_unbound_or_unrecognized_values() -> None:
    """**`_bool`は未束縛も、解釈できない字句形も、`False`ではなく例外にする**

    (レビュー要修正4)。`"TRUE"`(大文字)・`"yes"`のような、`xsd:boolean`の
    正当な字句形ではない値を黙って`False`にすると、CQ13の
    「入口/通過金の区別」が実データに反して狂う——欠損を既定値に落として
    静かに間違える、このプロジェクトの再発欠陥の同型である。
    """
    from jgkg.api.kgclient import Term
    from jgkg.api.overview import _bool

    try:
        _bool({"paid": None}, "paid")
    except ValueError:
        pass
    else:
        raise AssertionError("未束縛なのに例外にならなかった")

    for bad_value in ("TRUE", "yes", "unknown"):
        try:
            _bool({"paid": Term(value=bad_value, kind="literal")}, "paid")
        except ValueError:
            continue
        raise AssertionError(f"解釈できない値なのに例外にならなかった: {bad_value!r}")


# =============================================================================
# fixtureの実データに対する結合テスト(spyテストが見ない層を埋める)
# =============================================================================


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
    result = build_overview(client, BASE, _CQ_DIR)

    assert result.sources == OVERVIEW_QUERIES
    assert result.ministries, "CQ15: 府省の予算行が1件も無い"
    assert result.budget_and_execution, "CQ14: 予算年度の内訳行が1件も無い"
    assert result.request_and_initial, "CQ16: 要求額/当初予算の行が1件も無い"
    assert result.recipient_identification, "CQ17: 照合区分の行が1件も無い"
    assert result.type_counts, "CQ18: 型別件数の行が1件も無い"
    assert result.government_paid, "CQ12: 国が自ら支払った額の行が1件も無い"
    assert result.money_through_stages, "CQ13: 通過金の段の行が1件も無い"
    assert result.release_freshness, "CQ10: 鮮度の行が1件も無い"

    # **鮮度の各行が「いつ時点か」と「それが記録日か取得日か」を両方言うこと**
    # (裁定B111)。どちらの意味かを混ぜると、全件レビューのように「記録した日」
    # しか分からないソースと、APIから「取得した日」が分かるソースが同じ列に
    # 並んで読めなくなる。
    for fresh in result.release_freshness:
        assert fresh.source_name, fresh
        assert fresh.as_of, fresh
        assert fresh.date_kind in {"記録日", "取得日"}, fresh.date_kind
    # **ソース名の一意性は主張しない。** 一度そう書いてfixtureで緑になったが、
    # **本番の実データでは重複していた**(2026-09-13実測: 6行のうち
    # 「国税庁 法人番号公表サイト 全件データ」が同じ日付で2行)。CQ10は
    # 名前付きグラフ1つにつき1行を返すので、1つのソースが複数のグラフに
    # 分かれていれば同じ名前が並ぶ ——それがこのクエリの正しい答えである。
    # 畳むのは表示側の判断(`provenance.ts` の `sourceLines` が同じことを
    # している前例がある)。
    # **fixtureだけで確かめた不変条件は、実データで崩れる**(統制9)。

    # **CQ13の`project_id_path`が実際に開けること**(裁定B110)。
    # 「導出したパスがエンティティ詳細で引けない」はこのプロジェクトが
    # 2度踏んだ型(裁定B59・B69)なので、`id_path`を足したら必ず
    # **そのパスで引いてみる**。文字列の形を確かめるだけでは足りない。
    from jgkg.api.queries import get_entity_detail

    for stage in result.money_through_stages:
        detail = get_entity_detail(client, BASE, stage.project_id_path, limit=1)
        assert detail is not None, f"CQ13のproject_id_pathが引けない: {stage.project_id_path}"
        assert detail.id == stage.project_id
        assert detail.label == stage.project_name, "CQ13の事業名と詳細の表示名が食い違う"
    assert result.naive_sum_vs_entry_only, "CQ19: 素朴な合計/入口だけの合計の行が1件も無い"
    assert result.request_exactly_granted, "CQ20: 要求額の完全一致の行が1件も無い"

    # **`(sheet_year, budget_fiscal_year)`の組が一意であること**(裁定D-14)。
    # CQ14は将来2枚目のレビューシートが増えると同じ`budget_fiscal_year`に
    # 2行を返しうる——`BudgetAndExecution`が`sheet_year`を持つのはその2行を
    # 区別できるようにするためなので、現状(シートは1種類だけ)でも組として
    # 重複が無いことを固定しておく。
    pairs = [(row.sheet_year, row.budget_fiscal_year) for row in result.budget_and_execution]
    assert len(pairs) == len(set(pairs)), (
        f"(sheet_year, budget_fiscal_year) の組が重複している: {pairs}"
    )
