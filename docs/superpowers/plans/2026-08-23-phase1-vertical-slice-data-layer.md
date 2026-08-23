# Phase 1 縦スライス データレイヤー(計画B)実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 法令(府省令・規則)→ 所管府省 → 予算事業 → 支出先法人 の縦スライスを実データで構築し、CQ1〜CQ10にSPARQLで答えられるKGと、更新の一巡(2つ目のリリース)を作る。

**Architecture:** Phase 0 の基盤(レイク→変換→名前付きグラフ→SHACLゲート→成果物)の上に、law/budget の2ドメインモジュールと2つのコネクタ(e-Gov API v2・RSシステム)を足す。府省の導出は決定的な経路1(法令番号)を完了条件の土台とし、経路2(根拠法令欄)は解決率の計測対象。全法人(約581万件)はストリーミングでN-Quadsに直接書き、SHACLはバッチで検証する。

**Tech Stack:** Python 3.12 / uv / rdflib / pySHACL / httpx / LinkML 1.11.1(ピン) / Apache Jena Fuseki 6.2.0(TDB2) / docker-compose

**Spec:** `docs/superpowers/specs/2026-08-22-japan-government-kg-design.md`(§1.2, §5.6, §6.4, §7, §8, §10 が本計画の根拠)

## 本計画のスコープ判定(仕様からの明示的な逸脱2件を含む)

| 判定 | 内容 | 根拠 |
|---|---|---|
| B-1 | **予算書XML(仕様§7.1のソース3)は本計画に含めない。** | CQ1〜CQ10のどれも予算科目階層(所管-組織-項-目)を問わない。§5.6「CQに答えられないオントロジーは不合格」の裏は「CQが消費しないクラスを作らない」。縦スライス(§1.2 B)もRSの所管府省で成立する。**消費者のいない取込みは作らない**(Phase 0 で「消費者のいない記録」を5回踏んだ)。科目階層のCQが立った時点で導入する |
| B-2 | **e-Gov は API v2 のメタデータを主経路にし、`all_xml.zip`(条文XML、約315MB)は取り込まない。** | CQ1/5/8/9 が要るのは law_num・title・abbrev・改正履歴であり、**条文本文を読むCQは1つも無い**。API v2 で全件メタデータをページングで取れることは実測済み(law_type=MinisterialOrdinance が 4,431件)。仕様§7.1は all_xml を「主経路」とするが、これは条文が要る前提の記述。条文のCQが立った時点で all_xml を追加する |
| B-3 | §1.2(B)のうち「**画面遷移だけで辿れる**」はアプリ(計画C)の完了条件。本計画は同じ経路を**SPARQLで双方向に辿れる**ところまでを担う(統合テストで固定) | データとアプリの層の分離(決定41) |
| B-4 | ~~abr-geocoderは住所列がある場合のみ導入~~ → **改訂(B14)**: 住所列は実在した(Task 6)。ただし支出先は法人番号直結が主経路なので、**名称のみ行の AMBIGUOUS 率を Task 11 で計測してから**導入を判断する。未計測のツール導入をしない | Ruling B14 |
| B-5 | 旧省庁名の**継承マッピングは作らない**(仕様§7.2の明示的先送りに従う)。ただし CQ9 が「旧省庁名のため未解決か」を問うため、**旧省庁名の判定リスト**(マッピングではなく集合)は持つ | §7.2 |

## Global Constraints(全タスクに適用)

- ベースURI = `https://jgkg.norr-tech.com`。**ドメイン文字列は書かない**(`config.py`・`base_uri.py` 経由)。新規ファイルは `uv run python -m jgkg.base_uri --check` が検査対象に含むこと
- `linkml==1.11.1` ピン。生成は `./scripts/generate-schema.sh` のみ。**生成物はコミットし、3回連続実行でバイト一致**を確認
- スキーマ変更後は `schema/all.yaml` の imports に追加(忘れると `test_all_shacl_covers_every_module` が落ちる)
- 言語タグ: 言語的内容は `LangString`、識別子・コードは plain string(R27)
- 上位クラスの `rdf:type` を実体化しない(R1)。SHACLは閉じたシェイプ
- グラフは置換、追記しない(§6.4)。未解決は `UnresolvedReference` で保持し件数を報告(§8.2)
- CSVは `errors="strict"`(R20)。**大きい入力はストリーミング**(R19)。`PYTHONUTF8=1` は生成スクリプト側で設定済み
- **クエリ・テストに「fixtureにしか無い値」を焼き込まない**(R45の円環)。実在値を使い、架空の主体は明らかに合成と分かる値(法人番号 9999999999999 等)
- **検査対象の一覧を手で書かない**。ソースから導出する(空振り3連発の教訓)
- 新しいテストは「**これは何があれば落ちるか**」を確認し、わざと壊して落ちる出力を報告に載せる
- コミットは論点ごと。`git add` 後に `git diff --cached --stat` を確認(R30)
- **ネットワークが要るタスク(3・5・6・11)とDockerが要るタスク(8・10・11)は明記してある。** それ以外のタスクはどちらも使わない
- 外部APIへの実アクセスはテストに含めない(§10)。記録した応答をfixtureにする

## File Structure

```
schema/law.yaml                 法令ドメイン(新規)
schema/budget.yaml              予算事業ドメイン(新規)
schema/all.yaml                 imports に law, budget を追加
src/jgkg/connectors/egov_law.py e-Gov API v2 コネクタ(新規)
src/jgkg/connectors/rs_system.py RSシステム コネクタ(新規)
src/jgkg/transform/law.py       法令番号→府省の経路1(新規)
src/jgkg/transform/rs.py        RS行→事業・支出(新規。列対応は rs_columns.py)
src/jgkg/transform/rs_columns.py Task 6 が実データで確定する列対応(新規)
src/jgkg/transform/old_ministries.py 旧省庁名の判定集合(新規)
src/jgkg/rdf/emit.py            emit_laws / emit_budget を追加
src/jgkg/rdf/stream_emit.py     全法人のストリーミングN-Quads出力(新規)
src/jgkg/validate.py            バッチ検証 validate_stream を追加
src/jgkg/lake.py                latest_before(差分検出用)を追加
src/jgkg/pipeline.py            複数ソースのオーケストレーション拡張
src/jgkg/rdf/provenance.py     sha256・recorded_on を追加
data/reference/ministry-codes.csv 全府省に拡張
data/reference/old-ministries.csv 旧省庁名リスト(新規)
queries/cq/cq01..cq10 *.rq      CQ1〜CQ10(新規)
tests/...                       各タスクに対応
```

---

### Task 1: 出典と記録の債務返済(sha256・日付の区別・manifest版・非推奨API)

全体レビューとその再レビューで Phase 1 送りにした「記録の穴」をまとめて塞ぐ。
後続タスクが出典を増やす**前**にやる(増えてから直すと対象が増える)。

**Files:**
- Modify: `schema/core.yaml`(出典プロパティ追加)
- Modify: `src/jgkg/rdf/provenance.py`
- Modify: `src/jgkg/build.py`(manifest_version)
- Modify: `src/jgkg/validate.py` / `src/jgkg/pipeline.py` / `tests/test_validate.py`(`Dataset.contexts`→`Dataset.graphs`、計3箇所)
- Modify: `queries/cq/p0-04-release-freshness.rq`
- Test: `tests/test_provenance.py`(新規)

**Interfaces:**
- Produces: 出典グラフに `core:sourceSha256`(plain string)と `core:recordedOn`(date)。
  `provenance` の emit 関数に `sha256: str | None` / `recorded_on: datetime.date | None` 引数を追加
- Produces: `Manifest.manifest_version: int = 2`(欄が無い旧 manifest は読み込み時に 1 とみなす)

- [ ] **Step 1: core.yaml に出典スロットを足す**

`prov:generatedAtTime` は従来どおり「そのグラフの内容がどの時点のものか」を表す。足すのは:

```yaml
  source_sha256:
    description: >-
      取得した一次資料のバイト列のSHA-256。レイクのスナップショットと一致し、
      KGから入力バイト列まで遡れる(レビューI1)。値はレイクのメタデータから取る
  recorded_on:
    description: >-
      リポジトリに参照表として記録した日。取得日(prov:generatedAtTime)とは
      別の概念(レビューMod①)。「取得」の無いソース(手作りの参照表)はこちらを持つ
    range: date
```

**注意**: これらは出典グラフ(`graph/provenance`)の語彙。UnresolvedReference には付けない
(閉じたシェイプに違反する)。

- [ ] **Step 2: 失敗するテストを書く**

```python
def test_provenance_carries_sha256_and_recorded_on(kg_dataset):
    """出典グラフから一次資料のsha256に遡れること。

    何があれば落ちるか: emit 側が sha256 を書かなくなったら落ちる。
    """
    g = kg_dataset.get_graph(URIRef(PROV_GRAPH_URI))
    shas = [str(o) for o in g.objects(None, CORE.sourceSha256)]
    assert shas, "sourceSha256 が1件も無い"
    assert all(len(x) == 64 and set(x) <= set("0123456789abcdef") for x in shas)
```

- [ ] **Step 3: Run test → FAIL を確認**
- [ ] **Step 4: provenance を拡張し、pipeline がレイクの `Snapshot.sha256` を渡す。**
  参照表(ministry-codes)は `sources.py` の `recorded_on`/`sha256` を渡す
- [ ] **Step 5: Run test → PASS**
- [ ] **Step 6: manifest_version=2。旧manifest(欄なし)読込テストも書く(→1とみなす)**
- [ ] **Step 7: `Dataset.contexts()` → `Dataset.graphs()`(3箇所)。全テスト実行で退行なし**
- [ ] **Step 8: P0-4 クエリを「取得日/記録日」ラベル付きの両対応にする**
- [ ] **Step 9: `./scripts/generate-schema.sh` → 3回連続バイト一致 → コミット**

```bash
git add schema/ src/jgkg/ tests/ queries/ schema/generated/
git diff --cached --stat
git commit -m "feat: 出典にsha256と記録日を持たせ、manifestに版を入れる"
```

---

### Task 2: law モジュールのスキーマ(law.yaml)

**Files:**
- Create: `schema/law.yaml`
- Modify: `schema/all.yaml`(imports に law を追加)
- Modify: `schema/core.yaml`(UnresolvedReasonEnum に `OLD_MINISTRY` を追加)
- Test: 既存の `tests/test_schema_consistency.py` は**モジュール一覧をschemaから動的導出する**ので、law は自動で検査対象に入る(手で足さない。増えなければ導出が壊れている)

**Interfaces:**
- Produces: `law:Law`(is_a: Work)、`law:LawRevision`(is_a: Event)
- Produces: スロット `law_id`(identifier, plain)/`law_num`(plain)/`law_num_type`(plain)/
  `law_title`(LangString)/`abbrev`(LangString, multivalued)/`promulgation_date`(date)/
  `repeal_status`(plain)/`jurisdiction`(range: Organization)/
  `amendment_law_num`(plain)/`amendment_enforcement_date`(date)/`revision_status`(plain)
- Produces: enum 値 `OLD_MINISTRY`(2001年再編前の省庁名のため現存府省に解決できない)

- [ ] **Step 1: law.yaml を書く**(core を import。`default_prefix: jgkglaw`。
  id/prefixes のURIは現行ベースURI配下 — `jgkg.base_uri` の書き換え対象に自動で入る)

```yaml
classes:
  Law:
    is_a: Work
    description: 法令。版(LawRevision)とは独立に、法令IDで同一性を持つ
    slots: [law_id, law_num, law_num_type, law_title, abbrev,
            promulgation_date, repeal_status, jurisdiction]
    slot_usage:
      law_id: { identifier: true }
  LawRevision:
    is_a: Event
    description: 改正イベント。どの法令の・いつ施行の版かを表す(CQ8の器)
    slots: [law_id, amendment_law_num, amendment_enforcement_date, revision_status]
```

- [ ] **Step 2: OLD_MINISTRY を UnresolvedReasonEnum に追加**(CQ9 が NO_CANDIDATE と
  区別して問うため。理由の分類はスキーマの意味論なので unresolved_key の値では代用しない)
- [ ] **Step 3: all.yaml の imports に law を追加**
- [ ] **Step 4: 生成 → `pytest tests/test_schema_consistency.py -v` で `[law]` パラメータが
  **自動で現れて**全緑になることを確認。現れなければ動的導出の回帰**
- [ ] **Step 5: 3回連続バイト一致 → コミット**

---

### Task 3: e-Gov API v2 コネクタ(全法令メタデータのスナップショット)

**ネットワークを使うタスク**(fixture収録時のみ)。テストは記録済み応答で行う(§10)。

**Files:**
- Create: `src/jgkg/connectors/egov_law.py`
- Modify: `src/jgkg/sources.py`(`egov-law` を登録。url=`https://laws.e-gov.go.jp/api/2/laws`、
  license_url は e-Gov法令APIの利用規約ページ、encoding=utf-8)
- Test: `tests/test_connector_egov.py` + `tests/fixtures/egov_laws_page1.json` / `page2.json`
  (実応答から2〜3件に縮めたもの。**値は実在の法令**を使う — R45)

**Interfaces:**
- Produces: `SOURCE_ID = "egov-law"` / `FILENAME = "laws.jsonl"` /
  `fetch(fetched_on: date, client: httpx.Client | None = None) -> FetchResult`
- 保存形式: **JSONL(1行 = 1法令のlawオブジェクト)**。各行は
  `json.dumps(law, ensure_ascii=False, sort_keys=True)`(**sort_keys は決定性のため**)

実測済みの事実(2026-08-23): `GET /api/2/laws?limit=N&offset=M` は
`{total_count, count, next_offset, laws: [{law_info: {law_id, law_num, law_num_era,
law_num_type, law_num_num, law_num_year, law_type, promulgation_date},
revision_info: {law_title, law_title_kana, abbrev, category, amendment_*, repeal_status,
current_revision_status, ...}}]}` を返す。`law_type=MinisterialOrdinance` は 4,431 件。
古い「閣令」も MinisterialOrdinance に含まれる。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_pagination_sums_to_total_count(monkeypatch, tmp_path):
    """ページを繋いだ行数が total_count と一致しなければ例外になること。

    何があれば落ちるか: next_offset の見落とし・打ち切りで全件スナップショットが
    欠けたとき。「取れただけ保存」は差分検出(Task 10)を静かに壊すので許さない。
    """
    pages = {
        0: {"total_count": 5, "count": 3, "next_offset": 3,
            "laws": [FIXTURE_LAW_1, FIXTURE_LAW_2, FIXTURE_LAW_3]},
        3: {"total_count": 5, "count": 2, "next_offset": None,
            "laws": [FIXTURE_LAW_4, FIXTURE_LAW_5]},
    }
    client = client_returning(pages)          # offset をキーに応答するスタブ httpx.Client
    result = egov_law.fetch(DAY, client=client)
    saved = lake.path_of("egov-law", DAY, egov_law.FILENAME).read_text(encoding="utf-8")
    assert len(saved.splitlines()) == 5

    broken = client_returning({0: pages[0]})  # 2ページ目を返さない
    with pytest.raises(egov_law.IncompleteSnapshotError):
        egov_law.fetch(DAY2, client=broken)
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: 実装**(`next_offset` が尽きるまで取得。ページ間 `time.sleep(0.5)`(公共APIへの礼儀)。
  合計 != total_count で `IncompleteSnapshotError`。`fetch_to_lake` で保存)
- [ ] **Step 4: Run → PASS → コミット**

---

### Task 4: 経路1 — 法令番号から府省を導出(transform/law.py)

縦スライスの完了条件の土台(§7.2)。**決定的で、LLMも曖昧照合も使わない。**

**Files:**
- Create: `src/jgkg/transform/law.py`
- Create: `src/jgkg/transform/old_ministries.py` + `data/reference/old-ministries.csv`
- Test: `tests/test_transform_law.py`

**Interfaces:**
- Consumes: Task 3 の `laws.jsonl`(レイクから `parse_laws(path) -> Iterator[LawRecord]`)
- Consumes: `ministry.build(orgs, reference)` の出力 `list[Ministry]` を
  `dict[name, Ministry]` にしたもの(**Ministry.houjin_bangou が府省URIの材料**。
  load_reference は (code, name) しか持たないので直接は使えない — 実行前スキャン B-S1)
- Produces:
  ```python
  class LawRecord(BaseModel):      # laws.jsonl の1行を正規化したもの
      law_id: str; law_num: str; law_num_type: str; law_type: str
      law_title: str; abbrev: list[str]; promulgation_date: str
      repeal_status: str; revisions: list[Revision]
  class JurisdictionResult(BaseModel):
      law_id: str
      ministry_names: list[str]          # 法令番号から抽出した名称(共同省令は複数)
      resolved: list[str]                # 解決できた府省の法人番号
      unresolved: list[UnresolvedJurisdiction]  # reason: OLD_MINISTRY / NO_CANDIDATE / AMBIGUOUS
  def derive_jurisdiction(record, reference) -> JurisdictionResult | None
      # None = 経路1の対象外(法令番号に府省名を含まない法律・政令など)
  ```

- [ ] **Step 1: 抽出の失敗するテストを書く。実在の法令番号を使う**(R45)

```python
CASES = [
    # (law_num, 期待する抽出名リスト)
    ("令和七年厚生労働省令第十号", ["厚生労働省"]),
    ("平成十三年総務省令第一号", ["総務省"]),
    ("平成十二年総理府・大蔵省令第三号", ["総理府", "大蔵省"]),   # 共同省令
    ("昭和二十六年大蔵省令第百号", ["大蔵省"]),                  # 旧省庁
    ("明治二十二年閣令第十二号", ["閣"]),                        # 閣令(旧)
    ("人事院規則一―四", ["人事院"]),                             # 規則
    ("令和三年法律第三十六号", None),                            # 対象外
    ("平成九年政令第二百七号", None),                            # 対象外
]
```

抽出規則: `(元号)(漢数字)年(X)令第…号` の X 部分を `・` で分割。`X` は
`…省|…府|…庁|人事院|閣` のいずれかで終わる並び。**law_num_type ではなく law_num の
文字列を正とする**(実測で law_num_type=CabinetOrder に太政官布告が入る例を確認済み。
型のラベルを信用しない)。規則(Rule)は「人事院規則」「会計検査院規則」等の先頭機関名。

- [ ] **Step 2: Run → FAIL → 抽出を実装 → PASS**
- [ ] **Step 3: 解決の失敗するテストを書く**(現存府省に一致→resolved、
  `old-ministries.csv` に載る名→OLD_MINISTRY、どちらでもない→NO_CANDIDATE、
  参照表に同名2行→AMBIGUOUS)。**わざと old-ministries から大蔵省を消して
  NO_CANDIDATE に化けることを確認**(理由の分類が機能している証拠)し、戻す
- [ ] **Step 4: old-ministries.csv を書く**(2001年再編で消えた省庁名+閣。
  出典として総務省の中央省庁等改革のページURLをコメントで記す。
  総理府/大蔵省/厚生省/労働省/通商産業省/運輸省/郵政省/自治省/建設省/文部省/
  科学技術庁/経済企画庁/国土庁/北海道開発庁/沖縄開発庁/総務庁/環境庁/金融再生委員会/閣 等)
- [ ] **Step 5: emit_laws を書く**(Task 7 と同じ emit 規約: 最も具体的な型のみ、
  言語的内容は `@ja`、jurisdiction は resolved の府省URIへ、unresolved は
  UnresolvedReference + `unresolved_reason` + `unresolved_key`=抽出名)
- [ ] **Step 6: 全テスト → 生成物影響なしを確認 → コミット**

---

### Task 5: 府省コード参照表を全府省に拡張(実データで検証)

**ネットワークを使うタスク**(GIFコードリストの取得のみ)。

**Files:**
- Modify: `data/reference/ministry-codes.csv`(3行 → 全府省)
- Modify: `src/jgkg/sources.py`(参照表の `recorded_on` / `sha256` を更新)
- Test: `tests/test_reference_ministries.py`(新規)

**Interfaces:**
- Produces: 全府省の (ministry_code, name) 行。**RSの所管府省名として現れる機関を網羅**
  (1府11省2庁 + こども家庭庁・国家公安委員会(警察庁)等、GIFコードリストの現行行)
- Consumes(検証): 実データの国の機関848件(Task 11 で突合率を再計測)

- [ ] **Step 1: GIF コードリスト(府省コード)を取得**(https://github.com/JDA-DM/GIF 配下。
  取得したファイル名・コミットSHA・取得日をCSV冒頭コメントに記録する)
- [ ] **Step 2: 失敗するテストを書く**

```python
def test_reference_covers_current_ministries():
    """参照表が最低限の現行府省を含むこと(何があれば落ちるか: 行の欠落)。"""
    names = {n for _, n in load_reference(REFERENCE_PATH)}
    for required in ["内閣府", "総務省", "法務省", "外務省", "財務省", "文部科学省",
                     "厚生労働省", "農林水産省", "経済産業省", "国土交通省",
                     "環境省", "防衛省", "デジタル庁", "復興庁"]:
        assert required in names, f"{required} が参照表に無い"

def test_reference_digest_matches_registry():
    """sources.py の sha256 と実ファイルが一致すること(更新漏れを止める)。既存テストを流用"""
```

- [ ] **Step 3: CSVを拡張 → PASS。sources.py の sha256/recorded_on を更新**
- [ ] **Step 4: fixture(zenken_rows)ベースのテストが壊れないことを確認**
  (参照表が増えても fixture に無い府省は AMBIGUOUS ではなく NO_CANDIDATE になり、
  CQ P0-5 の「未解決あり」fixture の期待件数が変わる — **期待値を数え直して更新**)
- [ ] **Step 5: コミット**

---

### Task 6: RS実データの取得と列検証(§7.3 の分岐タスク)

**ネットワークを使うタスク。** 本計画で唯一「結果によって後続の形が変わる」タスク。
**先に実データを見る。** 推測で rs.py を書かない(Phase 0 のC4の教訓)。

**Files:**
- Create: `src/jgkg/connectors/rs_system.py`
- Create: `src/jgkg/transform/rs_columns.py`(**実データで確定した列対応**。照合記録コメント付き)
- Create: `tests/fixtures/rs_sample.csv`(実データから数行。**実在の事業・実在の値**)
- Modify: `src/jgkg/sources.py`(rs-system を登録)
- Test: `tests/test_connector_rs.py`

**Interfaces:**
- Produces: `rs_columns.RS_COL: dict[str, str|int]`(論理名→物理列。論理名は最低:
  `project_id, project_name, ministry_name, fiscal_year, budget_amount,
  basis_law_text, recipient_name, recipient_houjin_bangou, expenditure_amount`)
- Produces: 検証結果の記録(§7.3 の分岐判定)を **このタスクの報告と rs_columns.py の
  照合記録コメント**に残す:
  1. 根拠法令の列は **ある / 無い**(無ければ経路2をPhase 2へ送る — 完了条件は経路1で成立)
  2. 支出先の法人番号列は **ある / 無い**(無ければ名称のみ名寄せに切替、
     列自体が無ければ支出先をPhase 2へ送り完了条件を `法令→府省→事業` に短縮)
  3. 支出先の住所列は **ある / 無い**(あれば B-4 により abr-geocoder 導入を起案)

- [ ] **Step 1: https://rssystem.go.jp/download-csv からCSVの実体URLを特定**
  (SPAのためページのXHRを確認。**特定したURL・年度・ファイル名・取得日を
  rs_columns.py に記録**)
- [ ] **Step 2: 1年度分を取得してレイクに保存**(`rs-<年度>.csv` または配布のzipのまま。
  配布形態を変えない — 法人番号のzenken.zipと同じ規約)
- [ ] **Step 3: ヘッダ行・列数・上記論理名の物理位置を確認して rs_columns.py に書く。**
  ヘッダの実文字列を引用として残す(照合記録)
- [ ] **Step 4: 実データから3〜5行を fixture に切り出す**(支出先の法人番号がある行・
  無い行・根拠法令がある行を含める)
- [ ] **Step 5: コネクタのテスト(fixture)→ 実装 → PASS → コミット**
  分岐が発生した場合(列が無い等)は、**このタスクで計画の後続タスクを書き換えず、
  報告に分岐内容を明記して controller の判定を仰ぐ**(§7.3 の表が判定基準)

---

### Task 7: budget モジュール(budget.yaml + transform/rs.py + emit_budget)

**Files:**
- Create: `schema/budget.yaml`(all.yaml の imports にも追加)
- Create: `src/jgkg/transform/rs.py`
- Modify: `src/jgkg/uris.py`(`budget_uri(fiscal_year, project_id)` / `expenditure_uri(fiscal_year, project_id, seq)` を追加 — URI構築はここに集約する規約。実行前スキャン B-S2)
- Modify: `src/jgkg/rdf/emit.py`(emit_budget)
- Test: `tests/test_transform_rs.py` / `tests/test_rdf_emit.py` に追加

**Interfaces:**
- Produces(スキーマ): `budget:BudgetProject`(is_a: Work。slots: project_id(identifier),
  project_name(LangString), fiscal_year(integer), ministry(range: Organization),
  budget_amount(integer, 円), basis_law(range: Law, multivalued)),
  `budget:Expenditure`(is_a: MonetaryItem。slots: project(range: BudgetProject),
  recipient(range: Agent), amount(integer, 円), fiscal_year(integer))
- Produces(変換): `parse_rs(path) -> Iterator[RsRow]`(rs_columns.RS_COL 経由でのみ列に触る)、
  `build_projects(rows, ministry_ref, laws_by_title) -> (projects, expenditures, unresolved)`
- URI 規約: `.../id/budget/{fiscal_year}/{project_id}`、
  支出はハッシュの安定ID `.../id/expenditure/{fiscal_year}/{project_id}/{連番}`
  (連番はソース内の行順。**行順が版間で安定しない場合は Task 10 の置換セマンティクスが
  吸収する** — グラフごと置き換わるため個別IDの持続性は要件でない)

- [ ] **Step 1: budget.yaml を書き、生成 → 動的検査に `[budget]` が現れて緑**
- [ ] **Step 2: 変換の失敗するテスト**(fixtureから: 事業→府省が参照表で解決される/
  支出先に法人番号がある行は直結/無い行は名称正規化の一意一致/一致しなければ
  UnresolvedReference(NO_CANDIDATE)。**金額のカンマ・全角数字の正規化**、
  空金額は0ではなく欠損として捨てて件数報告)
- [ ] **Step 3: 名称正規化を実装**(§8.1 の2段目。法人種別語(株式会社/(株)/㈱)の
  統一・全半角・空白除去。**血縁のある正規化のみ**。曖昧照合はしない)。
  照合対象の法人は「RSの支出先に現れた名称の集合」に限定して全件CSVを
  ストリーミングで1パスし、name→[法人番号] の辞書を作る(**5.8M行を辞書に
  全載せしない**。R19 と同じ理由)
- [ ] **Step 4: 経路2 — 根拠法令の解決(B13: law_id 結合を主にする)**
  Task 6 の実測で、RSの根拠法令列には **law_id(e-Govと同一形式)が付いている**。
  (1) **law_id 直結**(決定的。e-Govスナップショットに存在することを検査し、無ければ
  UnresolvedReference で保持) (2) law_id が欠落した行のみ law_title / abbrev の完全一致で
  フォールバック(解決率を計測。未解決は件数報告 — §7.2「精度目標であり完了条件でない」)
- [ ] **Step 5: emit_budget**(名前付きグラフ `graph/rs-system/{取得日}`。
  出典に Task 1 の sha256。閉じたシェイプで全域が通ることを SHACL テストで確認)
- [ ] **Step 6: 参照整合ゲートの対象が0件でないことを確認**(Task 4 指摘7の裁定: 法令・予算が
  pipeline に入ったことで、reference-classes.json のゲートが実際に非0件を検査するようになる。
  検査対象件数をレポートに出す)
- [ ] **Step 7: 全テスト → 3回バイト一致 → コミット**

---

### Task 8: 全法人のストリーミング投入(単価の実測を可能にする)

**Dockerを使うタスク**(tdbloader)。§6.2.3 の「規模は分割で対処」に従い、
**全法人は `graph/houjin-bangou-all/{日付}` という別グラフ**にする。国の機関(848件)の
既存グラフは変えない — 縦スライスの検証対象を小さく保ったまま、規模の実測と
支出先解決の照合先を手に入れる。

**Files:**
- Create: `src/jgkg/rdf/stream_emit.py`
- Modify: `src/jgkg/validate.py`(validate_stream)
- Modify: `src/jgkg/pipeline.py`(`--include-all-corporations` 相当のフラグ)
- Test: `tests/test_stream_emit.py`

**Interfaces:**
- Produces: `stream_emit_organizations(orgs: Iterator[Organization], graph_uri: str,
  out: IO[str]) -> StreamStats`(**rdflib を使わず** N-Quads 行を直接書く。
  IRI/リテラルのエスケープは rdflib の `Literal.n3()` を1行単位で使ってよいが、
  **Dataset に貯めない**)
- Produces: `validate_stream(nq_path, shapes_dir, batch_size=50_000) -> list[ValidationResult]`

**バッチSHACLが全体検証と等価である条件(このタスクの中心の論証):**
本設計のシェイプは**エンティティ局所**(閉じた NodeShape。エンティティを跨ぐ制約は
R2 で排除済み)なので、同一主語の全トリプルが同じバッチに入っていれば、
バッチ検証の合併 = 全体検証。これを成立させるため:
1. stream_emit は**1エンティティの全トリプルを連続して書く**(行の並びで保証)
2. バッチ境界は**主語の切れ目でのみ**切る
3. **同一法人番号の重複はバッチを跨ぐと検出できない**ため、上流で弾く:
   parse 済みの行を法人番号で dedup(後勝ち: 更新年月日 列[4]が新しい方)し、
   dedup 件数を StreamStats に報告(消したことを黙らない)
- [ ] **Step 1: dedup の失敗するテスト**(同一法人番号2行(更新日が異なる)→
  新しい方が残る/dedup件数=1が報告される)。**5.8M件の法人番号を set に載せる
  メモリ(int化して ~500MB)が上限内であることを見積もりとしてテストに注記**
- [ ] **Step 2: stream_emit のテスト**(fixture → N-Quads 行が rdflib で再パース可能/
  1エンティティ連続の保証/件数一致)
- [ ] **Step 3: validate_stream のテスト**(**バッチ=全体の等価性テスト**:
  fixture を batch_size=2 で割った結果と全体一発の結果が一致する。
  わざと主語跨ぎで割ると差が出ることも確認 — 等価条件が実質であることの証明)
- [ ] **Step 4: pipeline に組み込み**(フラグON時のみ。kg.nq へ追記する形で
  グラフを足す。レポートに corporations_all / dedup 件数を追加)
- [ ] **Step 5: コミット**(実行は Task 11)

---

### Task 9: CQ1〜CQ10 のクエリとテスト

**Files:**
- Create: `queries/cq/cq01-jurisdiction-of-ordinance.rq` 〜 `cq10-release-freshness.rq`(10本)
- Create: `tests/test_competency_questions_phase1.py`
- Create: `schema/competency-questions.md`(CQの正文と対応クエリの対照表。§5.6 の管理場所)

**Interfaces:**
- Consumes: Task 2/4/7 の語彙。fixture は law+budget+org を含む合成データセット
  (**実在の値**: 実在の府省令の law_id/law_num、実在の府省の法人番号。
  事業は架空でよいが project_id を明らかに合成と分かる形式にする — R45)

各CQの形(§5.6 の表と1対1。クエリに固有名を焼き込むのは CQ1/CQ3/CQ8 のような
「あるXの」型のみで、**値は実データに存在するものを使う**):

| # | クエリの骨子 |
|---|---|
| CQ1 | `?law law:jurisdiction ?ministry` を実在の府省令IDで引く |
| CQ2 | `?p budget:ministry <府省URI> . ?p budget:fiscalYear ?y . ?p budget:budgetAmount ?a` を年度でGROUP BY |
| CQ3 | `?e budget:recipient <法人URI> ; budget:amount ?a ; budget:fiscalYear ?y` ORDER BY ?y |
| CQ4 | 法人→支出→事業→府省→(経路1の)法令 をひと繋ぎで(プロパティパスではなく明示ジョイン。出典グラフを跨ぐ) |
| CQ5 | `?p budget:basisLaw ?law . ?p budget:ministry ?m` |
| CQ6 | `?e budget:recipient ?r . ?r a core:UnresolvedReference` のCOUNT(事業単位) |
| CQ7 | P0-3 の一般化。クエリには**実データとfixtureの両方に存在する特定のエッジ**(実在の府省令の jurisdiction)を焼く(B-S3。実在値のみ→fixtureで空振り、fixture値のみ→実データで0件、の両方を避ける) |
| CQ8 | `law:LawRevision` を law_id で絞り、`?d <= 指定日` の最大の版 |
| CQ9 | 法令の unresolved のうち `unresolved_reason = OLD_MINISTRY` と resolved を分けて数える |
| CQ10 | P0-4 の全ソース版(取得日/記録日ラベル付き) |

- [ ] **Step 1: fixture データセットの構築ヘルパー**(tests/phase1_fixture.py。
  府省令2件(現行1・旧省庁1)・事業2件・支出3件(解決2/未解決1)・改正2版)
- [ ] **Step 2: CQごとに失敗するテスト → クエリ実装 → PASS の繰り返し。**
  各テストは**正のコントロール**(期待件数>0)を必ず持ち、否定形のみの
  アサートを作らない(I5 の教訓)。**CQ6 と CQ9 はわざと壊して(未解決を
  解決済みに書き換えて)落ちる出力を報告に載せる**
- [ ] **Step 3: competency-questions.md に CQ正文・クエリファイル・答えの例を対照表で記載**
- [ ] **Step 4: コミット**

---

### Task 10: 更新の一巡(差分検出・置換・アトミック切替・鮮度)

§1.2(C)の器。**2世代の固定スナップショットで訂正・削除・据え置きの3態を検証する**(§10)。

**Files:**
- Modify: `src/jgkg/lake.py`(`latest_before(source_id, before: date) -> Snapshot | None`)
- Modify: `src/jgkg/pipeline.py`(**egov-law / rs-system ソースの結線を含む — Ruling B17。**
  Task 7 は emit_budget までを実装済みで、pipeline.run への結線は複数ソースの
  オーケストレーション変更と同時にここで行う。**RSを含むリリースは全法人グラフ必須**
  (recipient の参照整合。Task 7 懸念2)。差分検出: 前回スナップショットと sha256 が同じソースは
  「据え置き」としてグラフ再生成をスキップし、**前リリースのグラフを引き継ぐ**)
- Modify: `scripts/serve.sh`(アトミック切替: `data/artifact/current` を
  ディレクトリごと入れ替える。**稼働中のmmapディレクトリを上書きしない** —
  先に停止→退避→配置→起動の順を維持しつつ、前世代を `previous/` に必ず残す)
- Modify: `docker-compose.yml`(マウントを `./data/artifact/current/tdb2` に変更)
- Create: `src/jgkg/freshness.py`(ソースごとの想定頻度(sources.py に `expected_cadence_days`
  を追加)と最終成功取得日を突き合わせ、超過を一覧で返す)
- Test: `tests/test_update_cycle.py`

**Interfaces:**
- Produces: `PipelineReport.carried_over: list[str]`(据え置きで引き継いだグラフURI)
- Produces: `freshness.report(today) -> list[StaleSource]`

- [ ] **Step 1: 2世代fixtureの失敗するテスト**

```python
def test_replacement_reflects_correction_and_deletion(two_generation_lake, tmp_path):
    """訂正(名称変更)が新値だけになり、削除(行消滅)が消えること。

    何があれば落ちるか: 置換でなく追記に退化したら旧値が残って落ちる。
    """
    # 世代1: A(名称X)とB / 世代2: A(名称Y。訂正)のみ(Bは削除)
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME,
              zipped(zenken_row(houjin_bangou=NUM_A, name="X")
                     + zenken_row(houjin_bangou=NUM_B, name="B", seq="2")))
    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME,
              zipped(zenken_row(houjin_bangou=NUM_A, name="Y")))
    pipeline.run({"houjin-bangou": DAY1}, out1)
    pipeline.run({"houjin-bangou": DAY2}, out2)
    ds = load(out2 / "kg.nq")
    labels_of_A = {str(o) for o in ds.objects(URIRef(uri_A), SKOS.prefLabel)}
    assert labels_of_A == {"Y"}, "訂正の旧値が残っている(追記に退化)"
    assert (URIRef(uri_B), None, None) not in ds, "削除が反映されていない"

def test_unchanged_source_is_carried_over(two_generation_lake, tmp_path):
    """sha256が同じソースは再生成されず、carried_over に前リリースのグラフURIが載ること。

    何があれば落ちるか: 差分検出を外すと carried_over が空になり落ちる。
    """
    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, SAME_BYTES_AS_DAY1)
    r2 = pipeline.run({"houjin-bangou": DAY2}, tmp_path / "out2",
                      previous_release=DAY1)
    assert graph_uri("houjin-bangou", DAY1) in r2.carried_over

def test_failed_validation_keeps_previous_release(two_generation_lake, tmp_path):
    """世代2が検証に落ちたら成果物が作られず、世代1が残ること(§6.4)。

    何があれば落ちるか: 隔離ゲートを exit 0 に緩めると落ちる(C2の再発検知)。
    """
    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME,
              zipped(zenken_row(name="重複1") + zenken_row(name="重複2", seq="2")))
    with pytest.raises(pipeline.QuarantineNotEmptyError):
        run_and_gate({"houjin-bangou": DAY2}, tmp_path / "out2")
    assert (ARTIFACT_DIR / DAY1.isoformat() / "manifest.json").exists()
```

- [ ] **Step 2: latest_before / 差分検出 / carried_over を実装 → PASS**
- [ ] **Step 3: serve.sh の切替を実装。** 手で `bash scripts/serve.sh <日付>` を2回
  (別リリース)実行し、**前世代が previous/ に残ること・切替後にCQが新データを
  返すことを実機で確認して出力を報告に貼る**(実行系でしか出ない欠陥が7件出ている領域)
- [ ] **Step 4: freshness のテスト**(超過ソースが検知される/期限内は空。
  cadence は houjin-bangou=31日, egov-law=31日, rs-system=366日, 参照表=無期限)
- [ ] **Step 5: コミット**

---

### Task 11: 統合 — 実データの全経路実行と実測(縦スライスの検証)

**ネットワークとDockerを使うタスク。** 本計画の完了条件を実データで確認する。

**Files:**
- Create: `tests/test_vertical_slice.py`(fixtureでの統合テスト。CIで回る)
- Modify: `scripts/build.sh`(全ソース対応: houjin-bangou + egov-law + rs-system)
- Create: `docs/measurements-phase1.md`(実測の記録)

**Interfaces:**
- Consumes: Task 3〜10 のすべて

- [ ] **Step 1: fixtureでの縦スライス統合テスト(往復)**

```python
def test_vertical_slice_roundtrip(phase1_kg):
    """府省令 → 府省 → 事業 → 支出先法人 と、その逆をSPARQLで辿れること(§1.2 B のデータ層)。
    ホップごとに出典グラフ(CQ7)が付くこともここで固定する。"""
```

- [ ] **Step 2: 実データの取得**(egov-law 全件・rs-system 1年度分・houjin-bangou は
  取得済みスナップショットを使用)
- [ ] **Step 3: `bash scripts/build.sh <日付>` を全ソースで実行。**
  隔離が出たら止まる(--allow-partial を既定で使わない)。**実データで隔離が出たら
  それは発見であり、報告して判定を仰ぐ**
- [ ] **Step 4: 全法人フラグONで再実行し、単価を実測**(Task 8)。記録する数字:
  - TDB2実サイズ(全法人 約3,500万トリプル時)と**1トリプルあたりバイト数**
    (固定約192MiBを引いた増分/トリプル数)
  - **8GiB(Azure Container Apps の一時ディスク上限)に収まるかの判定**(§6.3)
  - tdbloader の時間、パイプライン全体の時間、ピークメモリ(可能なら)
  - 経路1: 府省令・規則のうち**現存府省に解決できた割合**(§7.3-3。OLD_MINISTRY /
    NO_CANDIDATE / AMBIGUOUS の内訳付き)
  - 経路2: 根拠法令欄の解決率
  - RS支出先: 法人番号あり/名称一致/未解決の内訳
  - 府省参照表の突合(Task 5 の全行が848件の実データに一意一致するか)
- [ ] **Step 5: serve → CQ1〜CQ10 を実エンドポイントで全実行し、答えを
  docs/measurements-phase1.md に貼る**(CQが実データに答えられることが§1.2(A))
- [ ] **Step 6: 2つ目のリリースを作る**(いずれかのソースを再取得して Task 10 の
  一巡を実データで通す。§1.2(C))
- [ ] **Step 7: docs/status.md を更新 → コミット**

---

### Task 12: R16 の返済 — 排他公理をスキーマ側へ移す

**Files:**
- Modify: `schema/core.yaml`(6軸+UnresolvedReference に `children_are_mutually_disjoint` 相当を検討)
- Modify: `schema/overlay/core-axioms.ttl` / `tests/test_overlay.py`

**Interfaces:** 生成OWLの disjointness 公理が21ペアのまま維持されること(表現の置き場所だけが変わる)

- [ ] **Step 1: LinkML の該当機能で21ペアが生成できるかを実機で確認**(できなければ
  このタスクは「確認結果の記録」で終了し、オーバーレイ維持を確定する — 撤退条件明記)
- [ ] **Step 2: 移せる場合: スキーマへ移し、オーバーレイからは削除。**
  オーバーレイの整合テストは「対象0件で合格」に退化するので、**オーバーレイが
  空になった場合はテスト自体を『空であること』の検査に置き換える**(R16 の懸念の解消)
- [ ] **Step 3: 生成OWLの disjoint ペア数=21 のテストが**移行前後で**緑のまま → コミット**

---

## Phase 1(計画B)の完了条件

- [ ] `uv run pytest tests/` 全件成功、`ruff` 緑、`jgkg.base_uri --check` 緑
- [ ] 生成物がコミット済みと一致(3回連続バイト一致)
- [ ] **CQ1〜CQ10 が実データのエンドポイントで答えを返す**(§1.2 A。答えは docs/measurements-phase1.md に記録)
- [ ] **縦スライスをSPARQLで双方向に辿れる**(fixture統合テスト+実データ確認。§1.2 B のデータ層)
- [ ] **更新の一巡を実データで通し、2つ目のリリースが存在する**(§1.2 C)
- [ ] 全法人投入時の TDB2 実サイズ・単価・8GiB判定・各解決率が記録されている
- [ ] 未解決(OLD_MINISTRY / NO_CANDIDATE / AMBIGUOUS)の件数が pipeline-report と CQ9 の両方から見える

**計画Cに送るもの**: §9 API層・可視化アプリ、§1.2(B)の「画面遷移」部分。
**Phase 2 に送るもの(仕様の既定どおり)**: 旧省庁の継承マッピング、条文レベルの根拠法令解決、
予算書XML(科目階層)、政府の公表訂正の履歴化。

## 計画Bの自己レビュー

| 仕様の要求 | タスク |
|---|---|
| §1.2 A(CQ1〜10) | Task 9, 11 |
| §1.2 B(縦スライスのデータ層) | Task 4, 7, 11 |
| §1.2 C(更新の一巡) | Task 10, 11 |
| §5.6 CQ管理(competency-questions.md) | Task 9 |
| §6.4 置換・リリース・鮮度・隔離 | Task 10 |
| §7.1 ソース(1b, 2, 4, 5) | Task 3, 6, 既存, 5(3=予算書XMLは B-1 で明示的に除外) |
| §7.2 経路1/経路2/旧省庁の扱い | Task 4(OLD_MINISTRY), 7 |
| §7.3 検証項目1〜3(4は Task 5 で解消) | Task 6, 11 |
| §8.1 三段(ID直結/正規化/blocking の限定形) | Task 7 |
| §8.2 未解決の保持と計測 | Task 4, 7, 9(CQ6/9) |
| §10 2世代置換テスト・縦スライス統合テスト | Task 10, 11 |
| レビュー繰越(I1 sha256 / Mod① 日付 / manifest版 / Dataset.graphs / アトミック切替 / R16) | Task 1, 10, 12 |
| 実測(単価・8GiB判定・解決率) | Task 11 |

**型整合の確認**: `law_id` は Task 2(identifier)→ Task 3(JSONL の law_info.law_id)→
Task 4(LawRecord.law_id)→ Task 9(CQ1/8/9)で同名。`jurisdiction` は Task 2 で宣言し
Task 4 の emit と Task 9 の CQ1 が使う。`RS_COL` の論理名は Task 6 が確定し Task 7 だけが触る。
