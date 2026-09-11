# トップページ第1層「全体を見る」実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一般利用者がトップページを開いた時点で「日本政府の予算と支出の全体像」が数字で見え、そこから既存のエンティティ/グラフビューへ辿れるようにする。

**Architecture:** 第1層の数字は**すべて`queries/cq/*.rq`の答え**である(裁定B103)。APIは起動時に1回それらを実行して結果をメモリに持ち、`GET /overview`で配る。リクエストごとに集約しない。第2層は既存のSigma.jsグラフビュー(`frontend/src/views/graph.ts`)をそのまま使い、作り直さない。

**Tech Stack:** FastAPI + pydantic / SPARQL(Jena TDB2・rdflib) / TypeScript + Vite(素のDOM。チャートライブラリを入れない)

**Spec:** `docs/superpowers/specs/2026-08-22-japan-government-kg-design.md`(原則1)、`docs/decision-log.md`の**裁定B103**(この計画の設計判断)、レビュー済みモック `docs/mockups/top-page.html`

---

## Global Constraints

このプロジェクト固有の規律。**各タスクの要求はこの節を暗黙に含む。**

- **原則1: 本体はKGとオントロジー、アプリは検証装置。投資の中心をUIに置かない。**
  第2層を作り直さない。チャートライブラリ・UIフレームワークを追加しない。棒グラフは素のSVG/CSSで書く。
- **裁定B103: 第1層に出す数字は`queries/cq/*.rq`の答えでなければならない。**
  `overview.py`に手書きのSPARQLを置かない。画面用の別集計経路を作らない。
  新しい数字を出したければ**CQを足す**。
- **裁定B60の規律(warmup.pyが確立): 手書きSPARQLの代わりに実際のコード経路を呼び、それをspyテストで固定する。**
  `tests/test_api_warmup.py`が既にこの形なので、同じやり方に倣う。
- **裁定B102: 実行時に読むファイルはAPIイメージにCOPYされていなければならない。**
  `tests/test_api_image_contents.py`を拡張して守る。コンテナを起動せず静的に検査する。
- **表示名の出所は2つある。混同しない(Task 1の実測で判明。計画の当初の記述は誤りだった)。**
  - **語彙**(クラス・プロパティ・列挙型の許容値)の表示名 = **`dcterms:title @ja`**。
    裁定B78(`/def/`配下68項目)と裁定B88(列挙値8件)が言っているのはこちらである
  - **インスタンス**(府省・法人・法令・事業)の表示名 = **`skos:prefLabel`**。
    実測: `?m a org:Ministry` は `skos:prefLabel` を40件持ち、
    **`dcterms:title` は1件も持たない**。`warmup.py`も検索が
    `skos:prefLabel`を読むと書いている
  - **当初この節は「`dcterms:title @ja`が表示名の唯一の出所」と書いていた。
    これはB78/B88の射程を「すべての表示名」に一般化した誤りである。**
  - どちらの場合も**フロントで表示名を合成しない**(この部分は正しい)
- **生成物はコミットする。** API変更後に `bash scripts/generate-frontend-types.sh` を実行し、
  `frontend/openapi.json` と `frontend/src/api/openapi-types.ts` を一緒にコミットする。
- **CIと同じコマンドでlintする: `uv run ruff check src tests scripts`。**
  `ruff check .` の結果を読み飛ばしてはならない(2026-09-11に実際にそれで落ちた)。
- **テストは必ず一度わざと壊して落ちることを示し、失敗出力を報告に貼る。**
  壊し確認の前にコミットするか退避を取る(`git checkout`で未コミットの修正を消した実例がある)。
- **`tests/phase1_fixture.py`を手で呼ぶときは`JGKG_LAKE_DIR`を設定する。**
  設定せずに呼ぶと実レイクに書きに行く(不変ガードが止めるが、頼ってはいけない)。
- **`amount_jpy`は`core:`名前空間である**(`budget:`ではない)。実測で確認済み。
- **rdflibのfixtureは`Dataset(default_union=True)`なので、CQは`GRAPH`句なしで書く**
  (既存CQ1〜CQ14と同じ形。Jena側は`tdb2:unionDefaultGraph true`)。
- **スキーマ(`schema/*.yaml`)は変更しない。** この計画はオントロジーを変えない
  (変えるなら生成物をLinuxで作り直す必要がある。裁定B100)。

---

## File Structure

| ファイル | 責務 |
|---|---|
| `queries/cq/cq15-ministry-budget-ranking.rq` | 新規。全府省を予算額順に並べる |
| `queries/cq/cq16-request-vs-initial-budget.rq` | 新規。要求額と当初予算の乖離 |
| `queries/cq/cq17-recipient-identification.rq` | 新規。支払先の特定状況(照合区分ごと) |
| `queries/cq/cq18-kg-scale.rq` | 新規。型ごとの件数 |
| `schema/competency-questions.md` | CQ15〜18の問いと、fixtureでの期待値を追記 |
| `tests/test_competency_questions_phase1.py` | CQ15〜18のテスト |
| `src/jgkg/api/overview.py` | 新規。CQファイルを読んで実行し、結果を型に詰める。**手書きSPARQLを持たない** |
| `src/jgkg/api/models.py` | `OverviewResponse`とその要素を追加 |
| `src/jgkg/api/app.py` | `lifespan`で`build_overview`を呼び、`app.state`に持つ。`GET /overview` |
| `docker/api.Dockerfile` | `COPY queries ./queries` |
| `tests/test_api_image_contents.py` | 実行時に読むディレクトリ全部を見る形に拡張 |
| `tests/test_api_overview.py` | 新規。`/overview`の内容と、CQ経由であることのspy検査 |
| `frontend/src/api/client.ts` | `fetchOverview()` |
| `frontend/src/views/overview.ts` | 新規。第1層の描画 |
| ~~`frontend/src/views/overview.test.ts`~~ | **作らない**(vitestにDOM環境が無い)。純関数を`format.test.ts`等でテストし、ビューは実ブラウザで確認する |
| `frontend/src/router.ts` | `#/`(search)に第1層を載せる |

---

## Task 1: CQ15〜CQ18 を足す

**Files:**
- Create: `queries/cq/cq15-ministry-budget-ranking.rq`
- Create: `queries/cq/cq16-request-vs-initial-budget.rq`
- Create: `queries/cq/cq17-recipient-identification.rq`
- Create: `queries/cq/cq18-kg-scale.rq`
- Modify: `schema/competency-questions.md`
- Modify: `tests/test_competency_questions_phase1.py`

**Interfaces:**
- Produces: 4つの`.rq`ファイル名と、各クエリの**列名**。後続タスクがこの列名で結果を読む。
  - CQ15: `?ministry ?name ?y ?totalBudget ?projectCount`
  - CQ16: `?y ?requested ?initial ?recordCount`
  - CQ17: `?category ?totalAmount ?expenditureCount`
  - CQ18: `?type ?instanceCount`
- `scripts/run_cq.py`の既定パターンは`cq*.rq`なので、**ゲートには自動で入る**(追加作業は無い)。

- [ ] **Step 1: CQ15 を書く**

`queries/cq/cq15-ministry-budget-ranking.rq`:

```sparql
# CQ15: 全府省を予算額順に並べるとどうなるか。年度ごとに(裁定B103)
#
# **CQ2との違い。** CQ2は `<.../id/org/6000012070001>`(厚生労働省)に固定した
# 例示であり「この府省は」という問いに答える。CQ15は「**全府省を並べると**」
# という別の問いで、トップページ第1層が最初に見せる図の出所になる。
#
# **表示名は`dcterms:title`から取る(裁定B78/B88: 表示名の唯一の出所)。**
# `OPTIONAL`にしてあるのは、表示名の無い府省があってもその行を落とさない
# ためである——落とすと合計が静かに減る(その府省の予算が消える)。
#
# **`?y`でもGROUP BYする。** `budget:fiscalYear`はレビューシートの年度であり、
# 実データでは5,794事業すべてが2025だが(裁定B99)、年度を固定で書き込むと
# 来年のデータで黙って壊れる。
PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
PREFIX dcterms: <http://purl.org/dc/terms/>
SELECT ?ministry ?name ?y (SUM(?a) AS ?totalBudget) (COUNT(DISTINCT ?p) AS ?projectCount)
WHERE {
  ?p budget:ministry ?ministry ;
     budget:fiscalYear ?y ;
     budget:budgetAmount ?a .
  OPTIONAL { ?ministry dcterms:title ?name }
}
GROUP BY ?ministry ?name ?y
ORDER BY DESC(?totalBudget)
```

- [ ] **Step 2: CQ16 を書く**

`queries/cq/cq16-request-vs-initial-budget.rq`:

```sparql
# CQ16: 要求した額と、実際に付いた当初予算はどれだけ違うか。年度ごとに(裁定B103)
#
# **年度のずれに注意。** `budget:nextYearRequest`は「その年度の記録が持つ
# **翌年度の**要求額」である。したがって年度Yの`nextYearRequest`と
# 対応するのは**年度Y+1の`initialBudget`**であり、同じ行の`initialBudget`
# ではない。実データでは96.9〜99.4%で対応する(裁定B99の実測)。
# **このクエリは両方を同じ行に並べて返すだけで、対応付けはしない**
# ——ずらす判断を表示側に委ねる。ここで勝手にずらすと、
# 「この行の2つの数字は何なのか」が読めなくなる。
#
# **controllerは一度この列を「集計行すべてで空」と誤記録した**(裁定B99の訂正)。
# 実際は23,036件すべて非空で、`'45013000.0'`のような小数表記だった。
PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
SELECT ?y (SUM(?req) AS ?requested) (SUM(?init) AS ?initial) (COUNT(?a) AS ?recordCount)
WHERE {
  ?a budget:budgetFiscalYear ?y ;
     budget:nextYearRequest ?req ;
     budget:initialBudget ?init .
}
GROUP BY ?y
ORDER BY ?y
```

- [ ] **Step 3: CQ17 を書く**

`queries/cq/cq17-recipient-identification.rq`:

```sparql
# CQ17: 支払先はどこまで特定できているか。照合区分ごとの金額と件数(裁定B103)
#
# **`amount_jpy`は`core:`名前空間である**(`budget:`ではない。実測で確認)。
# 間違えると0件が返り、しかもエラーにならない——「支払先の特定は0件」と
# いう嘘の答えが画面に出る。
#
# 区分の意味は`schema/budget.yaml`の`RecipientMatchCategory`を参照。
# **表示名は列挙値に付いた`dcterms:title @ja`から取る**(裁定B88)ので、
# ここでは区分のIRIをそのまま返す——表示名の解決は呼び出し側の仕事。
PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
PREFIX core: <https://jgkg.norr-tech.com/def/core#>
SELECT ?category (SUM(?amount) AS ?totalAmount) (COUNT(?e) AS ?expenditureCount)
WHERE {
  ?e budget:recipientMatchCategory ?category ;
     core:amount_jpy ?amount .
}
GROUP BY ?category
ORDER BY DESC(?totalAmount)
```

- [ ] **Step 4: CQ18 を書く**

`queries/cq/cq18-kg-scale.rq`:

```sparql
# CQ18: このKGには何が何件入っているか。型ごとに(裁定B103)
#
# **`GRAPH`句を使わない。** rdflibのfixtureは`Dataset(default_union=True)`、
# Jena側は`tdb2:unionDefaultGraph true`なので、既存CQ1〜CQ14と同じく
# 素のパターンで名前付きグラフ全体を見る。
#
# **`?type`を絞らない。** 「6軸のうちどれ」のような絞りを入れると、
# 型が増えたときに黙って落ちる。全部返して、表示側が並べ方を決める。
PREFIX core: <https://jgkg.norr-tech.com/def/core#>
SELECT ?type (COUNT(?s) AS ?instanceCount)
WHERE {
  ?s a ?type .
}
GROUP BY ?type
ORDER BY DESC(?instanceCount)
```

- [ ] **Step 5: fixtureに対して実際の答えを測る(手で書かない)**

Run:
```bash
uv run python -c "
import sys; sys.path.insert(0,'tests')
import os, tempfile, json
from pathlib import Path
with tempfile.TemporaryDirectory() as d:
    os.environ['JGKG_BASE_URI'] = 'https://jgkg.norr-tech.com'
    os.environ['JGKG_LAKE_DIR'] = str(Path(d)/'lake')
    os.environ['JGKG_QUARANTINE_DIR'] = str(Path(d)/'quarantine')
    from jgkg.config import get_settings; get_settings.cache_clear()
    import phase1_fixture as fx
    ds = fx.build_dataset(Path(d)/'out')
    for n in ('cq15-ministry-budget-ranking','cq16-request-vs-initial-budget',
              'cq17-recipient-identification','cq18-kg-scale'):
        rows = list(ds.query(Path(f'queries/cq/{n}.rq').read_text(encoding='utf-8')))
        print(n, len(rows), '行')
        for r in rows[:8]:
            print('   ', [x.toPython() if x is not None else None for x in r])
"
```

**`JGKG_LAKE_DIR`を必ず設定する**(Global Constraints参照)。
出力された値を次のステップの期待値に使う。**目で見た値を手で打ち直さない
——出力をコピーする。**

- [ ] **Step 6: テストを書く(まず落ちることを確認する)**

`tests/test_competency_questions_phase1.py` の末尾に足す。
`<Step 5の実測値>`はStep 5の出力で置き換える。

```python
# =============================================================================
# CQ15〜CQ18: トップページ第1層が出す数字の出所(裁定B103)
# =============================================================================


def test_cq15_ranks_every_ministry_not_just_one(kg):
    """**全府省**が返り、予算額の降順であること。CQ2は1府省に固定されている。

    何があれば落ちるか:
    - `budget:ministry <...6000012070001>` のように府省を固定に戻すと1行になる
    - `OPTIONAL { ?ministry dcterms:title ?name }` を必須にすると、
      表示名の無い府省の行が消えて合計が減る
    """
    rows = _query(kg, "cq15-ministry-budget-ranking.rq")
    assert rows, "CQ15に答えられない"
    budgets = [int(r[3]) for r in rows]
    assert budgets == sorted(budgets, reverse=True), f"降順でない: {budgets}"
    ministries = {str(r[0]) for r in rows}
    assert len(ministries) >= 2, f"府省が1つしか返っていない(CQ2と同じになっている): {ministries}"


def test_cq16_returns_request_and_initial_side_by_side(kg):
    """要求額と当初予算が**同じ行に別の列として**返ること。

    何があれば落ちるか: クエリ側で年度をずらす(Y の要求と Y+1 の当初を
    同じ行に置く)実装にすると、この行の2つの数字が何なのか読めなくなる
    ——対応付けは表示側の仕事である(クエリのヘッダ参照)。
    """
    rows = _query(kg, "cq16-request-vs-initial-budget.rq")
    assert rows, "CQ16に答えられない"
    by_year = {int(r[0]): (int(r[1]), int(r[2]), int(r[3])) for r in rows}
    assert sorted(by_year) == [2024, 2025], by_year
    # fixtureは「2024年度に100を要求し、2025年度に当初100が付いた」形
    assert by_year[2024][0] == 100_000_000, by_year
    assert by_year[2025][1] == 100_000_000, by_year
    assert by_year[2025][0] != by_year[2025][1], (
        f"要求額と当初予算が同じ値になっている(同じ列を2回読んでいる疑い): {by_year[2025]}"
    )


def test_cq17_sums_amounts_from_the_core_namespace(kg):
    """照合区分ごとの金額が返ること。**`core:amount_jpy`を読んでいる**こと。

    何があれば落ちるか: `budget:amount_jpy`(存在しない)に書き換えると
    **エラーにならず0件**になる。そのとき「支払先の特定は0件」という
    嘘が画面に出る——だから件数が非0であることを固定する。
    """
    rows = _query(kg, "cq17-recipient-identification.rq")
    assert rows, "CQ17に答えられない(述語の名前空間を間違えている疑い)"
    total = sum(int(r[1]) for r in rows)
    count = sum(int(r[2]) for r in rows)
    assert total > 0, f"金額の合計が0(core:amount_jpyを読めていない): {rows}"
    assert count == 4, f"fixtureの支出は4件のはず: {count}"
    categories = {str(r[0]).rsplit("/", 1)[-1].rsplit("#", 1)[-1] for r in rows}
    assert len(categories) == 4, f"4区分すべてが出るはず(CQ6と同じ内訳): {categories}"


def test_cq18_counts_instances_across_named_graphs(kg):
    """型ごとの件数が、**名前付きグラフをまたいで**数えられること。

    何があれば落ちるか: `GRAPH ?g { ... }` を付けると rdflib の
    `default_union=True` では二重に数える形になりうる。逆に
    データを既定グラフだけに探しに行く形にすると0件になる。
    ここでは「主要な型が全部出る」ことで、どちらの壊れ方も捕まえる。
    """
    rows = _query(kg, "cq18-kg-scale.rq")
    assert rows, "CQ18に答えられない"
    counts = {str(r[0]).rsplit("#", 1)[-1]: int(r[1]) for r in rows}
    for expected in ("BudgetProject", "Expenditure", "Law", "Ministry", "AnnualBudget"):
        assert counts.get(expected, 0) > 0, f"{expected} が0件: {counts}"
```

- [ ] **Step 7: わざと壊して落ちることを確認する**

```bash
# 1) CQ15を1府省固定に戻す → test_cq15 が落ちる
# 2) CQ17の core:amount_jpy を budget:amount_jpy にする → test_cq17 が落ちる
# 3) それぞれ元に戻して緑を確認する
uv run pytest tests/test_competency_questions_phase1.py -k "cq15 or cq16 or cq17 or cq18" -v
```

**失敗出力を報告に貼る。** 壊す前にコミットするか退避を取る。

- [ ] **Step 8: `schema/competency-questions.md` に CQ15〜18 を追記**

既存のCQ節と同じ形で、**問い・なぜこの問いが要るか・fixtureでの期待値**を書く。
末尾の期待値テーブルに4行足す(値はStep 5の実測)。
**裁定B103を引く**(この4本がトップページ第1層の出所であること)。

- [ ] **Step 9: ゲートを回して commit**

```bash
uv run ruff check src tests scripts
uv run pytest tests/test_competency_questions_phase1.py -q
git add queries/cq/cq1[5-8]*.rq schema/competency-questions.md tests/test_competency_questions_phase1.py
git commit -m "feat(cq): 第1層が出す数字の出所としてCQ15〜18を足す(裁定B103)"
```

---

## Task 2: `GET /overview` を足す(起動時に1回計算する)

**Files:**
- Create: `src/jgkg/api/overview.py`
- Create: `tests/test_api_overview.py`
- Modify: `src/jgkg/api/models.py`
- Modify: `src/jgkg/api/app.py`
- Modify: `docker/api.Dockerfile`
- Modify: `tests/test_api_image_contents.py`

**Interfaces:**
- Consumes: Task 1の4ファイル名と列名。`KGClient.query(sparql) -> list[Row]`(`src/jgkg/api/kgclient.py`)。`Term.is_resource()`と`Row`の形はそこを読むこと。
- Produces:
  - `overview.build_overview(client: KGClient, base_uri: str, queries_dir: Path) -> OverviewResponse`
  - `models.OverviewResponse`(下記)
  - `GET /overview` が `OverviewResponse` を返す
  - `app.state.overview: OverviewResponse | None`

- [ ] **Step 1: モデルを書く**

`src/jgkg/api/models.py` の末尾に足す(既存の`_Envelope`を継承する)。

```python
class MinistryBudget(_Envelope):
    """CQ15の1行。府省1つの、ある年度の予算額と事業数。"""

    id: str
    id_path: str
    #: 表示名(`dcterms:title @ja`)。**無いことがある** ——
    #: CQ15が`OPTIONAL`で取るため。フロントで合成しない(裁定B78/B88)。
    label: str | None
    fiscal_year: int
    total_budget: int
    project_count: int


class BudgetAndExecution(_Envelope):
    """CQ14の1行。ある予算年度の内訳と執行。"""

    budget_fiscal_year: int
    initial_budget: int
    supplementary_budget: int
    carried_over_from_previous_year: int
    reserve_fund: int
    total_budget_available: int
    executed_amount: int
    project_count: int


class RequestAndInitial(_Envelope):
    """CQ16の1行。**年度のずれは解消していない** ——
    年度Yの`requested`に対応するのは年度Y+1の`initial`である
    (CQ16のヘッダ参照)。対応付けは表示側で行う。"""

    budget_fiscal_year: int
    requested: int
    initial: int
    record_count: int


class RecipientIdentification(_Envelope):
    """CQ17の1行。照合区分ごとの金額と件数。

    **`label`を持たない。表示名はAPIからは出せない。**
    `?category`は型なしの文字列リテラル(`resolved`等)であり、その日本語の
    表示名(裁定B88の`dcterms:title @ja`)は**トリプルストアに入っていない**
    ——`schema/generated/*.owl.ttl`はAPIイメージの`/chat`用の静的ファイルで、
    名前付きグラフはソース別のデータグラフだけである。SPARQLで
    `?category dcterms:title ?label`を引くと**0件**になる
    (`queries/cq/cq17-recipient-identification.rq`のヘッダに実測と理由がある)。

    表示名はフロントエンドが`labels.ts`の
    `enumValueLabel("recipientMatchCategory", category)`で引く
    ——ビルド時に書き出した`labels.json`の`enumValues`が出所である。
    """

    category: str
    total_amount: int
    expenditure_count: int


class TypeCount(_Envelope):
    """CQ18の1行。

    **`label`を持たない**(`RecipientIdentification`と同じ理由)。
    型の表示名はフロントエンドが`labels.ts`の`typeLabel(localName)`で引く
    (`labels.json`の`types`。18件)。

    `type`は完全IRIで返す。ローカル名(`#`の後ろ)への切り出しは
    **表示側で行う** ——`labels.ts`のキーがローカル名だからである。
    """

    type: str
    instance_count: int


class OverviewResponse(_Envelope):
    """トップページ第1層が必要とするものすべて(裁定B103)。

    **この応答の数字はすべて`queries/cq/*.rq`の答えである。**
    画面用の別集計は存在しない——`overview.py`に手書きのSPARQLは無い。

    `computed_at`は**このプロセスが起動時に計算した時刻**であり、
    KGの鮮度ではない。KGの鮮度はCQ10(`release_freshness`)が答える。
    """

    computed_at: str
    #: 各項目がどのCQから来たかの対応。**画面に出す**ため
    #: (原則1: アプリは検証装置。利用者が出所のCQを辿れる)
    sources: dict[str, str]
    ministries: list[MinistryBudget]
    budget_and_execution: list[BudgetAndExecution]
    request_and_initial: list[RequestAndInitial]
    recipient_identification: list[RecipientIdentification]
    type_counts: list[TypeCount]
    government_paid: list[GovernmentPaidTotal]
    money_through_stages: list[MoneyThroughStage]
```

CQ12とCQ13の分も書く。**列名は実物の`SELECT`から取った**:

```python
class GovernmentPaidTotal(_Envelope):
    """CQ12の1行。**これは下限であり、両方向に誤差がある** ——
    `queries/cq/cq12-government-paid-total.rq`のヘッダに理由と上限
    (63,863,635,000円=0.050%)がある。画面に「正確な総額」と書いてはいけない。"""

    fiscal_year: int
    government_paid: int
    item_count: int


class MoneyThroughStage(_Envelope):
    """CQ13の1行。同じ金額が複数の段に現れる事業。足すと二重計上になる。"""

    project_name: str
    block_id: str
    block_name: str | None
    paid_by_government: bool
    amount: int
    source_id: str | None
    source_name: str | None
```

**CQの列名との対応(実物から写した。推測ではない)**:

| CQ | SELECTの変数 |
|---|---|
| CQ12 | `?y ?governmentPaid ?itemCount` |
| CQ13 | `?projectName ?blockId ?blockName ?paidByGovernment ?amount ?sourceId ?sourceName` |
| CQ14 | `?sheetYear ?budgetYear ?initialBudget ?supplementaryBudget ?carriedOverFromPreviousYear ?reserveFund ?totalBudgetAvailable ?executedAmount ?projectCount` |
| CQ15 | `?ministry ?name ?y ?totalBudget ?projectCount` |
| CQ16 | `?y ?requested ?initial ?recordCount` |
| CQ17 | `?category ?totalAmount ?expenditureCount` |
| CQ18 | `?type ?instanceCount` |

**`Row = dict[str, Term | None]`なので変数名で引ける**
(`src/jgkg/api/kgclient.py:50`)。列の位置に依存しないこと。

- [ ] **Step 2: 「手書きSPARQLを置かない」ことを固定するテストを先に書く**

`tests/test_api_overview.py`:

```python
"""`/overview`の検査。

**このモジュールの中心は「数字の出所がCQファイルであること」の固定である**
(裁定B103)。`overview.py`に手書きのSPARQLを書き始めたら落ちる形にしてある
——`warmup.py`が裁定B60で確立した規律と、`tests/test_api_warmup.py`が
それをspyで固定しているやり方に倣う。
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
    code = re.sub(r'""".*?"""', "", source, flags=re.S)
    code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("#"))
    found = [m for m in _SPARQL_MARKERS if m in code]
    assert not found, (
        f"overview.py が手書きのSPARQLを持っている: {found}。"
        "数字の出所は queries/cq/*.rq でなければならない(裁定B103)"
    )
```

さらに**spyテスト**を書く:

```python
def test_overview_reads_the_cq_files_and_sends_them_verbatim(tmp_path) -> None:
    """**CQファイルの中身がそのままclientに届く**こと。

    何があれば落ちるか: `overview.py`がCQを読まずに自分で組み立てた
    クエリを送るようになると、届いた文字列がファイルの中身と一致せず落ちる。
    """
    sent: list[str] = []

    class SpyClient:
        def query(self, sparql: str):
            sent.append(sparql)
            return []

    from jgkg.api import overview

    overview.build_overview(SpyClient(), "https://jgkg.norr-tech.com", Path("queries/cq"))
    assert sent, "1本もクエリが送られていない"
    for name in overview.OVERVIEW_QUERIES.values():
        expected = (Path("queries/cq") / name).read_text(encoding="utf-8")
        assert expected in sent, f"{name} の中身がそのまま送られていない"
```

Run: `uv run pytest tests/test_api_overview.py -v`
Expected: FAIL(`overview.py`がまだ無い)

- [ ] **Step 3: `overview.py` を書く**

**設計の要点**: CQ名 → 応答の項目の対応を**モジュール定数**に持ち、
それをループで回す。**述語や年度をここに書かない。**

```python
"""トップページ第1層のための集約(裁定B103)。

**このモジュールは手書きのSPARQLを持たない。** `queries/cq/*.rq`を読んで
`KGClient.query`に**そのまま**渡し、返ってきた行を型に詰めるだけである。

**なぜそうするか。** 画面に出す数字を別途集計すると、KGとは別の真実が
1つ増える。設計書の原則1「本体はオントロジーとKG、アプリは検証装置」に
照らすと、**トップページはCQの答えを表示する装置**であるのが正しい
——第1層に新しい数字を出したければCQを足すことになる。

これは`warmup.py`が裁定B60で確立した規律と同じである
(「手書きのSPARQLをここに置かない。実際のコード経路を呼ぶ」)。
`tests/test_api_overview.py`が2つの検査でこれを固定している。

**起動時に1回だけ計算する。** 実測(裁定B103)では全体で
コールド3.999秒・ウォーム3.114秒かかる。第1層は全訪問者が最初に開く
画面なので、リクエストごとに払える代償ではない。また
`minReplicas=1`/`maxReplicas=1`でFusekiとAPIが同じレプリカを共有して
おり、Fuseki側にクエリのタイムアウトがまだ無い(既知の未処理事項)。
"""
```

モジュールの骨格(**これをそのまま書く**):

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jgkg.api.kgclient import KGClient, Row, Term
from jgkg.api.models import (
    BudgetAndExecution,
    GovernmentPaidTotal,
    MinistryBudget,
    MoneyThroughStage,
    OverviewResponse,
    RecipientIdentification,
    RequestAndInitial,
    TypeCount,
)

#: 応答の項目 → CQファイル名。**ここが数字の出所の一覧である。**
#: 項目を足したければCQを足す(裁定B103)。
OVERVIEW_QUERIES: dict[str, str] = {
    "ministries": "cq15-ministry-budget-ranking.rq",
    "budget_and_execution": "cq14-budget-and-execution-by-year.rq",
    "request_and_initial": "cq16-request-vs-initial-budget.rq",
    "recipient_identification": "cq17-recipient-identification.rq",
    "type_counts": "cq18-kg-scale.rq",
    "government_paid": "cq12-government-paid-total.rq",
    "money_through_stages": "cq13-money-passing-through-stages.rq",
}


def _int(row: Row, name: str) -> int:
    """束縛を整数で読む。**未束縛は0ではなく例外にする** ——
    集約の列が欠けているのは実装の誤りであり、0として通すと
    「予算0円」が画面に出る(このプロジェクトの再発欠陥: 欠損を
    既定値に落として静かに間違える)。"""
    term = row.get(name)
    if term is None:
        raise ValueError(f"{name} が束縛されていない: {sorted(row)}")
    return int(float(term.value))


def _text(row: Row, name: str) -> str | None:
    term = row.get(name)
    return term.value if term is not None else None


#: **`queries.py`の`_id_path`を使う**(`src/jgkg/api/queries.py:171`)。
#: 引数の順は **`(base_uri, iri)`** である——逆にすると黙って壊れた経路形が出る。
#: 手で文字列を切ってはいけない: 裁定B59が「箇所ごとに違う剥がし処理を
#: 書く」ことを禁じており、その関数1本だけを全ての構築箇所から呼ぶ設計である。
from jgkg.api.queries import _id_path
```

**`_id_path`は`queries.py`のプライベート関数である。**
モジュール外から`_`付きを読むのが気になるなら、`queries.py`側で
公開名に改名して既存の3箇所も直すこと(**複製は作らない**)。
どちらを選んだかを報告に書く。

各パーサは**変数名で読む**(位置に依存しない)。例:

```python
def _parse_ministries(rows: list[Row], base_uri: str) -> list[MinistryBudget]:
    out: list[MinistryBudget] = []
    for row in rows:
        iri = _text(row, "ministry")
        if iri is None:
            continue  # 府省が未束縛の行は集約の対象外(OPTIONALの相手ではない)
        out.append(
            MinistryBudget(
                id=iri,
                id_path=_id_path(base_uri, iri),  # 引数の順に注意
                label=_text(row, "name"),
                fiscal_year=_int(row, "y"),
                total_budget=_int(row, "totalBudget"),
                project_count=_int(row, "projectCount"),
            )
        )
    return out
```

`build_overview`は`OVERVIEW_QUERIES`を回して、各パーサに渡す:

```python
def build_overview(
    client: KGClient, base_uri: str, queries_dir: Path
) -> OverviewResponse:
    raw: dict[str, list[Row]] = {}
    for key, filename in OVERVIEW_QUERIES.items():
        sparql = (queries_dir / filename).read_text(encoding="utf-8")
        raw[key] = client.query(sparql)
    return OverviewResponse(
        computed_at=datetime.now(UTC).isoformat(),
        sources={key: filename for key, filename in OVERVIEW_QUERIES.items()},
        ministries=_parse_ministries(raw["ministries"], base_uri),
        budget_and_execution=_parse_budget_and_execution(raw["budget_and_execution"]),
        request_and_initial=_parse_request_and_initial(raw["request_and_initial"]),
        recipient_identification=_parse_recipient_identification(
            raw["recipient_identification"], base_uri
        ),
        type_counts=_parse_type_counts(raw["type_counts"]),
        government_paid=_parse_government_paid(raw["government_paid"]),
        money_through_stages=_parse_money_through_stages(raw["money_through_stages"]),
    )
```

**`_id_path`が呼ぶ`queries.py`の関数の実名は、`queries.py`を読んで合わせること**
(`id_path`を導出している箇所が既にある。**新しく書かない**)。

- [ ] **Step 4: テストが通ることを確認する**

Run: `uv run pytest tests/test_api_overview.py -v`
Expected: PASS

- [ ] **Step 5: `app.py` に繋ぐ**

`lifespan`の中で`warm_up`の**後に**呼ぶ(索引が温まってからの方が速い)。
失敗しても起動は続ける(`warm_up`と同じ方針。理由をコメントに書く)。

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        warm_up(client, resolved_base_uri)
        # **第1層の集約を起動時に1回だけ計算する(裁定B103)。**
        # 失敗しても起動は続ける——`/overview`が503を返すだけで、
        # 検索やエンティティ表示は影響を受けない。
        try:
            app.state.overview = build_overview(
                client, resolved_base_uri, resolved_queries_dir
            )
        except Exception:
            logger.exception("第1層の集約に失敗した。/overview は503を返す")
            app.state.overview = None
        yield
```

`resolved_queries_dir = queries_dir or Path("queries/cq")` を
`create_app`の引数に足す(`generated_dir`と同じ作法)。

`GET /overview`は`app.state.overview`が`None`なら**503**を返す
(`/chat`が未設定のときに503を返すのと同じ作法)。

- [ ] **Step 6: イメージに `queries/` を焼く**

`docker/api.Dockerfile`:

```dockerfile
# **CQファイルを焼く(裁定B103)。`/overview`が実行時に読む。**
# 裁定B102で`schema/generated`を焼き忘れて本番のチャットが壊れたのと
# 同じ穴なので、`tests/test_api_image_contents.py`が両方を見る。
COPY queries ./queries
```

- [ ] **Step 7: `test_api_image_contents.py` を「実行時に読むディレクトリ全部」に広げる**

`create_app`の既定値を**2つとも**コードから取り出し、それぞれが
`COPY`されていること・`.dockerignore`に除外されていないことを見る形にする。
**パスを手書きしない**(既存のテストがそうしている理由と同じ)。

- [ ] **Step 8: OpenAPI型を再生成する**

```bash
bash scripts/generate-frontend-types.sh
```

`frontend/openapi.json`と`frontend/src/api/openapi-types.ts`を
**一緒にコミットする**(生成物はコミットする)。

- [ ] **Step 9: わざと壊して落ちることを確認する**

1. `overview.py`に`SELECT ?x WHERE { ?x ?y ?z }`を書き足す → 手書きSPARQL検査が落ちる
2. `OVERVIEW_QUERIES`の1つを別のファイル名にする → spy検査が落ちる
3. `api.Dockerfile`から`COPY queries`を消す → イメージ内容の検査が落ちる

**3件すべての失敗出力を報告に貼る。**

- [ ] **Step 10: ゲートを回して commit**

```bash
uv run ruff check src tests scripts
uv run pytest tests/test_api_overview.py tests/test_api_image_contents.py tests/test_api_app.py -q
git add src/jgkg/api/overview.py src/jgkg/api/models.py src/jgkg/api/app.py \
        docker/api.Dockerfile tests/test_api_overview.py tests/test_api_image_contents.py \
        frontend/openapi.json frontend/src/api/openapi-types.ts
git commit -m "feat(api): GET /overview を足し、第1層の数字をCQの答えから作る(裁定B103)"
```

---

## Task 2b: CQ19(素朴な合計と入口だけの合計)を足し、`/overview`に載せる

**なぜこのタスクがあるか(裁定B103の追記)**: モックの第4節は`spending`17項目と
`sumProblem`5項目を読んでいたが、CQ12が返すのは3つだけだった。
**第4節の中心の主張「予算123.1兆に対し支出の記録を全部足すと156.8兆。
合いません」にはCQ1本で足りる**ので、それだけを足す。
残り(推論に基づく所見)は画面に出さない —— 理由は裁定B103の追記にある。

**Files:**
- Create: `queries/cq/cq19-naive-sum-vs-entry-only.rq`
- Modify: `schema/competency-questions.md`
- Modify: `tests/test_competency_questions_phase1.py`
- Modify: `src/jgkg/api/overview.py`(`OVERVIEW_QUERIES`に1行・パーサ1本)
- Modify: `src/jgkg/api/models.py`(`NaiveSumVsEntryOnly` + `OverviewResponse`に1項目)
- Modify: `tests/test_api_overview.py`

**Interfaces:**
- Consumes: Task 2の`OVERVIEW_QUERIES`・`build_overview`・モデルの作法
- Produces: 列名 `?y ?naiveSum ?entryOnly ?blockCount`、
  `OverviewResponse.naive_sum_vs_entry_only: list[NaiveSumVsEntryOnly]`

- [ ] **Step 1: CQ19 を書く**

`queries/cq/cq19-naive-sum-vs-entry-only.rq`。**controllerが実測して
モックの値を完全再現したクエリである。そのまま使うこと:**

```sparql
# CQ19: 支出の記録を素朴に全部足すといくらで、国が自ら支出した分だけだと
# いくらか。年度ごとに(裁定B103の追記)
#
# **この2つの差が、この製品がいちばん説明しなければならないものである。**
# 予算(当初123.1兆)に対し、素朴な合計は156.8兆になる——差の33兆は
# 予算の不足ではなく**二重計上**である。RSの支出先ブロックは
# 「国→市町村→受給者」のような資金の流れを段ごとに記録するので、
# 全段を足すと同じお金を何度も数える(裁定B97)。
#
# `budget:paidByGovernment`が真のブロック=**入口**(国自身が支出した段)。
# それだけを足したものが`entryOnly`である。
# **国が自ら支払った額(CQ12)は`entryOnly` + 間接経費**であり、
# このクエリの`entryOnly`とは別の値になる(CQ12のヘッダ参照)。
#
# 実測(2026-09-11。本番と同じ索引1,438,620トリプル・1.390秒):
#   2025年度: naiveSum=156,775,926,742,671 / entryOnly=126,878,845,988,981
#             blockCount=19,125
# **この3つはモック用にCSVを全走査して出した値と一致する**
# (`docs/mockups/mock-data.js`の`overview.sumProblem.allBlocks`・
#  `overview.spending.naiveSum`/`entryTrue`)。
# blockCountはパイプラインの`budget_block_amount_checked`とも一致する。
#
# **`amount_jpy`は`core:`名前空間である**(`budget:`ではない)。
PREFIX budget: <https://jgkg.norr-tech.com/def/budget#>
PREFIX core: <https://jgkg.norr-tech.com/def/core#>
SELECT ?y
       (SUM(?all) AS ?naiveSum)
       (SUM(IF(?entry, ?all, 0)) AS ?entryOnly)
       (COUNT(?b) AS ?blockCount)
WHERE {
  ?b a budget:ExpenditureBlock ;
     budget:fiscalYear ?y ;
     core:amount_jpy ?all ;
     budget:paidByGovernment ?entry .
}
GROUP BY ?y
ORDER BY ?y
```

- [ ] **Step 2: fixtureに対して実測する(手で書かない)**

Task 1のStep 5と同じ形で測る(`JGKG_LAKE_DIR`を設定すること)。
出力をテストと`competency-questions.md`の期待値に使う。

- [ ] **Step 3: テストを書き、わざと壊して確認する**

**`SUM(IF(?entry, ?all, 0))`が効いていることを固定する。**
`entryOnly < naiveSum` を見るだけでは弱い(fixtureのブロックが
たまたまそうなっているだけかもしれない)。
**入口フラグが真のブロックの金額合計と一致すること**を、
別の経路(`budget_result`か、fixtureの`ExpenditureBlockLine`の定義)から
導いて突き合わせること。

壊し確認: `IF(?entry, ?all, 0)` を `?all` にすると
`naiveSum == entryOnly` になって落ちる、を示す。

- [ ] **Step 4: `schema/competency-questions.md` に CQ19 を足す**

「答えの例」テーブルにも1行。**CQ12との違い**(CQ12=入口+間接経費)を明記する。

- [ ] **Step 5: `/overview` に載せる**

`models.py`に足す:

```python
class NaiveSumVsEntryOnly(_Envelope):
    """CQ19の1行。**この2つの差が二重計上である**(裁定B97)。

    `entry_only`は`budget:paidByGovernment`が真のブロックだけの合計。
    **CQ12の「国が自ら支払った額」は`entry_only` + 間接経費**なので、
    この値とは一致しない——表示側で混同しないこと。
    """

    fiscal_year: int
    naive_sum: int
    entry_only: int
    block_count: int
```

`OVERVIEW_QUERIES`に `"naive_sum_vs_entry_only": "cq19-naive-sum-vs-entry-only.rq"`、
`OverviewResponse`に項目、パーサ1本。**手書きのSPARQLは書かない**(Task 2と同じ規律。
spyテストが落ちる)。

- [ ] **Step 6: 型を再生成し、ゲートを回して commit**

```bash
bash scripts/generate-frontend-types.sh
uv run ruff check src tests scripts
uv run pytest -q
```

`frontend/openapi.json`と`openapi-types.ts`も一緒にコミットする。

---

## Task 3: 第1層の骨格と「規模」「府省ごとの予算額」「5年分の予算と執行」

> **controller追記(2026-09-12): テストの置き方はこのリポジトリの作法に合わせる。
> 当初の計画は`views/overview.test.ts`を作ると書いていたが、それはできない。**
>
> **vitestにDOM環境が無い**(実測: `package.json`のdevDependenciesに
> jsdom/happy-domが無く、`vite.config.ts`にも`test`設定が無い)。
> つまりテストの中で`document`は使えない。
>
> **このリポジトリの既存の作法(実測)**:
> - テストがあるのは**純モジュール**だけ ——`format.test.ts`・
>   `graph-colors.test.ts`・`graph-theme.test.ts`・`labels.test.ts`・
>   `views/graph-merge.test.ts`
> - `views/graph-merge.ts`は`document.`/`window.`の参照が**0件**。
>   **ビューから抽出した純関数**である
> - `graph-theme.test.ts`は**偽のstyleオブジェクトを注入**する
>   (`{ getPropertyValue: (name) => ... }`)。`getComputedStyle`に触らない
>   ——**モジュールはインターフェースを受け取り、グローバルを見ない**
> - **ビュー本体(DOMを書く部分)は実ブラウザで確認する**(裁定B93:
>   「描画された」は「動く」ではない。押せるものを実際に押す)
>
> **したがってこうする**:
> - **純関数に切り出してテストする**: 金額の整形(`format.ts`)、
>   `sources`からCQ番号の導出、目盛り切替の注記文の組み立て、
>   `?y`と`?y+1`の対応付け(Task 4+5)
> - **DOMを書く`overview.ts`にはテストを置かない。** 代わりに実ブラウザで
>   確認し、**何を押して何が起きたかを報告に書く**
> - **jsdomを入れない。** テストのためだけに依存を増やす判断は、
>   この計画の範囲では取らない(原則1。必要になったら別途判断する)


**Files:**
- Create: `frontend/src/views/overview.ts`
- Create: `frontend/src/views/overview.test.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/style.css`

**Interfaces:**
- Consumes: `OverviewResponse`(Task 2。型は`openapi-types.ts`から取る。**手で型を書かない**)
- Produces: `renderOverview(root: HTMLElement): Promise<void>`、
  `formatAmountRounded(yen: number): string`(兆/億/万円に丸める)

**整形とレイアウトの参照元は、レビュー済みのモックである。**
`docs/mockups/top-page.html` を読んで、そこの実装に合わせること:

| 何 | モックの場所 |
|---|---|
| 兆/億/万円の丸め | `docs/mockups/top-page.html:1214`。**「丸めた値を出すときは正確な値も併記する」**という規律がコメントに書かれている——守ること |
| 円のそのまま表示 | 同 `:501` の `yen()`(`toLocaleString("ja-JP") + " 円"`) |
| 「並べると誤読される」の注記 | 同 `:1309` 付近。**予算と執行を並べるときの分母の説明**(裁定B99)。文言をそのまま持ってくる |
| 各節の見出しと順序 | `<h2>`を順に読む(6節) |

`frontend/src/format.ts`には**金額の整形関数がまだ無い**(実測: `esc`・
`provenanceHtml`・`truncationNotice`・`neighborhoodStatusText`・
`attributeValueHtml`・`describePathResult`・`chatSourceHtml`・
`toolCallLogEntryHtml`のみ)。**`format.ts`に足す**(`overview.ts`に
閉じ込めない——他の画面でも金額を出すため)。

- [ ] **Step 1: `client.ts` に `fetchOverview` を足す**

既存の`search`/`entityDetail`と同じ形にする(`getJson`を使う)。

```typescript
export async function fetchOverview(): Promise<OverviewResponse> {
  return getJson<OverviewResponse>(`${API_BASE}/overview`);
}
```

- [ ] **Step 2: 整形関数のテストを先に書く**

`frontend/src/views/overview.test.ts`。**モックのHTMLが使っていた丸め方と
同じ結果になること**を固定する(兆・億の桁。`docs/mockups/top-page.html`の
該当関数を読むこと)。

- [ ] **Step 3: `overview.ts` を書く**

**制約**:
- 棒グラフは**素のSVG**。ライブラリを入れない(原則1)
- **府省は23件すべて出す。「上位N件+残りM府省」にしない**
  (**この計画の当初の記述は誤りだった。モックはそうしていない** ——
  controllerがモックを読み直して訂正した)。
  モックが実際にやっていること(`docs/mockups/top-page.html:1252` の `renderBars`):
  - 全23府省を棒で出す。下位が幅0で消えないよう最小幅を持たせる
  - **目盛りの切替**を置く。既定は「全23府省」(最大=厚労省を棒いっぱい)、
    切替後は**厚労省を除いた22府省**で取り直す
  - 切替中は**いま何を見ているか**を画面に書く(モックの文言をそのまま使う。
    「厚労省(91.8兆・全体の74.6%)を除いた22府省のうち最大を棒いっぱいに
    しています。府省どうしの比較はこちらが読みやすく、全体に対する割合は
    『全23府省』が正確です」)
  - **対数目盛りにしない。** モックのコメントに理由がある ——
    「**対数は集中の事実を静かに消す**ので、切替なら『いま何を見ているか』が
    画面に書ける」。**厚労省が全体の約3/4という事実自体がこの画面の内容**であり、
    目盛りで薄めてはいけない
  **この判断はレビュー済みのモックが持っている。作り直さず写すこと。**
- 各節に「出所: CQnn」を出す(`OverviewResponse.sources`から。原則1)
- 表示名が`null`の府省は**IRIの経路形を出す**。`(表示名なし)`ではなく
  辿れる形にする——ここは裁定B78/B88の「合成しない」に抵触しない
  (IRIは合成ではない)
- ダークモード: 色は`style.css`のトークン(`--ink`等)から取る。
  **Sigmaと違ってCSSが効くので、色をJSに書かない**

- [ ] **Step 3b: `/overview`が503を返す場合を必ず扱う(計画の欠落。controllerが追記)**

**`getJson`は503で例外を投げる**(`frontend/src/api/client.ts`の
`if (!res.ok) throw new ApiError(res.status, ...)`)。
`/overview`は**起動時の集約が失敗すると503を返す設計**である
(`app.py`の`lifespan`が例外を飲んで`app.state.overview = None`にする)。
**だから`fetchOverview()`は失敗しうる。** そのとき:

- **トップページは壊れないこと。** 検索ボックスと`/def/`・GitHub Releasesへの
  リンクは今までどおり出る(それらは`/overview`に依存しない)
- 第1層の場所には**素の説明文**を出す。「全体の数字をいま出せません」程度にし、
  **利用者に内部事情を説明しない**(ただしコンソールには`ApiError`の内容を出す)
- **`apiUnavailableReason()`が非nullの場合(APIそのものが未配備)とは別の経路である。**
  前者はAPI全体が無い状態、こちらは**APIは動いているが集約だけが無い**状態。
  **2つの文言が同じでないことをテストで固定する** ——
  裁定B84の教訓「対処が違う2つの原因を区別できないメッセージはゲートの欠陥である」

- [ ] **Step 4: `router.ts` の `#/` に載せる**

検索ボックスは**残す**(今の入り口を壊さない)。第1層はその下に置く。
`apiUnavailableReason()`が非nullのときは第1層を出さない
(裁定B82の「準備中」表示と整合させる)。

- [ ] **Step 5: vitestを回し、わざと壊して確認する**

```bash
cd frontend && npx vitest run
```

- [ ] **Step 6: 実ブラウザで確認する。押せるものを実際に押す(裁定B93)**

`npm run dev`で起動し、**ローカルのAPIに対して**:
- 第1層が描かれること
- **府省の棒をクリックしてエンティティビューに飛ぶこと**
- ダークモード/ライトモード両方で読めること(`prefers-color-scheme`を切り替える)
- 幅400pxで崩れないこと

**「描画された」は「動く」ではない**(裁定B93)。押した結果を報告に書く。

- [ ] **Step 7: ゲートを回して commit**

---

## Task 4: 「いくら要求して、いくら付いたか」「国が自ら支払った額」「支払先はどこまで特定できているか」

> **controller裁定(2026-09-12): Task 4 と Task 5 を1回の実装で出す。**
> どちらも`frontend/src/views/overview.ts`だけを触り、**並行させられない**
> (同一ファイル)。分けると同じファイルに2回手が入り、レビューも2回になる。
> 節の追加(Task 4)と遷移の結線(Task 5)は互いに近く、
> **遷移先が実在するかは節を作った直後にしか確かめられない。**
> レビュー面は「3節 + 遷移」で、Task 3(骨格 + 3節 + 503経路)と同程度に収まる。


**Files:**
- Modify: `frontend/src/views/overview.ts`
- Modify: `frontend/src/views/overview.test.ts`

**Interfaces:**
- Consumes: Task 3の`overview.ts`の構造、`OverviewResponse`の残りの項目

- [ ] **Step 1: 「要求と査定」の年度のずれを表示側で解消する**

CQ16は年度をずらさずに返す(Task 1参照)。**表示側で
「年度Yの要求額 → 年度Y+1の当初予算」に並べ替える。**
**この対応付けをテストで固定する**——ずれを間違えると
「要求より多く付いた」ように見える。

- [ ] **Step 2: 「国が自ら支払った額」を出す(出す数字を絞る。裁定B103の追記)**

出すのは**3つだけ**:

1. **CQ19の`naiveSum`**(素朴に全部足すと156.8兆)
2. **CQ19の`entryOnly`**(入口だけだと126.9兆)
3. **CQ12の`governmentPaid`**(= 入口 + 間接経費。126,911,742,219,947円)

**この3つの並びが第4節の主張である** ——
「予算123.1兆(CQ14の当初予算)に対し、支出の記録を全部足すと156.8兆。
差は予算の不足ではなく二重計上である。」

**書かなければならない限界**(`cq12-*.rq`のヘッダに理由がある):
この数字は**下限であり、両方向に誤差がある**。32事業がフラグ無しで下振れ、
9事業の混在ブロックで上振れ、上限は63,863,635,000円(0.050%)。
**「正確な総額」と書いてはいけない。**

**出さないもの**: `inferredTotal`・`depths`・`mismatchExample`等の
推論に基づく所見(裁定B103の追記に一覧と理由)。
**代わりに節の末尾から`docs/decision-log.md`の裁定B97へ辿れるようにする。**

- [ ] **Step 2b: 段を通る資金の例を1件出す(CQ13。新しいCQは要らない)**

CQ13は「同じ金額が複数の段に記録されている事業」を20件返す。
**その1件目を描く。** モックの`flowDiagram`/`dupExample`は
まさにこの形のデータである(`docs/mockups/top-page.html`の該当節を読む)。
**事業を手で選ばない** ——CQ13が返す順の1件目を使う。

- [ ] **Step 3: 「支払先はどこまで特定できているか」を出す**

CQ17の4区分。**区分の表示名は`labels.ts`の
`enumValueLabel("recipientMatchCategory", category)`で引く**
(実在する関数。`frontend/src/labels.ts:53`)。**手で対応表を書かない。**
APIは`label`を返さない——理由はTask 2の`RecipientIdentification`の
docstringにある(SPARQLでは辿れない)。

型の表示名が要るところ(CQ18を使う「規模」の節)は`typeLabel(localName)`
(`frontend/src/labels.ts:34`)を使う。**`type`は完全IRIで返るので、
ローカル名への切り出しは表示側で行う。**

- [ ] **Step 4: テスト・実ブラウザ確認・commit**

Task 3のStep 5〜7と同じ手順。

---

## Task 5: 第1層から第2層(既存ビュー)への接続

**Files:**
- Modify: `frontend/src/views/overview.ts`
- Modify: `frontend/src/views/overview.test.ts`

**Interfaces:**
- Consumes: 既存の`routeToHash`(`router.ts`)、既存の`#/entity/{idPath}`・`#/path`

- [ ] **Step 1: 遷移先を`routeToHash`経由にする**

**URLを文字列で組み立てない。** `routeToHash({name:"entity", idPath})`を使う
——ハッシュの形が変わったときに黙って壊れないようにする。

- [ ] **Step 2: 遷移先が実在することをテストで固定する**

第1層が出す`idPath`が、`/entity/{idPath}`で引ける形であること
(パーセントエンコードの扱い。裁定B69/B73と同じ族)。

- [ ] **Step 3: 実ブラウザで、第1層の各節から実際に遷移してみる**

府省 → エンティティ → グラフ、の順に**実際に押す**。
グラフが描かれ、**展開ボタンと辺クリックが動くこと**も見る(裁定B93)。

- [ ] **Step 4: commit**

---

## Task 6: 「たとえば、こう辿れます」— **切る(controller裁定。2026-09-12)**

**実施しない。** 理由:

1. **新しいCQが2本必要である**(最も多くの事業の根拠になっている法令・
   最も多くの事業に支出先として現れる法人)。第1層の他の節と違い、
   **この節が無くても第1層は成立する** ——例示は導入の潤滑油であって、
   「日本政府の状態が把握しやすい」という目的そのものには要らない
2. **原則1**(本体はKGとオントロジー、アプリは検証装置。投資の中心をUIに
   置かない)。CQ15〜20で6本足しており、**例示のためにさらに2本足すのは
   UIのための投資が過ぎる**
3. **第2層への入口は既にある。** 府省の棒・照合区分・段を通る資金の例から
   既存のエンティティ/グラフビューへ辿れる(Task 5)。
   「こう辿れます」の実演は、実際に辿れる導線があれば要らない

**コスト**: 初めて開いた利用者が「何ができるのか」を掴む手がかりが1つ減る。
モックにはあった節なので、**利用者が見たいと言えば後から足せる**
(CQ2本と1節。独立している)。

---

## Task 7: 配備と検証

- [ ] **Step 1: 全ゲート**

```bash
uv run ruff check src tests scripts
uv run pytest -q
cd frontend && npx vitest run && npx tsc --noEmit
```

- [ ] **Step 2: 配信イメージを作り、`/overview`をローカルで確認する**

```bash
bash scripts/build-serve-images.sh release 2026-09-11-flow-and-history
curl -s http://localhost:8055/overview | head -c 400
```

**起動時間が伸びていることを測る。** 裁定B103の実測では、`/overview`が
走らせる7本の合計は**再起動直後7.282秒・ウォーム2.772秒**である。
D-6b-1の「起動→APIの最初の200まで10.938秒」に足すと約18秒の見込みだが、
**これは足し算であって実測ではない。実際に測って記録すること。**

- [ ] **Step 3: 本番へ配備し、`provisioningState: Succeeded` を確認する(裁定B91)**

`docs/deploy-aca.md`の手順に従う。**`minReplicas=1`を明示する**
(既定は0)。APIだけ差し替えるので`apiImageTag`を使う(裁定B102)。

- [ ] **Step 4: 本番で実ブラウザ確認。押せるものを押す**

- [ ] **Step 5: 文書を更新して commit**

`docs/status.md`(第1層の完了)、`docs/measurements-phase1.md`
(起動時間の実測)、`docs/decision-log.md`(この実装で出た裁定があれば)。
