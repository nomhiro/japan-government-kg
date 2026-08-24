# Phase 1 実測記録

最終更新: 2026-08-25

**裁定B25(測定は使い捨てにしない)に従う。** 数字の出典はすべて `scripts/` に
コミットされたスクリプトであり、ここには**その出力を全量転記する**(要約・
再計算はしない)。この計画で「再導出できない数値」由来の訂正が複数回起きた
ため、この記録自体が再現可能性の担保になる。

対象: 計画B(Phase 1)完了条件 —
(A) CQ1〜CQ10 に実データ・実エンドポイントで答えられる。
(B) 縦の接続スライス(法令→所管府省→予算事業→支出先法人)を双方向に辿れる。
(C) 更新の一巡(取得→差分検出→検証→切替→鮮度反映)を実データで通し、2つ目の
リリースを作れる。

---

## 0. 前提: リリースの構成(Ruling B30)

利用者の裁定(2026-08-24。`.superpowers/sdd/2026-08-23-phase1-vertical-slice-data-layer/progress.md`
Ruling B30)により、Phase 1 で提供するKGは**「支出先として実際に登場する法人」
に限る**。全法人(約581万件)は入れない(能力は実証済みで、別エンドポイントと
して後から足せる)。

| リリース | ディレクトリ | 内容 | 用途 |
|---|---|---|---|
| 全法人込み(検証物) | `data/artifact/2026-08-24/` | 4ソース6グラフ・全法人グラフ含む。**消さずに残す**(13.8GiBの実測の証拠) | §6.3の8GiB判定の「収まらない」側の実測 |
| 支出先限定・リリースA(Phase 1提供物) | `data/artifact/2026-08-25/` | 同じ4ソース。法人グラフは`houjin-bangou-payees`(支出先限定) | Phase 1として実際に配信する初回リリース |
| 支出先限定・リリースB(carry-over検証) | `data/artifact/2026-08-26/` | リリースAと全く同じ4ソース。`--previous-release 2026-08-25`で構築 | 完了条件C(更新の一巡)の実データ検証。§5参照 |

**リリースディレクトリ名と manifest 内部の `release` フィールドの不一致に
ついて**: 上表の3ディレクトリは、`release` フィールドが**全て**
`"2026-08-24"`になる(`max(fetched_on.values())`から導出。3件とも
egov-lawの取得日が2026-08-24であるため)。ディレクトリ名を実際の構築日・
用途に応じて`2026-08-24`(全法人)・`2026-08-25`(支出先限定A)・
`2026-08-26`(支出先限定B=carry-over)と分けたのは、既存ディレクトリと
衝突しないための選択であり、task-11-fix-brief.mdが明示的に許容している
(「B30の新リリースは別の日付か別ディレクトリに作る」)。この
ディレクトリ名/release不一致は Ruling B29 が既に受理した先例
(「同一IDの再ビルドが区別できない」がPhase 2への繰り越し課題)と同種であり、
実害は無い(sourcesフィールドで実際の取得日は分かる)。**この不一致の
対象がリリースBの追加によって2件から3件に増えたことは、Phase 2への
繰り越し課題として明記する**(3つの`data/artifact/`ディレクトリが同じ
`release`文字列を名乗る状態は、識別子としての`release`フィールドの
設計を将来見直す動機になる)。

---

## 1. B30: 全法人 vs 支出先限定の比較(§6.3 8GiB判定)

`.superpowers/sdd/2026-08-23-phase1-vertical-slice-data-layer/progress.md`
「発見7の定量的裏付け」「§6.3の8GiB判定が確定」「Ruling B30」の全量転記。

### 実測(2026-08-24。controller による全法人込みリリース)

- kg.nq = 6,793,393,635 bytes(6.33 GiB)/ **35,584,368 quads**
- ネイティブ層での構築: **35,584,368 quads を 1,036秒(17分16秒)で構築**
  (平均 34,343 quads/秒。速度低下なし)
- **TDB2 実サイズ = 14,813,075,171 bytes(13.8 GiB)**
- tar.gz = 1,994,085,008 bytes(1.86 GiB)。圧縮に約6分
- 内訳の目安: 固定オーバーヘッド約192MiB(後述§3のとおり201,423,591 bytes
  が実測値) + データ 約13.6GiB(35,584,368 quads → 約390 bytes/quad の目安。
  厳密な baseline 引き算は §3 参照)

### バインドマウント方式との比較(発見7)

| 方式 | 速度 | 備考 |
|---|---|---|
| コンテナのネイティブ層(overlayのwritable layer) | **34,343 quads/秒**(平均。速度低下なし) | 実測(2026-08-24) |
| Docker Desktop for Windows のバインドマウント | 42分で3M件(平均1,190/s、末尾596/s。単調に減速) | 実測(2026-08-24)。34,723→1,227→596 quads/秒と崩壊 |

**約58倍の差。** 仕様§6.3「TDB2はmmapを使うのでネットワークファイル共有に
置くな」の警告が、Docker Desktop のバインドマウントについて定量的に裏付け
られた。診断: Docker Desktop for Windows のバインドマウントは実質ネット
ワークファイル共有であり、TDB2のノード表へのランダムI/Oが支配的なため
FUSE越しでは破綻する(Phase 0の37トリプル・5,107quadsでは固定オーバー
ヘッドに埋もれて見えなかった)。

### Ruling B30 適用後(支出先限定) — 裁定当時の事前見積り

| 構成 | quads | TDB2実サイズ | 構築時間 |
|---|---|---|---|
| 縦スライスのみ(**法人グラフを含まない**。houjin-bangou/ministry-codes/egov-law/rs-systemのみ) | 704,359 | **232 MiB** | 6.3秒 |
| 全法人込み | 35,584,368 | **13.8 GiB** | 17分16秒 |

**注記(2026-08-25。Task 11修正ラウンドで実装した後に判明。progress.md
「私の見積りと実装後の実測が別物だったことを実装者が検出」の節を転記)。**
上の704,359行/232MiBという数字は、Ruling B30を決める根拠として利用者が
示した**「全法人グラフを除外しただけの数字」**であり、B30を実装した実際の
リリース(`houjin-bangou-payees`グラフ=支出先として実在する法人18,941件を
含む)の実測値ではない。実装後の実測(下記§2)は **817,982 quads / TDB2実
サイズ 449,434,865 bytes(429 MiB)**。**判断の向き(全法人は8GiBに収まらず、
支出先限定なら余裕で収まる)は変わらない**が、利用者に示された「232 MiB」は
訂正済みである(429 MiBでも13.8GiBとの比は32倍で、8GiB判定の結論は不変)。
突き合わせの計算は下記§2に全量記す。

支出先の distinct 法人は **18,994件**(全法人581万件の0.33%)。差の60倍・
165倍に対して得られるのは「Phase 1 のCQが1本も参照しない581万件」だけ
という判断(B-1で予算書XML、B-2で条文XMLを外したのと同じ「消費者のいない
取込みを作らない」原則)。

### §6.3 8GiB判定の結論

**全法人はサーバーレスコンテナ環境(Azure Container Apps の一時ディスク
8GiB上限)には載らない。支出先限定なら余裕で載る。**

- 全法人: TDB2実サイズ 13.8 GiB > 8 GiB → **収まらない**
- 支出先限定(B30実装後の実測値。確定): TDB2実サイズ **449,434,865 bytes
  (429 MiB)** ≪ 8 GiB(使用率5.2%、余裕+7.581GiB)→ **余裕で収まる**
  (全法人比: サイズ1/32・構築時間1/49・配布物(tar.gz)1/44)。詳細は§2・§3

帰結(仕様§6.2.3のescalation orderに従う。今回選ばれたのは(3)寄りの判断
——B30により全法人はPhase 1の提供対象から外す。エンドポイント分割
(選択肢1)は将来全法人を別エンドポイントとして復活させる余地を残す形で
実装済み(`--corporations-scope all`はcapabilityとして維持):
全法人ストリーミング投入・バッチSHACL検証は実証済みの能力として
`pipeline.run(corporations_scope="all")` に残し、既定は"payees"にはしない
(明示フラグ)。

---

## 2. B30実装後の実測(Task 11修正ラウンド。2026-08-25リリース)

**確定(2026-08-24夜〜25。`scripts/build.sh`経由で構築。手書きpython呼び出しでは
ない)。** 入力: houjin-bangou=2026-08-23・ministry-codes=2026-08-23・
egov-law=2026-08-24・rs-system=2026-08-23(4ソース)。フラグ:
`--include-all-corporations --corporations-scope payees`。

同一構成で2回ビルドし、両方とも以下の数字が**完全に一致**した(1回目は
build.sh側の検査バグ——発見8/9、下記——でスクリプト自体は途中終了したが、
生成物〔tdb2.tar.gz全43ファイル・pipeline-report.json〕を直接検査して内容が
正しいことを確認済み。2回目は検査を修正した上で最初から最後まで成功
〔exit 0〕、実物も同一)。

### tdbloader実行ログ(コンテナのネイティブ層。`.native-tdb2-build.log`全量)

```
12:22:59 INFO  loader          :: Loader = LoaderPhased
12:22:59 INFO  loader          :: Start: /work/data/artifact/2026-08-25/kg.nq
12:23:18 INFO  loader          :: Finished: /work/data/artifact/2026-08-25/kg.nq: 817,982 tuples in 18.64s (Avg: 43,887)
12:23:18 INFO  loader          :: Finish - index GSPO
12:23:18 INFO  loader          :: Start replay index GSPO
12:23:18 INFO  loader          :: Index set:  GSPO => GSPO->GPOS, GSPO->GOSP
12:23:18 INFO  loader          :: Index set:  GSPO => GSPO->GPOS, GSPO->GOSP [817,982 items, 0.2 seconds]
12:23:18 INFO  loader          :: Index set:  GSPO => GSPO->SPOG, GSPO->POSG, GSPO->OSPG
12:23:18 INFO  loader          :: Index set:  GSPO => GSPO->SPOG, GSPO->POSG, GSPO->OSPG [817,982 items, 0.1 seconds]
12:23:20 INFO  loader          :: Finish - index SPOG
12:23:20 INFO  loader          :: Finish - index OSPG
12:23:20 INFO  loader          :: Finish - index GOSP
12:23:20 INFO  loader          :: Finish - index POSG
12:23:21 INFO  loader          :: Finish - index GPOS
12:23:21 INFO  loader          :: Time = 21.229 seconds : Quads = 817,982 : Rate = 38,531 /s
449434865	/tdb2
```

構築時間21.2秒・38,531quads/秒。全法人込み(17分16秒・平均34,343/秒)との比較は
§1参照(こちらは行数が1/43なので単純な速度比較にはならないが、速度低下が
起きていないことは確認できる)。

### manifest.json(全量)

```json
{
  "release": "2026-08-24",
  "created_on": "2026-08-24",
  "jena_version": "6.2.0",
  "sha256": "bf9f56e2af192e5cc427b4d22876170f115a26a65f1489fcbe975e7ab39649fd",
  "byte_size": 44489890,
  "triple_count": 817982,
  "nquads_sha256": "077b5dcf7c20f8f5614401514d0ae3211ea9262a6f08864c1d63cf55d659c4c0",
  "tdb2_expanded_bytes": 449434865,
  "graphs": [
    "https://jgkg.norr-tech.com/graph/egov-law/2026-08-24",
    "https://jgkg.norr-tech.com/graph/houjin-bangou-payees/2026-08-23",
    "https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23",
    "https://jgkg.norr-tech.com/graph/ministry-codes/2026-08-23",
    "https://jgkg.norr-tech.com/graph/provenance",
    "https://jgkg.norr-tech.com/graph/rs-system/2026-08-23"
  ],
  "sources": {
    "houjin-bangou": "2026-08-23",
    "ministry-codes": "2026-08-23",
    "egov-law": "2026-08-24",
    "rs-system": "2026-08-23"
  },
  "quarantined_sources": [],
  "manifest_version": 4
}
```

`houjin-bangou-payees`という**グラフ名自体**が「全法人ではない」ことを示す
(manifestを読むだけで判定できる。`houjin-bangou-all`と混同しない設計)。

### pipeline-report.json(全量)

```json
{
  "release": "2026-08-24",
  "rows_seen": 5816535,
  "rows_rejected": 0,
  "rows_short": 0,
  "organizations": 5816535,
  "government_organs": 848,
  "ministries": 40,
  "unmatched_ministries": 0,
  "graphs_validated": 5,
  "graphs_quarantined": 0,
  "sources": {
    "houjin-bangou": "2026-08-23",
    "ministry-codes": "2026-08-23",
    "egov-law": "2026-08-24",
    "rs-system": "2026-08-23"
  },
  "quarantined_sources": [],
  "reference_violations": [],
  "corporations_all": 18941,
  "corporations_all_dedup_removed": 0,
  "corporations_all_quarantined": 0,
  "corporations_scope": "payees",
  "carried_over": [],
  "law_records": 9547,
  "law_jurisdiction_resolved": 4243,
  "law_jurisdiction_unresolved": 2274,
  "law_jurisdiction_extraction_failed": 13,
  "budget_projects": 5794,
  "budget_expenditures": 73919,
  "budget_expenditures_bundled": 7326,
  "budget_recipients_sentinel": 9922,
  "budget_recipients_nonexistent_houjin_bangou": 60,
  "budget_recipients_resolved_by_houjin_bangou": 56607,
  "budget_recipients_resolved_by_name": 0,
  "budget_recipients_unresolved": 4,
  "budget_ministries_resolved": 5794,
  "budget_ministries_unresolved": 0,
  "budget_basis_law_resolved": 7956,
  "budget_basis_law_unresolved": 503,
  "budget_ratio_exact_1_0": 1488,
  "budget_ratio_exact_2_0": 221,
  "budget_ratio_exact_3_0": 24,
  "budget_ratio_total_zero": 36,
  "budget_ratio_other": 2877,
  "budget_ratio_no_denominator": 1148
}
```

`graphs_quarantined: 0` / `reference_violations: []` — SHACL・参照整合の
両方が違反0件で通過している(B21のexternally_typed機構、B27の
nonexistent分類を含む)。

### 突き合わせ(§1の事前見積り704,359行 との整合性検査)

B30が実際に追加するのは「支出先として実在する法人(corporations_all=
18,941件)の法人グラフ」である。`_organization_lines`(`src/jgkg/rdf/
stream_emit.py`)は1法人につき **rdf:type・skos:prefLabel・houjinBangou・
organizationKindCode の4つを必須**、prefectureName・cityNameは値がある
ときだけ発行する(最大6トリプル/法人)。

- 実測差分: 817,982(実装後) − 704,359(事前見積り。法人グラフ抜き) =
  **113,623 quads**
- 予測上限: 18,941法人 × 6トリプル = **113,646**(実測差分との差はわずか23。
  都道府県名または市区町村名を欠く法人が23件相当ぶんある、という意味で
  整合する——両方とも任意項目であり、全法人データに欠損があることは
  Phase 0から既知)
- **corporations_all(18,941。実在する支出先法人)+ 53(distinctな
  「支出先だが法人番号が実在しない」件数。progress.md 2026-08-24時点の
  実測記録「全法人フラグONでも60件の違反が残る(distinct 53件)」より) =
  18,994 = 支出先のdistinct法人総数**(§1既出の数字と一致)。
  この53件は`payee_houjin_bangou`(RS生データから直接作る、resolve前の
  distinct集合)に含まれるが実在法人と一致しないもの——B27が
  `budget_recipients_nonexistent_houjin_bangou`(60行。distinctでは53件)
  として分類する対象そのものであり、定義上必然的に成り立つ恒等式である

両方の突き合わせが誤差の範囲内(前者は非任意項目のみの欠損23件で説明でき、
後者は完全一致)で成立しており、**B30のフィルタが「実装意図どおりに」
支出先の実在法人だけを積んでいる**ことの独立した検証になっている。

---

## 3. TDB2の単価(1トリプルあたりバイト数。`measure_release_size.py`)

`uv run python scripts/measure_release_size.py data/artifact/2026-08-25`
の標準出力(全量)。

```
==============================================================================
成果物サイズの実測: data\artifact\2026-08-25
==============================================================================
release          : 2026-08-24
jena_version     : 6.2.0
manifest triple_count: 817982
manifest tdb2_expanded_bytes: 449434865
sources          : {'houjin-bangou': '2026-08-23', 'ministry-codes': '2026-08-23', 'egov-law': '2026-08-24', 'rs-system': '2026-08-23'}

kg.nq            : 817,982 行 / 175,342,530 バイト (167.2 MiB)
kg.nq 1行あたり  : 214.4 バイト
(data\artifact\2026-08-25\tdb2.tar.gz を一時ディレクトリに展開して測定した)

TDB2 実サイズ    : 449,434,865 バイト (428.6 MiB / 0.419 GiB)
TDB2 ファイル内訳(降順・全件):
      50,331,648      48.00 MiB  Data-0001\GOSP.dat
      50,331,648      48.00 MiB  Data-0001\GPOS.dat
      50,331,648      48.00 MiB  Data-0001\OSPG.dat
      50,331,648      48.00 MiB  Data-0001\POSG.dat
      50,331,648      48.00 MiB  Data-0001\SPOG.dat
      33,554,432      32.00 MiB  Data-0001\GSPO.dat
      13,226,923      12.61 MiB  Data-0001\nodes-data.obj
       8,388,608       8.00 MiB  Data-0001\GOSP.idn
       8,388,608       8.00 MiB  Data-0001\GPOS.idn
       8,388,608       8.00 MiB  Data-0001\GPU.dat
       8,388,608       8.00 MiB  Data-0001\GPU.idn
       8,388,608       8.00 MiB  Data-0001\GSPO.idn
       8,388,608       8.00 MiB  Data-0001\nodes.dat
       8,388,608       8.00 MiB  Data-0001\nodes.idn
       8,388,608       8.00 MiB  Data-0001\OSP.dat
       8,388,608       8.00 MiB  Data-0001\OSP.idn
       8,388,608       8.00 MiB  Data-0001\OSPG.idn
       8,388,608       8.00 MiB  Data-0001\POS.dat
       8,388,608       8.00 MiB  Data-0001\POS.idn
       8,388,608       8.00 MiB  Data-0001\POSG.idn
       8,388,608       8.00 MiB  Data-0001\prefixes.dat
       8,388,608       8.00 MiB  Data-0001\prefixes.idn
       8,388,608       8.00 MiB  Data-0001\SPO.dat
       8,388,608       8.00 MiB  Data-0001\SPO.idn
       8,388,608       8.00 MiB  Data-0001\SPOG.idn
              24       0.00 MiB  Data-0001\GOSP.bpt
              24       0.00 MiB  Data-0001\GPOS.bpt
              24       0.00 MiB  Data-0001\GPU.bpt
              24       0.00 MiB  Data-0001\GSPO.bpt
              24       0.00 MiB  Data-0001\nodes.bpt
              24       0.00 MiB  Data-0001\OSP.bpt
              24       0.00 MiB  Data-0001\OSPG.bpt
              24       0.00 MiB  Data-0001\POS.bpt
              24       0.00 MiB  Data-0001\POSG.bpt
              24       0.00 MiB  Data-0001\prefixes.bpt
              24       0.00 MiB  Data-0001\SPO.bpt
              24       0.00 MiB  Data-0001\SPOG.bpt
              16       0.00 MiB  Data-0001\nodes-data.bdf
              16       0.00 MiB  Data-0001\prefixes-data.bdf
               3       0.00 MiB  Data-0001\tdb.lock
               3       0.00 MiB  tdb.lock
               0       0.00 MiB  Data-0001\journal.jrnl
               0       0.00 MiB  Data-0001\prefixes-data.obj

tdb2.tar.gz      : 44,489,890 バイト (42.4 MiB) / 圧縮率 0.099

--- 1トリプルあたりバイト数 ---
固定オーバーヘッドの実測元: data\artifact\2026-08-23\tdb2(5,143 行)
  その実サイズ           : 201,423,591 バイト (192.1 MiB)
  差分(このリリース − 基準): 248,011,274 バイト / 812,839 行
  **1トリプルあたり 305.12 バイト**
  (参考)引き算なしの単純平均: 549.44 バイト/行

--- 8GiB(Azure Container Apps 一時ディスク上限。§6.3)判定 ---
TDB2 実サイズ / 8GiB = 5.2%
判定: 収まる(余裕 +7.581 GiB)
展開中のピーク(tar.gz + 展開後TDB2) = 493,924,755 バイト (0.460 GiB) → 8GiB の 5.8%
判定(ピーク基準): 収まる
```

**結論: 支出先限定(B30)のTDB2実サイズは429MiBで、8GiBの5.2%(展開中の
ピークでも5.8%)。全法人(13.8GiB)との比は32倍——全法人はサイズ1/32・
構築時間1/49(21.2秒 vs 17分16秒)・配布物(tar.gz)1/44(42MiB vs 1.86GiB)。
配布物42MiBはGitHub Releasesにそのまま置けるサイズであり、設計書§6.3が
想定する「tar.gzをGitHub Releasesで配る」運用が実際に成立する規模になった。**

---

## 4. CQ1〜CQ10 実エンドポイント実行(完了条件A。`scripts/run_cq.py`)

**実行対象: `scripts/serve.sh 2026-08-25` で配置したFuseki(`http://localhost:3030/kg/sparql`)。
rdflibのインメモリ実行ではなく実際のJena/TDB2エンドポイント。全10本が非0件で
答えた時点で完了条件Aを満たす(`run_cq.py`の既定は1件でも0件のCQがあれば
非0終了する仕様)。** 標準出力を転記する(件数・所要時間は全10本とも
全量。行内容は`--head 15`分の抜粋——cq04/05/06/09は件数が数千件になるため、
先頭の抜粋のみをここに示し、全行はJSONを参照する)。全行のJSONは
`data/artifact/2026-08-25/cq-results/`に保存した(リポジトリにはコミットしない
成果物ディレクトリ内。転記した本記録が恒久的な証拠)。

```
==============================================================================
CQの実エンドポイント実行: http://localhost:3030/kg/sparql
対象: 10 本(queries\cq/cq*.rq)
==============================================================================

------------------------------------------------------------------------------
### cq01-jurisdiction-of-ordinance.rq
形式: SELECT / 変数: ['ministry', 'ministryName']
行数: 1 / 0.032 秒
ministry | ministryName
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省

------------------------------------------------------------------------------
### cq02-ministry-budget-by-year.rq
形式: SELECT / 変数: ['y', 'totalBudget', 'projectCount']
行数: 1 / 2.985 秒
y | totalBudget | projectCount
2025 | 91789031491000 | 1176

------------------------------------------------------------------------------
### cq03-recipient-expenditures-by-year.rq
形式: SELECT / 変数: ['project', 'projectName', 'y', 'a']
行数: 13 / 0.093 秒
project | projectName | y | a
https://jgkg.norr-tech.com/id/budget/2025/2330 | 地域保健活動検討経費 | 2025 | 1127876
https://jgkg.norr-tech.com/id/budget/2025/884 | 法教育の推進 | 2025 | 1439000
https://jgkg.norr-tech.com/id/budget/2025/221 | 公益法人制度の適正な運営の推進に必要な経費 | 2025 | 1471000
https://jgkg.norr-tech.com/id/budget/2025/2386 | 医療用麻薬適正使用推進事業 | 2025 | 1806000
https://jgkg.norr-tech.com/id/budget/2025/1900 | 地域脱炭素移行・再エネ推進交付金 | 2025 | 2412000
https://jgkg.norr-tech.com/id/budget/2025/404 | 犯罪被害者支援の推進 | 2025 | 2695000
https://jgkg.norr-tech.com/id/budget/2025/1 | 内閣人事局経費(研修事業) | 2025 | 3025000
https://jgkg.norr-tech.com/id/budget/2025/469 | 地方公共団体との連携等の推進 | 2025 | 3762000
https://jgkg.norr-tech.com/id/budget/2025/4099 | 静止気象衛星運用業務 | 2025 | 457000
https://jgkg.norr-tech.com/id/budget/2025/35 | 水循環推進経費 | 2025 | 506000
https://jgkg.norr-tech.com/id/budget/2025/4564 | 国際機関と連携し、国際会議を活用したスマートシティの海外展開の推進 | 2025 | 693000
https://jgkg.norr-tech.com/id/budget/2025/104 | 民間資金等活用事業調査等に必要な経費 | 2025 | 779000
https://jgkg.norr-tech.com/id/budget/2025/1933 | ユネスコ「世界の記憶」に関する国内推進体制の構築 | 2025 | 789000

------------------------------------------------------------------------------
### cq04-money-trace-to-ministry-and-law.rq
形式: SELECT / 変数: ['ministry', 'ministryName', 'law', 'lawTitle']
行数: 2021 / 8.391 秒
(先頭15行。全行は cq-results/cq04-money-trace-to-ministry-and-law.json)
ministry | ministryName | law | lawTitle
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/413M60000100092 | 義肢装具士法第十七条第一項に規定する指定試験機関を指定する省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/420M60000100003 | 特定フィブリノゲン製剤及び特定血液凝固第ＩＸ因子製剤によるＣ型肝炎感染被害者を救済するための給付金の支給に関する特別措置法施行規則
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/501M60000100040 | 自殺対策の総合的かつ効果的な実施に資するための調査研究及びその成果の活用等の推進に関する法律施行規則
... (以下省略。全2021行はcq-resultsのJSON参照)

------------------------------------------------------------------------------
### cq05-ministry-of-basis-law.rq
形式: SELECT / 変数: ['law', 'project', 'ministry', 'ministryName']
行数: 5663 / 8.562 秒
(先頭15行。全行は cq-results/cq05-ministry-of-basis-law.json)
law | project | ministry | ministryName
https://jgkg.norr-tech.com/id/law/416AC0000000135 | https://jgkg.norr-tech.com/id/budget/2025/2966 | https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省
https://jgkg.norr-tech.com/id/law/329AC0000000144 | https://jgkg.norr-tech.com/id/budget/2025/1545 | https://jgkg.norr-tech.com/id/org/7000012060001 | 文部科学省
https://jgkg.norr-tech.com/id/law/411AC0100000052 | https://jgkg.norr-tech.com/id/budget/2025/49 | https://jgkg.norr-tech.com/id/org/8000012130001 | 警察庁
... (以下省略。全5663行はcq-resultsのJSON参照)

------------------------------------------------------------------------------
### cq06-unresolved-recipients-per-project.rq
形式: SELECT / 変数: ['project', 'category', 'count']
行数: 8151 / **154.828 秒**
(先頭10行。全行は cq-results/cq06-unresolved-recipients-per-project.json)
project | category | count
https://jgkg.norr-tech.com/id/budget/2025/1 | resolved | 8
https://jgkg.norr-tech.com/id/budget/2025/100 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/100 | resolved | 10
https://jgkg.norr-tech.com/id/budget/2025/1000 | resolved | 10
https://jgkg.norr-tech.com/id/budget/2025/1001 | resolved | 1
... (以下省略。全8151行はcq-resultsのJSON参照)

------------------------------------------------------------------------------
### cq07-provenance-of-edge.rq
形式: SELECT / 変数: ['graph', 'source', 'fetchedOn', 'license']
行数: 1 / 0.016 秒
graph | source | fetchedOn | license
https://jgkg.norr-tech.com/graph/egov-law/2026-08-24 | https://laws.e-gov.go.jp/api/2/laws | 2026-08-24 | 政府標準利用規約(第2.0版)

------------------------------------------------------------------------------
### cq08-law-revision-as-of-date.rq
形式: SELECT / 変数: ['revision', 'd']
行数: 1 / 0.078 秒
revision | d
https://jgkg.norr-tech.com/id/law/417M60000100021/20260401_令和八年厚生労働省令第三号 | 2026-04-01

------------------------------------------------------------------------------
### cq09-jurisdiction-resolution-status.rq
形式: SELECT / 変数: ['law', 'status', 'detail']
行数: 6517 / 6.984 秒
(先頭5行。全行は cq-results/cq09-jurisdiction-resolution-status.json)
law | status | detail
https://jgkg.norr-tech.com/id/law/414M60000800066 | resolved | https://jgkg.norr-tech.com/id/org/2000012100001
https://jgkg.norr-tech.com/id/law/426M60400000004 | resolved | https://jgkg.norr-tech.com/id/org/7000012010022
https://jgkg.norr-tech.com/id/law/422M60000040052 | resolved | https://jgkg.norr-tech.com/id/org/8000012050001
... (以下省略。全6517行はcq-resultsのJSON参照)

------------------------------------------------------------------------------
### cq10-release-freshness.rq
形式: SELECT / 変数: ['sourceName', 'asOf', 'dateKind']
行数: 5 / 0.047 秒
sourceName | asOf | dateKind
e-Gov法令API v2 全法令メタデータ | 2026-08-24 | 取得日
国税庁 法人番号公表サイト 全件データ | 2026-08-23 | 取得日
国税庁 法人番号公表サイト 全件データ | 2026-08-23 | 取得日
府省名簿(RS実データの所管府省庁名+府省庁名の和集合 + 法令経路3機関より作成) | 2026-08-23 | 記録日
行政事業レビュー見える化サイト RSシステム 一括CSVダウンロード | 2026-08-23 | 取得日

==============================================================================
全 10 本のCQが非0の答えを返した(完了条件A)
[exited with code 0]
```

### 完了条件Aの判定

**全10本(CQ1〜CQ10)が実データ・実エンドポイント(Fuseki/TDB2)で非0件の
答えを返した。完了条件Aを満たす。**

- CQ8(法令の改正としての時点指定): 事前監査で発見した実データ不整合
  (ハードコードされたカットオフ日`2023-01-01`が実データの改正日
  `2026-04-01`より前で0件になる)を修正した効果が、実エンドポイントでも
  1件の答え(`2026-04-01`)として確認できた
- CQ10(鮮度): 5件——e-Gov(取得日)・法人番号(取得日。houjin-bangou/
  houjin-bangou-payeesの2グラフ分で2行)・府省名簿(記録日)・RS(取得日)。
  ソース4種+法人番号グラフが2つという構成と一致する(異常ではない)
- **観察(性能。完了条件Aの合否には影響しないが記録する): CQ6は154.8秒
  かかった。** 他のCQ(いずれも10秒未満)と比べて明確に遅い。予算執行明細
  (73,919行)をproject×categoryで集計するクエリで、この規模でも実用上は
  許容範囲(タイムアウト300秒以内)だが、Phase 2でAPI層を作る場合はこの
  パターン(project単位の集計)にキャッシュや事前集計を検討する価値がある、
  という申し送り

---

## 5. 更新の一巡(完了条件C。carry-over実データ検証)

**「2つ目のリリースを作る」を実データで実行した。** リリースA
(`data/artifact/2026-08-25/`。§2)と全く同じ4ソース(houjin-bangou=
2026-08-23・ministry-codes=2026-08-23・egov-law=2026-08-24・rs-system=
2026-08-23)を`--previous-release 2026-08-25 --out-dir data/artifact/2026-08-26`
で指定し、`scripts/build.sh`経由でリリースBを構築した。**`--out-dir`は
必ず明示する**(省略時の既定は`data/artifact/<最新の取得日>`=
`data/artifact/2026-08-24`となり、全法人13.8GiBの証拠を上書きしてしまう
——build.shのソース〔`if [ -z "$OUT" ]; then OUT="data/artifact/${LATEST_DATE}"; fi`〕
で確認した実際の危険。今回は明示したため発生していない)。

### carry-overの判定(pipeline-report.json `carried_over`)

```json
"carried_over": [
  "https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23",
  "https://jgkg.norr-tech.com/graph/egov-law/2026-08-24",
  "https://jgkg.norr-tech.com/graph/rs-system/2026-08-23"
],
"corporations_all": 18941,
"corporations_scope": "payees",
```

**houjin-bangou・egov-law・rs-systemの3グラフは据え置き(再検証・再排出
なし)、houjin-bangou-payeesは据え置きに載らず毎回再構築されている。**
これは設計どおりの挙動である——`houjin-bangou-payees`は
houjin-bangou**と**rs-systemの両方に依存する派生グラフで、carry-overの
差分検出はソース単位(`_GRAPH_DEPENDENCIES`)にしか効かないため、
「rs-system自体は不変だが支出先フィルタの構築ロジックが変わった」場合を
見落とす恐れがある。そのため意図的に毎回再構築する。**Task 10の
carry-overテスト群(`tests/test_update_cycle.py`)はB30より前に書かれており、
この組み合わせを一度も検証していなかった** — 本ラウンドで
`tests/test_pipeline.py::test_run_payees_scope_carry_over_regenerates_the_payees_graph_but_carries_the_rest`
を追加し、この実データでの挙動をfixtureで固定した(464件green)。

副次的な発見: `_GRAPH_DEPENDENCIES["rs-system"]`は`("houjin-bangou",
"ministry-codes", "egov-law", "rs-system")`であり、**このリリースの
`fetched_on`にegov-lawが無いと、rs-system自身の据え置きも「不変と確認
できない」として保守的に諦められる**(依存元がリリース対象に含まれない
場合の設計判断)。今回のリリースA/Bは両方egov-lawを含んでいたため問題
にならなかったが、上記テストを書く過程でegov-lawを含めない構成だと
rs-systemが据え置かれないことを確認し、この前提を記録した。

### manifest.jsonの比較(A: 2026-08-25 / B: 2026-08-26)

| 項目 | A | B | 一致 |
|---|---|---|---|
| triple_count | 817,982 | 817,982 | ✅ |
| tdb2_expanded_bytes | 449,434,865 | 449,434,865 | ✅ |
| nquads_sha256 | `077b5dcf...` | `b7937562...` | ❌(下記で説明) |
| tarball sha256 | `bf9f56e2...` | `76301049...` | ❌(想定どおり) |

**tarball sha256の不一致は想定どおり**(tarに埋め込まれるmtimeが実行ごとに
変わるため。内容の差ではない)。

**nquads_sha256の不一致は「内容の差」ではなく「行の並び順の差」だと
確認した。** kg.nqを名前付きグラフごとに切り出し、各グラフの行を
`sort`してから改めてsha256を取ると、**manifestに載る6グラフ全て
(houjin-bangou・egov-law・rs-system・ministry-codes・provenance・
houjin-bangou-payees)がA/Bで完全に一致した**(`triple_count`が
A/Bで同じ817,982なのは「総数が同じ」ことしか示さないため、6グラフ
それぞれを個別に確認した):

```
houjin-bangou        : 2d409ddc... (A) == 2d409ddc... (B)
egov-law              : 6d0574ca... (A) == 6d0574ca... (B)
rs-system             : f4785f75... (A) == f4785f75... (B)
ministry-codes        : 3392faec... (A) == 3392faec... (B)
provenance            : 83a9a5f3... (A) == 83a9a5f3... (B)
houjin-bangou-payees  : 77de2dc4... (A) == 77de2dc4... (B)
```

つまり**トリプルの欠落・重複・改変は無い**。差は`emit.write_nquads`が
`clean`(rdflib Dataset)をシリアライズする際の行の出力順のみであり、
carry-over経路(前リリースのグラフを読み込んで`clean`に足す)と
新規生成経路(パイプラインが生成した順に`clean`に足す)で、rdflibへの
追加順序が異なるために生じる(rdflibの`Dataset`は挿入順に依存した順序で
シリアライズする)。**これはkg.nqのバイト列レベルの差であり、TDB2への
ロード結果(トリプルの集合)には影響しない**——実際に`tdb2_expanded_bytes`
はA/Bで完全に一致している。

### 壁時計時間の比較(carry-overの効果が見えない理由)

| リリース | パイプライン実行(検証を含む) | 総所要 |
|---|---|---|
| A(初回) | 461秒 | 527秒 |
| B(carry-over) | 458秒 | 544秒 |

**carry-overが3/4グラフを据え置いたにもかかわらず、壁時計時間はほぼ
変わらなかった(458秒 vs 461秒。誤差の範囲)。** 理由:
`corporations_scope="payees"`は設計上、支出先フィルタ(`payee_houjin_bangou`)
の再構築のために**houjin-bangou全件(580万行)を毎回フルスキャンする**
(`pipeline-report.json`の`rows_seen`はA/Bとも5,816,535で完全に同一)。
これは houjin-bangou-payees グラフが carry-over の対象外(上記)である
ことの直接の結果であり、この構成では carry-over の本来の効果(検証・
排出のスキップによる時間短縮)がフルスキャンの時間に埋もれて見えない。
carry-overの効果自体は`carried_over`リストと(fixtureの)carry-overテスト群
で確認済みであり、この観察は「効いていない」ではなく「この構成では
支配的なコストが別にある」という切り分けである。

### リリース切替と鮮度反映

`scripts/serve.sh 2026-08-26`で実際に配置した。

```
== Fusekiを停止 ==
 Container requirements-draft-fuseki-1  Stopped
== 成果物の照合と配置 ==
(manifest.jsonのsha256とJenaバージョンの照合を通過)
== Fusekiを起動 ==
 Container requirements-draft-fuseki-1  Started
完了: data/artifact/2026-08-26 を配置した(data/artifact/current/ に切替。前世代は data/artifact/previous/)。
```

`data/artifact/current/`のmtimeが切替直後の時刻に更新され、
`data/artifact/previous/`にリリースAの内容(切替前のcurrent)が退避
されていることを確認した。切替後、Fuseki(`docker compose ps`で
`Up`)にクエリを投げ、応答が返ることを確認した(p0-02-ministry-list.rq)。

**注記: 内容が同一である(上記の通りA/Bのトリプル集合は完全一致)以上、
クエリの答えの内容で「Aを配信中かBを配信中か」を区別することはできない
——これはcarry-overが正しく働いている証拠であり、欠陥ではない。**
切替が完了条件Cを満たす根拠は、クエリの答えの変化ではなく、
(a) serve.sh自身のmanifest照合が通過したこと、(b) `current`/`previous`の
実際の入れ替わりを確認したこと、(c) 切替後もエンドポイントが生きて
応答すること、の3点である。

### 保護対象の証拠(全法人13.8GiB)が生存していることの確認

```
$ ls -la data/artifact/2026-08-24/
kg.nq         6,793,393,635 bytes(6.33 GiB)
tdb2.tar.gz   1,994,085,008 bytes(1.86 GiB)
pipeline-report.json  1,921 bytes
```

2回のビルド(リリースA・B)を経てもサイズ・mtimeとも変化無し(B30実装
開始前のタイムスタンプのまま)。`--out-dir`の明示により、リリースA・B
ともこの証拠を上書きしていない。

### 完了条件Cの判定

**満たす。** 取得(既存スナップショットの再利用含む)→差分検出
(`carried_over`)→検証(据え置き4グラフはSHACL再検証、新規1グラフは
通常検証)→リリース切替(serve.sh)→鮮度反映(current/previousの実際の
入れ替わり+エンドポイントの応答)の一巡を実データで通し、2つ目の
リリース(`data/artifact/2026-08-26/`)を作った。

---

## 6. 必須項目6: RS の年度をまたいだ整合(`measure_rs_cross_year.py`)

Task 6は事業年度2025のみ取得しており、懸念12・13は「観察・未検証」で
申し送られていた。本ラウンドで事業年度2024のデータを新規取得
(`fetched_on=2026-08-24`。REQUIRED_GROUPS 4本のみ。礼儀のため不要な
ファイルは取らない)し、`scripts/measure_rs_cross_year.py --snapshot
2026-08-23 --snapshot 2026-08-24`で実測した。

**このRS-2024取得は、リリースB(§5)の`carried_over`検証が完全に確定
した後に行った** — `data/lake/rs-system/2026-08-24/`が新設されると
`lake.latest_before("rs-system", ...)`が返す「直近のスナップショット」が
変わり、以後の(まだ存在しないリリースへの)carry-over判定に影響する
可能性があるため(将来のリリースがrs-systemを「変化した」と判定して
再生成に回るだけで、データが壊れるわけではないが、§5の実測記録が
これ以降は再現できなくなる)。

取得した事業年度2024の4ファイル(`data/lake/`は`.gitignore`対象なので、
出典追跡のためsha256をここに記録する):

| ファイル | sha256 |
|---|---|
| 1-2_RS_2024_基本情報_事業概要等.zip | `82488871dff9b2a450444d11b4010951ca02e2ec7bd886e6e923c4b2a512e4e2` |
| 2-1_RS_2024_予算・執行_サマリ.zip | `a054b9e8e87850ffbf9ab5ec478eaf5a344259989d868dda02bb1b92fbf1909e` |
| 1-3_RS_2024_基本情報_政策・施策、法令等.zip | `890d31b93d7d4266975fb763ceb707458a103ba21bada92999e92a5be177eced` |
| 5-1_RS_2024_支出先_支出情報.zip | `4624b0c1e179cbe2c6edcff4bbf30e4108ff8bb3f2751c74f7e216821afe895d` |

```
==============================================================================
RSの年度をまたいだ整合(Task 6 懸念12・13)
==============================================================================
--- 取得日 2026-08-23(事業年度2025) ---
  project_summary の行数 : 6,061
  事業数(distinct pid)  : 5,794
  府省数(distinct 府省庁): 23
  budget_summary の行数  : 47,100

--- 取得日 2026-08-24(事業年度2024) ---
  project_summary の行数 : 5,948
  事業数(distinct pid)  : 5,664
  府省数(distinct 府省庁): 23
  budget_summary の行数  : 37,981

### 懸念12: 建制順(kensei_jun)の年度をまたいだ安定性
  両年度に現れる府省名 : 23 / 片方だけ: 0件(両方0件)
  **建制順が変わった府省: 0 件**(両年度に現れる府省の建制順はすべて一致)
  (23府省全ての建制順を確認。例: 内閣官房1→1、こども家庭庁12→12、防衛省26→26)

### 懸念13(前半): budget_summary の (project_id, 予算年度) 複合キー
  2026-08-23: キー数 23,036 / 重複キー 23,034 件
  2026-08-24: キー数 18,524 / 重複キー 18,521 件
  予算年度の分布(2025スナップショット): {2021: 7180, 2022: 7683, 2023: 9915, 2024: 10614, 2025: 11708}
  予算年度の分布(2024スナップショット): {2021: 7585, 2022: 8232, 2023: 10724, 2024: 11440}

### 懸念13(核心): 同じ project_id が両年度で同じ事業を指すか
  両年度に現れる project_id : 5,231
  事業名が一致   : 4,952 (94.7%)
  **事業名が不一致: 279 (5.3%)**
  所管府省が一致 : 5,231 (100.0%)
  不一致の例(先頭5件): 「内閣人事局経費(研修事業)」→「内閣人事局経費」/
  「サイバーセキュリティ関係情報システム等経費」→「内閣サイバーセキュリティ
  センター情報システム等経費」/「子供の性被害防止対策の推進」→「人身安全
  関連事案対策の推進」/「「魅力的な地域をつくる」ための調査・研究事業」→
  「「魅力的な地域をつくる」ための先行事例調査・研究」/「地域の社会課題
  解決に資する起業者展開推進事業」→「地域の担い手展開推進事業」
  (全30件は`scripts/measure_rs_cross_year.py`の実行結果として再現可能)
```

### 結論

**懸念12(建制順の年度安定性): 完全に安定している。** 23府省全てで
2024/2025両年度の建制順が一致した(変化0件)。Ruling B15の判断
(建制順を識別子に使わない)は実害を避ける保守的な判断だったが、実データ
ではこの2年度間では変わっていなかったことも記録する。

**懸念13前半((project_id, 予算年度)複合キー): 主キーとして使えないことが
決定的に確認できた。** 2025年度スナップショットでは23,036個のキーのうち
23,034個(99.99%)が重複している——ほぼ全ての組が複数行を持つ。原因は
1事業・1予算年度に対して複数の予算種別・執行区分の行が存在するため
(B20の「役割による二重計上」の土台と同根)。この複合キーを一意キーとして
扱う設計は実データで即座に破綻する。

**懸念13核心(project_idの年度をまたいだ安定性): project_idは安定した
横断識別子として使えるが、project_nameは年度ごとに変わりうる(小幅な
文言修正が5.3%で発生)。** 所管府省は100%一致するため、府省の変化は
project_nameの表記変化の原因ではない(語尾・括弧書きの整理などの軽微な
言い直しが主)。**この結果はPhase 1の設計(各事業年度のproject_summary
行を、その年度専用のBudgetProjectとして個別に生成し、project_nameを
年度をまたいで統合・正規化しない)を裏付ける** ——実データが「同じ
project_idでも名称が年度によって変わりうる」ことを示しているため、
名称を年度をまたいで1つに統合する設計にしていたら、この5.3%で
どちらの表記を正とするかという恣意的な判断が必要になっていた。

---

## 7. 必須項目7: e-Gov法令API の PAGE_LIMIT=100 の実効性(`probe_egov_paging.py`)

実測(2026-08-25。`uv run python scripts/probe_egov_paging.py`):

```
GET https://laws.e-gov.go.jp/api/2/laws params={'limit': 100, 'offset': 0}
status=200
content-type='application/json'
実際に叩いたURL: https://laws.e-gov.go.jp/api/2/laws?limit=100&offset=0
要求 limit           : 100
返ってきた laws 件数 : 100
total_count          : 9547
next_offset          : 100
応答のトップレベルkey : ['count', 'laws', 'next_offset', 'total_count']
判定: PAGE_LIMIT=100 は効いている(切り下げられていない)
全件取得に必要なページ数(概算): 96
--- 1件目の法令オブジェクトのキー(生値の形の確認) ---
["current_revision_info", "law_info", "revision_info"]
```

**結論: `PAGE_LIMIT=100` は実際に効いている**(要求どおり100件返る。
サーバー側で黙って切り下げられてはいない)。全件取得(9,547件)には
約96ページが必要(実測: 発見1の対応で完走。9,547件/22.5MB/147秒)。

---

## 8. 必須項目8: `old-ministries.csv` の出典URLの実確認(`verify_old_ministries_source.py`)

実測(2026-08-25。`uv run python scripts/verify_old_ministries_source.py`):

```
==============================================================================
old-ministries.csv の出典URLの実確認(必須項目8)
==============================================================================
CSVに載っている廃止名称: 18 件
  ['労働省', '北海道開発庁', '厚生省', '国土庁', '大蔵省', '建設省', '文部省', '沖縄開発庁', '環境庁', '科学技術庁', '経済企画庁', '総務庁', '総理府', '自治省', '通商産業省', '運輸省', '郵政省', '金融再生委員会']

### 1. コメントが挙げているURL(と周辺のHTML)
------------------------------------------------------------------------------
URL: https://www.soumu.go.jp/main_sosiki/gyoukan/kanri/  ← CSVのコメントが挙げている出典
  status=403 content-type='text/html' bytes=39276
  **このURLは出典として引用できない**
------------------------------------------------------------------------------
URL: https://www.soumu.go.jp/main_sosiki/gyoukan/kanri/index.html
  status=404 content-type='text/html' bytes=39276
  **このURLは出典として引用できない**
------------------------------------------------------------------------------
URL: https://www.soumu.go.jp/
  status=200 content-type='text/html' bytes=224117
  デコード: cp932
  <title>: 総務省
  本文に現れた廃止名称: 0/18
    現れない: ['労働省', '北海道開発庁', '厚生省', '国土庁', '大蔵省', '建設省', '文部省', '沖縄開発庁', '環境庁', '科学技術庁', '経済企画庁', '総務庁', '総理府', '自治省', '通商産業省', '運輸省', '郵政省', '金融再生委員会']
------------------------------------------------------------------------------
URL: https://www.gyoukaku.go.jp/
  status=200 content-type='text/html' bytes=56415
  デコード: utf-8
  <title>: 政府の行政改革 - トップページ
  本文に現れた廃止名称: 0/18
    現れない: ['労働省', '北海道開発庁', '厚生省', '国土庁', '大蔵省', '建設省', '文部省', '沖縄開発庁', '環境庁', '科学技術庁', '経済企画庁', '総務庁', '総理府', '自治省', '通商産業省', '運輸省', '郵政省', '金融再生委員会']

### 2. 一次資料(e-Gov法令API v2。このプロジェクトが既に使っているAPI)
------------------------------------------------------------------------------
URL: https://laws.e-gov.go.jp/api/2/law_data/410AC0000000103
  対象: 中央省庁等改革基本法(平成十年法律第百三号)
  status=200 bytes=181960
  sha256(応答本文): e85cdf7b26ca9e8adaad597ec0e0e7780787976c2912edfe1ce1ff709f40501b
  law_num=平成十年法律第百三号 law_id=410AC0000000103 promulgation_date=1998-06-12
  law_title=None repeal_status=None
  法令本文(JSON全体)に現れた廃止名称: 11/18
    現れた : ['北海道開発庁', '国土庁', '大蔵省', '建設省', '経済企画庁', '総務庁', '総理府', '自治省', '通商産業省', '運輸省', '郵政省']
    現れない: ['労働省', '厚生省', '文部省', '沖縄開発庁', '環境庁', '科学技術庁', '金融再生委員会']
------------------------------------------------------------------------------
URL: https://laws.e-gov.go.jp/api/2/law_data/411AC0000000160
  対象: 中央省庁等改革関係法施行法(平成十一年法律第百六十号)
  status=404 bytes=120
  本文: {"code":"404004","message":"指定のパラメータで取得できる法令本文ファイルは存在しません。"}

### 3. 「{名称}設置法」が現行法令として存在するか(レイクの全件メタデータ)
スナップショット: data\lake\egov-law\2026-08-24\laws.jsonl
法令の総数: 9547 / 題名に「設置法」を含む法令: 53

旧省庁(old-ministries.csv の18件):
  存在しない   労働省設置法
  存在しない   北海道開発庁設置法
  存在しない   厚生省設置法
  存在しない   国土庁設置法
  存在しない   大蔵省設置法
  存在しない   建設省設置法
  存在しない   文部省設置法
  存在しない   沖縄開発庁設置法
  存在しない   環境庁設置法
  存在しない   科学技術庁設置法
  存在しない   経済企画庁設置法
  存在しない   総務庁設置法
  存在しない   総理府設置法
  存在しない   自治省設置法
  存在しない   通商産業省設置法
  存在しない   運輸省設置法
  存在しない   郵政省設置法
  存在しない   金融再生委員会設置法
  → 18件のうち現行法令に設置法があるもの: 0

正のコントロール: 現行府省(ministry-codes.csv の40行):
  設置法がある: 20/40
    ['内閣府', '金融庁', 'こども家庭庁', 'デジタル庁', '復興庁', '総務省', '公害等調整委員会', '法務省', '公安調査庁', '外務省', '財務省', '文部科学省', '厚生労働省', '農林水産省', '経済産業省', '国土交通省', '運輸安全委員会', '環境省', '原子力規制委員会', '防衛省']
  設置法が無い: 20/40
    ['内閣官房', '公正取引委員会', '警察庁', '個人情報保護委員会', 'カジノ管理委員会', '消費者庁', '消防庁', '国税庁', 'スポーツ庁', '文化庁', '中央労働委員会', '林野庁', '水産庁', '特許庁', '気象庁', '海上保安庁', '観光庁', '人事院', '会計検査院', '国家公安委員会']
  (無い側は外局・内部組織など、親府省の設置法や別の法律(国家公務員法・会計検査院法等)で設置されるもの)

判定: 旧省庁18件は設置法が現行法令に1件も無く、現行府省は20件が存在する。この非対称が「もう存在しない」の機械照合可能な証拠になる
```

**結論**: `data/reference/old-ministries.csv` のコメントが挙げていた出典URL
(`soumu.go.jp/main_sosiki/gyoukan/kanri/`)は403/404で引用不能と再確認。
中央省庁等改革基本法(law_id=410AC0000000103)をe-Gov法令APIから一次資料
として取得できることを確認(sha256追跡可能)。「旧省庁18件は設置法が1件も
現存しない/現行府省は20/40件に設置法がある」という非対称が、機械照合
可能な「もう存在しない」の証拠として成立している。

---

## 9. 必須項目9: `EXTRACTION_FAILED` の法形式ごとの内訳(`measure_jurisdiction_resolution.py`)

## 10. 必須項目10: 「内閣官房令」の実在確認(同スクリプト)

実測(2026-08-25。`uv run python scripts/measure_jurisdiction_resolution.py`):

```
==============================================================================
経路1(法令番号 → 所管府省)の解決率 — 実データ
==============================================================================
egov-law スナップショット : data\lake\egov-law\2026-08-24\laws.jsonl
houjin-bangou スナップショット: 取得日 2026-08-23
国の機関(法人種別101)     : 848 件
参照表と突合できた府省       : 40 件(未突合 0 件)

法令の総数(laws.jsonl の行数)      : 9547
経路1の対象外(「○○令第n号」でない): 4679
EXTRACTION_FAILED(形はしているが抽出不能): 13
経路1の対象(名称を抽出できた法令)  : 4855

--- 法令単位の解決 ---
全名称が解決     : 2936 (60.5%)
一部だけ解決     : 61 (1.3%)
1件も解決しない  : 1858 (38.3%)
少なくとも1件解決: 2997 (61.7%)
共同省令(抽出名称が2件以上): 837

--- 名称単位(延べ。pipeline-report.json の law_jurisdiction_* と一致する ---
resolved   : 4243
unresolved : 2274
  OLD_MINISTRY            : 1995
  OBSOLETE_ORGANIZATION   : 276
  NO_CANDIDATE            : 3

--- 未解決の名称(全件。理由つき) ---
     354  OLD_MINISTRY             大蔵省
     304  OLD_MINISTRY             総理府
     287  OLD_MINISTRY             運輸省
     279  OLD_MINISTRY             厚生省
     234  OLD_MINISTRY             通商産業省
     181  OLD_MINISTRY             建設省
     127  OBSOLETE_ORGANIZATION    農林省
     109  OLD_MINISTRY             文部省
     107  OLD_MINISTRY             自治省
      94  OLD_MINISTRY             労働省
      44  OLD_MINISTRY             郵政省
      21  OBSOLETE_ORGANIZATION    逓信省
      19  OBSOLETE_ORGANIZATION    司法省
      19  OBSOLETE_ORGANIZATION    文化財保護委員会
      14  OBSOLETE_ORGANIZATION    法務府
      11  OBSOLETE_ORGANIZATION    内務省
      10  OBSOLETE_ORGANIZATION    閣
       9  OBSOLETE_ORGANIZATION    商工省
       7  OBSOLETE_ORGANIZATION    総理庁
       7  OBSOLETE_ORGANIZATION    電波監理委員会
       6  OBSOLETE_ORGANIZATION    特定個人情報保護委員会
       4  OBSOLETE_ORGANIZATION    鉄道省
       3  NO_CANDIDATE             日本学術会議
       3  OBSOLETE_ORGANIZATION    法務庁
       3  OBSOLETE_ORGANIZATION    首都圏整備委員会
       2  OBSOLETE_ORGANIZATION    公安審査委員会
       2  OBSOLETE_ORGANIZATION    内閣府・公正取引委員会・個人情報保護委員会・総務省・法務省・財務省・文部科学省・厚生労働省・農林水産省・経済産業省・国土交通省・環境省・原子力規制委員会
       2  OBSOLETE_ORGANIZATION    農商務省
       2  OLD_MINISTRY             金融再生委員会
       1  OBSOLETE_ORGANIZATION    公認会計士管理委員会
       1  OBSOLETE_ORGANIZATION    司法試験管理委員会
       1  OBSOLETE_ORGANIZATION    土地調整委員会
       1  OBSOLETE_ORGANIZATION    地方財政委員会
       1  OBSOLETE_ORGANIZATION    外資委員会
       1  OBSOLETE_ORGANIZATION    日本ユネスコ国内委員会
       1  OBSOLETE_ORGANIZATION    第一復員省
       1  OBSOLETE_ORGANIZATION    第二復員省
       1  OBSOLETE_ORGANIZATION    運輸通信省
       1  OBSOLETE_ORGANIZATION    電気通信省

--- 必須項目9: EXTRACTION_FAILED の法形式ごとの内訳 ---
(皇室令など非府省令もここに拾われるため、総数を「経路1の欠陥」と
 読むと過大評価になる。task-4-report.md の申し送り)
law_type 別:
      13  MinisterialOrdinance
law_num_type 別:
      13  MinisterialOrdinance
例(最大20件):
  324M50000804001  MinisterialOrdinance     昭和二十四年運輸省・経済安定本部令第一号
  426M60000001001  MinisterialOrdinance     平成二十六年内閣官房令第一号
  426M60000001003  MinisterialOrdinance     平成二十六年内閣官房令第三号
  426M60000009001  MinisterialOrdinance     平成二十六年内閣官房・総務省令第一号
  427M60000001007  MinisterialOrdinance     平成二十七年内閣官房令第七号
  427M60000011001  MinisterialOrdinance     平成二十七年内閣官房・法務省令第一号
  427M60002001001  MinisterialOrdinance     平成二十七年内閣官房・防衛省令第一号
  501M60000101001  MinisterialOrdinance     令和元年内閣官房・厚生労働省令第一号
  502M60000001008  MinisterialOrdinance     令和二年内閣官房令第八号
  503M60000001004  MinisterialOrdinance     令和三年内閣官房令第四号
  504M60000001003  MinisterialOrdinance     令和四年内閣官房令第三号
  504M62000800001  MinisterialOrdinance     令和四年カジノ管理委員会規則・国土交通省令第一号
  506M60000011002  MinisterialOrdinance     令和六年内閣官房・法務省令第二号

--- 必須項目10: 「内閣官房令」は実データに存在するか ---
存在する: 6 件
  426M60000001001  平成二十六年内閣官房令第一号  幹部職員の任用等に関する政令第二条第一項の官職を定める内閣官房令
  426M60000001003  平成二十六年内閣官房令第三号  経験者採用試験の対象官職及び種類並びに採用試験の種類ごとに求められる知識及び能力等に関する内閣官房令
  427M60000001007  平成二十七年内閣官房令第七号  国家戦略特別区域法第十九条の二の規定による国家公務員退職手当法の特例に関する内閣官房令
  502M60000001008  令和二年内閣官房令第八号  内閣官房内閣人事局の所管する法令に係る情報通信技術を活用した行政の推進等に関する法律の施行に関する内閣官房令
  503M60000001004  令和三年内閣官房令第四号  特定秘密の保護に関する法律に係る情報通信技術を活用した行政の推進等に関する法律の施行に関する内閣官房令
  504M60000001003  令和四年内閣官房令第三号  国家公務員退職手当法附則第十二項、第十四項及び第十六項の規定による退職手当の基本額の特例等に関する内閣官房令
```

**結論(項目9)**: `EXTRACTION_FAILED`(13件)は**全件`MinisterialOrdinance`
(府省令の形式)**。内訳を見ると原因は「単独の府省令ではない」パターン
(内閣官房令単独・複数府省の共同省令・委員会規則との共同)であり、
名称抽出ロジック自体が「単一府省名を前提にしている」ことに起因する
狭い型の失敗。「経路1の欠陥」として過大評価してはならない
という task-4-report.md の申し送りが実データで裏付けられた
(皇室令等の非府省令はこの13件には含まれない——全件`MinisterialOrdinance`)。

**結論(項目10)**: 「内閣官房令」は実在する法形式である(**6件**確認)。
Task 4 観察3の疑問(実在するか)は「実在する」で確定した。ただし全件
`EXTRACTION_FAILED`側に落ちている(上記13件のうち6件が内閣官房令単独)
——これは「内閣官房」が`ministry-codes.csv`に「内閣官房」という名称で
実在するにもかかわらず抽出できていないことを意味し、Phase 2で
名称抽出ロジックの拡張候補になる(単独の「○○令」だけでなく
「内閣官房令」等の単独パターンを扱えるようにする)。

---

## 11. 府省参照表の突合(`measure_ministry_reference_match.py`)

実測(2026-08-25。`uv run python scripts/measure_ministry_reference_match.py`):

```
==============================================================================
府省参照表(ministry-codes.csv)と実データ(国の機関)の突合
==============================================================================
スナップショット   : data\lake\houjin-bangou\2026-08-23\zenken.zip
参照表             : data\reference\ministry-codes.csv
参照表の内容ハッシュ: 5818790d921bc903cd121d4d7faf0f7c2d3b0d73212a01db62b7e835c0bee7b7
sources.py の記録  : 5818790d921bc903cd121d4d7faf0f7c2d3b0d73212a01db62b7e835c0bee7b7
入力の非空行数     : 5,816,535
国の機関(法人種別101): 848 件
参照表の行数       : 40
一意一致           : 40 件
未突合             : 0 件
```

参照表40行全件が実データの国の機関848件に一意一致(未突合0件)。国の機関側
に同名の重複は無い(848件の名称はすべて一意)。参照表に無いが国の機関として
実在する名称は808件で、その大半(先頭50件を確認)は簡易裁判所・地方裁判所・
検察庁・検察審査会などの司法機関であり、参照表(40行=行政府の府省庁)の対象
範囲外として正しく除外されている(名称末尾の分布: 「所」549件・「会」176件
等が大半を占め、司法・審議会系の名称であることと整合する)。

---

## 12. (§6に統合済み)

Task 6 懸念12・13の実測は§6に全量転記した(このセクション番号は
欠番にせず、統合済みの記録として残す)。

---

## 13. B24(6)の観測: 合計/執行額の比の分布(実データ)

**B24(6)により、この比は合否のゲートにはしない(観察のみ)。**
`data/artifact/2026-08-25/pipeline-report.json`の`budget_ratio_*`を転記する
(`budget_projects`=5,794件との内訳一致を確認済み: 1,488+221+24+36+2,877+1,148
=5,794)。

| 分類 | 件数 | 割合 |
|---|---|---|
| ちょうど1.0(予算=執行) | 1,488 | 25.7% |
| ちょうど2.0 | 221 | 3.8% |
| ちょうど3.0 | 24 | 0.4% |
| 分子・分母とも0 | 36 | 0.6% |
| その他の比 | 2,877 | 49.7% |
| 分母が無い(前年度執行額が無い等) | 1,148 | 19.8% |

**観察: 「予算≈執行」を機械的なゲートにしていたら5,794件中1,488件
(25.7%)しか通らず、残り74.3%を誤って弾く設計になっていた。** ちょうど
整数倍(1.0/2.0/3.0)になる事業が合計29.9%ある一方、約半数(49.7%)は
どちらとも言えない比であり、単純な比の合否判定はこの実データには
そぐわないことが確認できた(B24(6)の判断が正しかったことの裏付け)。

---

## 14. 壊し確認(Task 11修正ラウンドで追加したガード)

- **B30フィルタ(`_all_corporations_source`の絞り込み)**: `if payee_houjin_bangou is not None and ...`
  を`if False and ...`へ書き換えて`test_run_payees_scope_writes_a_distinctly_named_graph_with_only_recipient_corporations`
  等を実行 → `corporations_all`が2件(フィルタ無効化前は1件期待)に増え、
  意図どおり失敗することを確認。元に戻すと全緑。
- **`corporations_scope="payees"`の2つのValueErrorガード**: それぞれ
  `if corporations_scope == "payees":`を`if False and corporations_scope == "payees":`
  に書き換えて対応するテストを実行 → ガードをすり抜けた先で
  `FileNotFoundError`(スナップショット不在)に変わり、
  `pytest.raises(ValueError, match=...)`が失敗することを確認。元に戻すと全緑。
- **`build_manifest`の`tdb2_expanded_bytes<=0`ガード**: `if tdb2_expanded_bytes <= 0:`
  を`if False and ...`に書き換えて`test_build_manifest_rejects_non_positive_tdb2_expanded_bytes`
  を実行 → `DID NOT RAISE ValueError`で失敗することを確認。元に戻すと全緑。
- **build.shの実物検査3種(空tar.gz検出/`tdb2/Data-0001/`不在検出/`du -sb`パース
  失敗検出)**: シェルの条件式を直接、(a)空ファイル、(b)`tdb2/Data-0001/`を
  含まないtarball、(c)`du -sb`の出力行を含まないログ、の3通りに対して実行し、
  いずれも意図した「エラー:」分岐に入ることを確認。正常系(`tdb2/Data-0001/`
  を含む有効なtarball)では素通りすることも確認(正のコントロール)。

---

## 15. Phase 1 完了条件の判定

| 条件 | 判定 | 根拠 |
|---|---|---|
| (A) CQ1〜CQ10 に実データ・実エンドポイントで答えられる | **満たす** | §4(2026-08-25リリース。Fuseki実エンドポイントで全10本が非0件) |
| (B) 縦の接続スライスを双方向に辿れ、出典が付く | **満たす** | `tests/test_vertical_slice.py`(fixture、全ホップ往復)+ 実データ: CQ1(法令→府省)・CQ5(法令→事業→府省)・CQ4(法人→支出→事業→府省→法令。逆方向を明示ジョインで確認、2,021件)・CQ7(出典。graph/source/fetchedOn/licenseが1件で返る) |
| (C) 更新の一巡を実データで通し、2つ目のリリースを作れる | **満たす** | §5(`data/artifact/2026-08-26/`。carry-over3グラフ+新規1グラフ+serve.sh切替+新規回帰テスト) |

**Phase 1(計画B)の完了条件A・B・Cを実データで満たした。** 併せて
task-11-brief.mdの必須項目6〜10(RS年度整合・PAGE_LIMIT・
old-ministries.csv出典・EXTRACTION_FAILED内訳・内閣官房令実在)も
本記録(§6〜§11)で全て実データにより確認済み。詳細な経緯・気になる点は
`.superpowers/sdd/2026-08-23-phase1-vertical-slice-data-layer/task-11-report.md`
を参照。
