# Phase 1 実測記録

最終更新: 2026-08-25

**裁定B25(測定は使い捨てにしない)に従う。** 数字の出典はすべて `scripts/` に
コミットされたスクリプトであり、ここには**その出力を全量転記する**(要約・
再計算はしない)。この計画で「再導出できない数値」由来の訂正が複数回起きた
ため、この記録自体が再現可能性の担保になる。**この宣言をliterallyに守る
(裁定B32)。** 手で要約・圧縮した箇所が実機の出力と食い違う事故(修正
ラウンド2の要修正1・6)が実際に起きたため——**全量転記できない箇所は
「全量」と書かず、何を省いたか(行内容の抜粋のみで件数・所要時間は
全量、等)とどう再生成するか(実行コマンド)を明記する。** 具体的には
§4(CQの結果行。cq04/05/06/09は数千〜8千件超あるため`run_cq.py`自身の
`--head`件数分のみを載せ、以降は同スクリプトの省略行の文言のまま)がこれに
該当する。件数・所要時間・0件判定は全10本とも全量。

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
ついて【修正ラウンド2で解消。Ruling B31】**: 上表の3ディレクトリ(全法人・
支出先限定A・支出先限定B)は、いずれも修正前の実装で作られたもので、
`release` フィールドが**全て**`"2026-08-24"`のまま固定されている
(`max(fetched_on.values())`から導出。3件とも実際にmanifestを読んで確認
済み——全法人ディレクトリはmanifest.json自体が無いため対象外、A/Bは
上の「manifest.jsonの比較」節参照)。当時はこれを「Ruling B29が既に受理した
先例と同種で実害は無い、Phase 2への繰り越し課題」としていたが、**この
判断は誤りだった**——実際にはmanifestだけでは3ディレクトリを区別できず、
§6.3の配布契約(tar.gz + manifest)が嘘をついていた。修正ラウンド2で
`release`の意味を「成果物ディレクトリのbasename」に変え(§5「Ruling B31」節
に実物のmanifest比較・壊し確認を記す)、`manifest_version`を5に上げた。
**この3ディレクトリ自体は保護対象なので書き換えていない**(上表のとおり、
manifestの`release`は今も`"2026-08-24"`のまま——修正の効果は、この3件
より後に作るリリースから効く)。検証のため、この3件と全く同じ取得日の組で
新たに`data/artifact/2026-08-27/`をビルドし(**Phase 1として配信する
リリースではなく、B31の修正が実データで効くことを確認するためだけの
第4のディレクトリ**)、`release`が`"2026-08-27"`になり衝突しないことを
確認した(§5参照)。

**追記(修正ラウンド3。項目1)**: `--previous-release`が日付形式のみを
受け付けていた「B31の部分適用」を解消する実データ確認のため、
`data/artifact/2026-08-26-carryover-check/`(前リリース2026-08-26の
manifest+kg.nqの複製。非ISOのbasename)・
`data/artifact/2026-08-26-carryover-check-out/`(この確認の出力先。
kg.nq+pipeline-report.jsonのみでtdb2/manifestは作っていない)の2つが
追加で存在する。**いずれもPhase 1配信物ではなく確認専用**(2026-08-27と
同種の位置づけ)。詳細は`task-11-fix-round-3-report.md`「項目1」節参照。

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
  が実測値) + データ 約13.6GiB。**1トリプルあたり
  (14,813,075,171 − 201,423,591) / (35,584,368 − 5,143) = 410.7 bytes/quad**
  (自分で再計算した値。旧記載の「約390」はprogress.mdからの逐語転記で
  再導出できなかったため訂正——8GiB判定の結論〔13.8GiB > 8GiB〕には影響しない。
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

### 突き合わせ(§1の事前見積り704,359行 との整合性検査)【修正ラウンド2で再導出】

**修正ラウンド2での訂正。** 以前の記載は「payeesグラフの実測差分は
113,623 quads」としていたが、これは`kg.nq`全体から
`grep -F "houjin-bangou-payees/2026-08-23>"`という**部分文字列一致**で
数えた値であり、**payeesグラフ自身についての出典情報(provenanceグラフに
入る7トリプル)を誤って含んでいた**。N-Quadsの4番目の項(グラフ項)を
きちんと末尾で固定して数え直すと、値が変わる。以下、自分で再現した手順と
結果を示す。

```
$ grep -cF "graph/houjin-bangou-payees/2026-08-23>" data/artifact/2026-08-25/kg.nq
113623   # 誤り。部分文字列一致なので、他グラフに入る「このグラフURIへの言及」も数えてしまう

$ grep -cE "<https://jgkg\.norr-tech\.com/graph/houjin-bangou-payees/2026-08-23> \.$" data/artifact/2026-08-25/kg.nq
113616   # 正しい。行末が「<グラフURI> .」であることを固定して、グラフ項そのものだけを数える
```

差分の7行を実際に確認すると、全て**主語がpayeesグラフのURI・グラフ項が
`graph/provenance`**(payeesグラフ「について」のprovenance記述であって
payeesグラフの構成要素ではない):

```
<.../graph/houjin-bangou-payees/2026-08-23> prov:wasDerivedFrom <...zenken/> <.../graph/provenance> .
<.../graph/houjin-bangou-payees/2026-08-23> prov:generatedAtTime "2026-08-23"^^xsd:date <.../graph/provenance> .
<.../graph/houjin-bangou-payees/2026-08-23> dcterms:rights "政府標準利用規約(第2.0版)" <.../graph/provenance> .
<.../graph/houjin-bangou-payees/2026-08-23> dcterms:source "国税庁 法人番号公表サイト 全件データ" <.../graph/provenance> .
<.../graph/houjin-bangou-payees/2026-08-23> prov:wasGeneratedBy "jgkg/0.1.0" <.../graph/provenance> .
<.../graph/houjin-bangou-payees/2026-08-23> dcterms:license <...terms_of_use> <.../graph/provenance> .
<.../graph/houjin-bangou-payees/2026-08-23> core:sourceSha256 "69d3c3a6...be55a" <.../graph/provenance> .
```

B30が実際に追加するのは「支出先として実在する法人(corporations_all=
18,941件)の法人グラフ」である。`_organization_lines`(`src/jgkg/rdf/
stream_emit.py`)は1法人につき **rdf:type・skos:prefLabel・houjinBangou・
organizationKindCode の4つを必須**、prefectureName・cityNameは値がある
ときだけ発行する(最大6トリプル/法人)。抽出した113,616行を述語別に
数えると(`grep -c` を4回):

| 述語 | 件数 |
|---|---|
| rdf:type | 18,941 |
| skos:prefLabel | 18,941 |
| houjinBangou | 18,941 |
| organizationKindCode | 18,941 |
| prefectureName | 18,926 |
| cityName | 18,926 |
| **合計** | **113,616** |

- 実測差分: 817,982(実装後) − 704,359(事前見積り。法人グラフ抜き) =
  113,623 quads = **payeesグラフ自身(113,616)+ provenanceの7行**
- 予測上限: 18,941法人 × 6トリプル = 113,646。payeesグラフの実測113,616
  との差は**23ではなく30**
- **この30の意味を集合として確かめた**(件数の一致だけでなく、対象が
  同じ法人であることまで確認): 法人ごとの`houjinBangou`行から全18,941件の
  法人URI集合を作り、`prefectureName`を持つ集合・`cityName`を持つ集合を
  それぞれ作って差集合を取ると、**prefectureNameを欠く15件とcityNameを
  欠く15件は完全に同じ集合だった**(`comm -23`と`diff`で確認。差分0行)。
  つまり「30」は「都道府県名**または**市区町村名を欠く法人が23件」では
  なく、**「両方を欠く法人が15件(15法人×2項目=30トリプル分の欠落)」**
  である

### 「恒等式」の再検証(要修正4)【修正ラウンド2で訂正】

**修正ラウンド2での訂正。** 以前の記載は「corporations_all(18,941)+53=
18,994=支出先のdistinct法人総数」を「定義上必然的に成り立つ恒等式」と
書いていたが、これは**足し算で作った数(18,994)が、既にprogress.mdに
載っていた数(18,994)と一致することを確認しただけ**であり、
`payee_houjin_bangou`という名指しした集合そのものを実際に構築して
数えてはいなかった。実際に構築すると数が変わる。

`pipeline.py`が`payee_houjin_bangou`を作る規則
(`{int(v) for row in rows for line in row.expenditures if (v :=
line.recipient_houjin_bangou) and v.isdigit()}`)を、`rs.parse_rs`を
自分で呼んでそのまま再現した:

```
$ uv run python scripts/verify_payee_houjin_bangou.py --houjin-bangou 2026-08-23 --rs-system 2026-08-23
==============================================================================
payee_houjin_bangou の再構築(要修正4)
==============================================================================
houjin-bangouスナップショット: 2026-08-23
rs-systemスナップショット    : 2026-08-23
payee_houjin_bangou の distinct 件数: 18995
センチネル(9999999999999)がこの集合に入っているか: True
実在する(corporations_all相当)  : 18941
実在しない(センチネル除く。distinct): 53
内訳の合計: 18941 + 53 + 1(センチネル) = 18995
内訳の合計とpayee_houjin_bangouの件数が一致した(恒等式が成立)
```

**`payee_houjin_bangou`の実際のdistinct件数は18,995であり、18,994では
ない。** 差の1件は**センチネル(`9999999999999`。B18の「非法人の支出先」を
表す値)**——センチネルは13桁の数字文字列なので`v.isdigit()`を通過し、
`payee_houjin_bangou`集合に入る。しかし`resolve_recipient`はセンチネル
判定を法人番号の実在確認より先に行うため、
`budget_recipients_nonexistent_houjin_bangou`(60行/distinct 53件)には
分類されない——`corporations_all`(実在法人)にも`nonexistent`(実在しない
distinct53件)にも入らない、**3つに分けた分類のうちどれにも該当しない
第3の値**である。

**訂正した恒等式: 18,941(実在。corporations_all)+ 53(distinctで実在
しない)+ 1(センチネル) = 18,995 = payee_houjin_bangouのdistinct件数。**
§1に既出の「18,994」は、**センチネルを除いた数**(controllerが前ラウンド
で足し算のみで出した数値)であり、`payee_houjin_bangou`そのものの件数
ではなかったと明記する。この訂正により、恒等式は「足し算の一致」ではなく
「名指しした集合を実際に数えた結果」になった——`corporations_all`の定義が
将来変わっても(例: センチネルを含む方向に変わっても)、この検証手順自体は
再実行すれば誤りを検出できる。

両方の突き合わせ(§2の行数分解・上記の集合構築)が、内容まで確認した
完全な説明として成立しており(件数の一致を運で得たものではない)、
**B30のフィルタが「実装意図どおりに」支出先の実在法人だけを積んでいる**
ことの独立した検証になっている。

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

**修正ラウンド2で単一実行の出力に貼り替えた。** 以前の記載は`--head`の
ラベルが15/10/5の3種類混在し、実際に載っている行数(3/3/5/3)とも
食い違っていた(要修正6。3種類の異なる実行——おそらく`--head`を都度変えて
実行した結果——を手で1つのコードブロックに混ぜていた)。これは単一実行の
出力ではあり得ない、というB32/B25の趣旨に反する状態だった。

**実行対象: `scripts/serve.sh 2026-08-25` で配置したFuseki(`http://localhost:3030/kg/sparql`)。
rdflibのインメモリ実行ではなく実際のJena/TDB2エンドポイント。全10本が非0件で
答えた時点で完了条件Aを満たす(`run_cq.py`の既定は1件でも0件のCQがあれば
非0終了する仕様)。** 以下は`uv run python scripts/run_cq.py`(オプション無し。
既定の`--head 20`)を**1回だけ実行した標準出力そのまま**である(手で編集した
箇所は無い。省略行の文言も`run_cq.py`自身が出す`... 以下 N 行省略`のまま)。

**全行のJSON(`--save-dir`付きの別実行)は`data/artifact/2026-08-25/cq-results/`
に保存済み(リポジトリにはコミットしない成果物ディレクトリ内)——ただし
この保存は上記の標準出力転記より前(同じ`2026-08-25`リリースに対する
別回の実行。ファイルの更新日時で確認できる)。この転記(標準出力)自体が
恒久的な証拠であり、`cq-results/`のJSONは全行データの補助証拠として
残している(同じリリース・同じクエリなので内容は一致するはずだが、
実行そのものは別物であることを明記する——「同じ実行の出力」という
誤読を避けるため)。**

```
==============================================================================
CQの実エンドポイント実行: http://localhost:3030/kg/sparql
対象: 10 本(queries\cq/cq*.rq)
==============================================================================

------------------------------------------------------------------------------
### cq01-jurisdiction-of-ordinance.rq
形式: SELECT / 変数: ['ministry', 'ministryName']
行数: 1 / 0.297 秒
ministry | ministryName
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省

------------------------------------------------------------------------------
### cq02-ministry-budget-by-year.rq
形式: SELECT / 変数: ['y', 'totalBudget', 'projectCount']
行数: 1 / 3.266 秒
y | totalBudget | projectCount
2025 | 91789031491000 | 1176

------------------------------------------------------------------------------
### cq03-recipient-expenditures-by-year.rq
形式: SELECT / 変数: ['project', 'projectName', 'y', 'a']
行数: 13 / 0.109 秒
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
行数: 2021 / 9.000 秒
ministry | ministryName | law | lawTitle
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/413M60000100092 | 義肢装具士法第十七条第一項に規定する指定試験機関を指定する省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/420M60000100003 | 特定フィブリノゲン製剤及び特定血液凝固第ＩＸ因子製剤によるＣ型肝炎感染被害者を救済するための給付金の支給に関する特別措置法施行規則
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/501M60000100040 | 自殺対策の総合的かつ効果的な実施に資するための調査研究及びその成果の活用等の推進に関する法律施行規則
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/502M60000100172 | 新型コロナウイルス感染症を指定感染症として定める等の政令第三条において準用する感染症の予防及び感染症の患者に対する医療に関する法律第十九条第一項の厚生労働省令で定める者等を定める省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/414M60000100127 | 身体障害者補助犬法施行規則
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/413M60000100067 | 労働安全衛生法第七十五条の二第一項に規定する指定試験機関の指定に関する省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/413M60000100191 | 個別労働関係紛争の解決の促進に関する法律施行規則
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/418M60000100036 | 指定地域密着型介護予防サービスの事業の人員、設備及び運営並びに指定地域密着型介護予防サービスに係る介護予防のための効果的な支援の方法に関する基準
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/503M60001F40001 | 特定工場における公害防止組織の整備に関する法律の規定に基づく立入検査の際に携帯する職員の身分を示す証明書の様式の特例に関する省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/417M60000100118 | 心神喪失等の状態で重大な他害行為を行った者の医療及び観察等に関する法律第百三条第一項及び心神喪失等の状態で重大な他害行為を行った者の医療及び観察等に関する法律施行令第十五条の規定により地方厚生局長に委任する権限を定める省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/424M6000054A001 | 株式会社地域経済活性化支援機構法第二十五条第一項第一号に規定するおそれがある旨の認定の申請手続に関する命令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/415M60000100152 | 独立行政法人勤労者退職金共済機構の業務運営、財務及び会計並びに人事管理に関する省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/501M60000900005 | 厚生労働省・国土交通省関係地域再生法施行規則
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/507M60001FCA010 | 物資の流通の効率化に関する法律の規定に基づく荷主に係る届出等に関する命令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/419M60000F48001 | 地域経済牽引事業の促進による地域の成長発展の基盤強化に関する法律第四条第一項に規定する基本計画等に関する省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/415M60000100053 | 特別児童扶養手当証書の様式を定める省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/429M60000100019 | 地域医療連携推進法人会計基準
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/422M60001500004 | ＰＦＯＳ又はその塩及び化学物質の審査及び製造等の規制に関する法律施行令第九条の表ＰＦＯＳ又はその塩の項第一号から第三号までに定める製品に関する技術上の基準を定める省令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/418M60001FFA002 | 温室効果ガス算定排出量等の報告等に関する命令
https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省 | https://jgkg.norr-tech.com/id/law/506M60000100106 | 厚生労働省の所管する法令に係る情報通信技術を利用する方法による国の歳入等の納付に関する法律施行規則
... 以下 2001 行省略

------------------------------------------------------------------------------
### cq05-ministry-of-basis-law.rq
形式: SELECT / 変数: ['law', 'project', 'ministry', 'ministryName']
行数: 5663 / 7.469 秒
law | project | ministry | ministryName
https://jgkg.norr-tech.com/id/law/416AC0000000135 | https://jgkg.norr-tech.com/id/budget/2025/2966 | https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省
https://jgkg.norr-tech.com/id/law/416AC0000000135 | https://jgkg.norr-tech.com/id/budget/2025/2965 | https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省
https://jgkg.norr-tech.com/id/law/416AC0000000135 | https://jgkg.norr-tech.com/id/budget/2025/22037 | https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省
https://jgkg.norr-tech.com/id/law/416AC0000000135 | https://jgkg.norr-tech.com/id/budget/2025/22035 | https://jgkg.norr-tech.com/id/org/6000012070001 | 厚生労働省
https://jgkg.norr-tech.com/id/law/329AC0000000144 | https://jgkg.norr-tech.com/id/budget/2025/1545 | https://jgkg.norr-tech.com/id/org/7000012060001 | 文部科学省
https://jgkg.norr-tech.com/id/law/329AC0000000144 | https://jgkg.norr-tech.com/id/budget/2025/1533 | https://jgkg.norr-tech.com/id/org/7000012060001 | 文部科学省
https://jgkg.norr-tech.com/id/law/411AC0100000052 | https://jgkg.norr-tech.com/id/budget/2025/49 | https://jgkg.norr-tech.com/id/org/8000012130001 | 警察庁
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/961 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/1057 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/966 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/1137 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/956 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/994 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/7683 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/1082 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/999 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/21745 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/21868 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/20154 | https://jgkg.norr-tech.com/id/org/8000012010038 | デジタル庁
https://jgkg.norr-tech.com/id/law/412CO0000000249 | https://jgkg.norr-tech.com/id/budget/2025/1069 | https://jgkg.norr-tech.com/id/org/9000012040001 | 外務省
... 以下 5643 行省略

------------------------------------------------------------------------------
### cq06-unresolved-recipients-per-project.rq
形式: SELECT / 変数: ['project', 'category', 'count']
行数: 8151 / **152.890 秒**
project | category | count
https://jgkg.norr-tech.com/id/budget/2025/1 | resolved | 8
https://jgkg.norr-tech.com/id/budget/2025/100 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/100 | resolved | 10
https://jgkg.norr-tech.com/id/budget/2025/1000 | resolved | 10
https://jgkg.norr-tech.com/id/budget/2025/1001 | resolved | 1
https://jgkg.norr-tech.com/id/budget/2025/1003 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/1004 | resolved | 1
https://jgkg.norr-tech.com/id/budget/2025/1007 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/1008 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/1009 | resolved | 1
https://jgkg.norr-tech.com/id/budget/2025/101 | resolved | 2
https://jgkg.norr-tech.com/id/budget/2025/101 | sentinel | 8
https://jgkg.norr-tech.com/id/budget/2025/1010 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/1011 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/1011 | resolved | 4
https://jgkg.norr-tech.com/id/budget/2025/1012 | bundled | 1
https://jgkg.norr-tech.com/id/budget/2025/1014 | bundled | 2
https://jgkg.norr-tech.com/id/budget/2025/1015 | bundled | 2
https://jgkg.norr-tech.com/id/budget/2025/1016 | resolved | 17
https://jgkg.norr-tech.com/id/budget/2025/1016 | sentinel | 42
... 以下 8131 行省略

**追記(最終レビュー要修正4。裁定B42)。** 上記の`sentinel`という分類名は
嘘だった: `budget:payeeLabel`はセンチネル行(B18)と実在しない法人番号の
行(Ruling B27)の**両方**に付き、グラフ上この2つを区別するトリプルが
無い(`emit.py`/`rs.py`参照)。pipeline-reportは9,922(センチネル)と
60(実在しない法人番号)を分けて記録しているのに、CQ6は合算した9,982を
「そもそも法人でない(センチネル)」1categoryとして報告していた——
**照合の失敗を照合すべき対象が無いこととして報告する**過大な単純化。

クエリを`sentinel_or_nonexistent_houjin_bangou`に改称した上で
(`queries/cq/cq06-unresolved-recipients-per-project.rq`。クエリ側だけでは
2つを分けられないため、合算であることが名前から分かる形にした。分ける
にはemit側に理由トリプルを足す必要があり、それはPhase 2に送った)、
**実Fusekiで再実行し、8151行全量を集計して実測した**(修正前にこの数字
自体を実際にクエリで確認したことは無かった——上の転記は先頭20行だけで、
9,982という数字はpipeline-reportの2欄から**導出**しただけだった):

```
$ scripts/serve.sh 2026-08-26   # data/artifact/2026-08-26 を配置(B: carry-over。
                                 # budget系グラフは2026-08-25から変更無く据え置き)
$ uv run python scripts/run_cq.py --pattern "cq06*.rq" --save-dir <tmp> \
    --endpoint http://localhost:3030/kg/sparql
行数: 8151 / 158.594 秒(上記の152.890秒の実行と同じ行数・同じデータ——
carry-overによりbudget系グラフの内容が2026-08-25から変わっていないため)

# 保存されたJSON(8151行全量)をcategoryごとに集計:
bundled                                  7326
resolved                                56607
sentinel_or_nonexistent_houjin_bangou     9982
unresolved                                  4
grand total                             73919
```

**`sentinel_or_nonexistent_houjin_bangou`の実測値は9,982**——
`data/artifact/2026-08-25/pipeline-report.json`の
`budget_recipients_sentinel`(9,922)+`budget_recipients_nonexistent_houjin_bangou`
(60)の合計と**完全に一致した**(実測して初めて確認。レビューが指摘した
とおり、修正前はこの一致自体が未検証だった)。

------------------------------------------------------------------------------
### cq07-provenance-of-edge.rq
形式: SELECT / 変数: ['graph', 'source', 'fetchedOn', 'license']
行数: 1 / 0.031 秒
graph | source | fetchedOn | license
https://jgkg.norr-tech.com/graph/egov-law/2026-08-24 | https://laws.e-gov.go.jp/api/2/laws | 2026-08-24 | 政府標準利用規約(第2.0版)

------------------------------------------------------------------------------
### cq08-law-revision-as-of-date.rq
形式: SELECT / 変数: ['revision', 'd']
行数: 1 / 0.078 秒
revision | d
https://jgkg.norr-tech.com/id/law/417M60000100021/20260401_令和八年厚生労働省令第三号 | 2026-04-01

~~**最終レビュー観察O9(park。裁定により直さない)。** `queries/cq/cq08-*.rq:40`の
`FILTER (?d <= "2026-04-01"^^xsd:date)`は、実データ側の唯一の版
(`417M60000100021`石綿障害予防規則の施行日)と同値に固定されている。
e-Govコネクタは「現在の改正情報」1件しか取らないため、この法令が
次に改正されて施行日が`2026-04-01`より後になると、`?d <= 2026-04-01`に
一致する版が0件になりCQ8は再び0件を返す——修正ラウンドで実際に踏んだ
欠陥(cutoff `2023-01-01`で0件)と同型で、fixture側のテストは通り続けるため
自動検知されない。**カットオフの導出化には`run_cq.py`にクエリの
置換機構を新設する必要があり、park(裁定)。次にe-Gov法令APIから
データを再取得するタイミングで、このカットオフを実データの最新の版に
合わせて動かす必要があることをここに明記する。**~~

**→ A-3(O9)で解消(2026-08-25)。** 上のparkは撤回された。`run_cq.py`に
置換機構を新設せず、`queries/cq/cq08-*.rq`自身のSPARQLで、LawRevisionが
載っている名前付きグラフ自身の`prov:generatedAtTime`(このデータを
取得した時点)からカットオフを導出する形に変更した(CQ7と同じ
「`?graph`をGRAPH{}の内外両方で束縛する」パターンの応用。追加の置換
機構は不要だった)。手書きの日付リテラルは0件になり、`data/artifact/
2026-08-26`を配置した実Fusekiで実測: 新しいCQ8は1件(`417M60000100021`の
2026-04-01の版)を返し、参考として元のバグの日付(`?d <= "2023-01-01"`)を
同じエンドポイントに流すと0件に戻ることを確認した(詳細は
`task-A3-report.md`)。**e-Gov法令APIからデータを再取得しても、このカットオフ
は自動的にその時点へ動く**ため、上記のparkの理由(次の再取得で再発する)は
解消している。

------------------------------------------------------------------------------
### cq09-jurisdiction-resolution-status.rq
形式: SELECT / 変数: ['law', 'status', 'detail']
行数: 6517 / 7.047 秒
law | status | detail
https://jgkg.norr-tech.com/id/law/414M60000800066 | resolved | https://jgkg.norr-tech.com/id/org/2000012100001
https://jgkg.norr-tech.com/id/law/426M60400000004 | resolved | https://jgkg.norr-tech.com/id/org/7000012010022
https://jgkg.norr-tech.com/id/law/422M60000040052 | resolved | https://jgkg.norr-tech.com/id/org/8000012050001
https://jgkg.norr-tech.com/id/law/430M60000048001 | resolved | https://jgkg.norr-tech.com/id/org/8000012050001
https://jgkg.norr-tech.com/id/law/430M60000048001 | resolved | https://jgkg.norr-tech.com/id/org/2000012020001
https://jgkg.norr-tech.com/id/law/429M60000442003 | resolved | https://jgkg.norr-tech.com/id/org/2000012010019
https://jgkg.norr-tech.com/id/law/429M60000442003 | resolved | https://jgkg.norr-tech.com/id/org/8000012050001
https://jgkg.norr-tech.com/id/law/429M60000442003 | resolved | https://jgkg.norr-tech.com/id/org/4000012090001
https://jgkg.norr-tech.com/id/law/413M60000100092 | resolved | https://jgkg.norr-tech.com/id/org/6000012070001
https://jgkg.norr-tech.com/id/law/504RJNJ09148000 | resolved | https://jgkg.norr-tech.com/id/org/2000012010002
https://jgkg.norr-tech.com/id/law/413M60000400104 | resolved | https://jgkg.norr-tech.com/id/org/4000012090001
https://jgkg.norr-tech.com/id/law/503M60001C00002 | resolved | https://jgkg.norr-tech.com/id/org/4000012090001
https://jgkg.norr-tech.com/id/law/503M60001C00002 | resolved | https://jgkg.norr-tech.com/id/org/2000012100001
https://jgkg.norr-tech.com/id/law/503M60001C00002 | resolved | https://jgkg.norr-tech.com/id/org/1000012110001
https://jgkg.norr-tech.com/id/law/503M60000080031 | resolved | https://jgkg.norr-tech.com/id/org/7000012060001
https://jgkg.norr-tech.com/id/law/405M50000640001 | resolved | https://jgkg.norr-tech.com/id/org/5000012080001
https://jgkg.norr-tech.com/id/law/423R00000001007 | resolved | https://jgkg.norr-tech.com/id/org/6000012150001
https://jgkg.norr-tech.com/id/law/420M60000100003 | resolved | https://jgkg.norr-tech.com/id/org/6000012070001
https://jgkg.norr-tech.com/id/law/501M60000100040 | resolved | https://jgkg.norr-tech.com/id/org/6000012070001
https://jgkg.norr-tech.com/id/law/419M60400000023 | resolved | https://jgkg.norr-tech.com/id/org/7000012010022
... 以下 6497 行省略

------------------------------------------------------------------------------
### cq10-release-freshness.rq
形式: SELECT / 変数: ['sourceName', 'asOf', 'dateKind']
行数: 5 / 0.031 秒
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

- **CQ2の答え(91,789,031,491,000円)の範囲を明文化(修正ラウンド2
  裁定B34)**: この金額は**一般会計＋特別会計の合計**である。
  `budget_summary`の会計区分別明細行(列25「会計区分」・列28「当初予算」)を
  自分で集計すると、特別会計71,174,383,135,000円(77.5%)+一般会計
  20,614,648,356,000円(22.5%)=91,789,031,491,000円と、CQ2の答え・
  集計行(列14「当初予算(合計)」)の合計の両方に一致した(下記のように
  3方向とも一致することを自分で確認した)。厚生労働省の一般会計予算
  だけを期待して比べる読者は約2.6倍ずれた解釈をする。クエリのコメント
  ・`schema/competency-questions.md`(B34節)にもスコープを明記した。
  併せて`budget:ministry`がRS列5(政策所管府省庁)から作られること
  (列6の府省庁ではない)も同じ場所に明記した。
  **この裏付けは`scripts/verify_cq2_scope.py`としてコミット済み**
  (裁定B25「測定は使い捨てにしない」——要修正5で他の1回限りの確認を
  スクリプト化しなかったことが指摘されたのと同じ轍を踏まないため、
  ここは最初からコミットする)。

```
$ uv run python scripts/verify_cq2_scope.py --rs-system 2026-08-23 \
    --ministry 厚生労働省 --fiscal-year 2025
==============================================================================
B34裏付け確認: 厚生労働省 FY2025 budget_summaryの会計区分別明細
==============================================================================
集計行(会計区分が空): 1176 行 / 合計 91,789,031,491,000 円
明細行(会計区分が非空): 1225 行
  特別会計: 71,174,383,135,000 円 (77.5%)
  一般会計: 20,614,648,356,000 円 (22.5%)
明細行の合計: 91,789,031,491,000 円
集計行の合計と明細行の合計が一致するか: True
```

CQ2自体の答え(91,789,031,491,000円)は`run_cq.py`+`cq02`のSPARQLで
恒久的に再現可能(§4参照)。上記の集計行合計もその値と一致しており、
3方向(CQ2のSPARQL結果・集計行(列14)の合計・明細行(列28)を会計区分別に
合計した値)がすべて91,789,031,491,000円で一致した。

- CQ8(法令の改正としての時点指定): 事前監査で発見した実データ不整合
  (ハードコードされたカットオフ日`2023-01-01`が実データの改正日
  `2026-04-01`より前で0件になる)を修正した効果が、実エンドポイントでも
  1件の答え(`2026-04-01`)として確認できた
- CQ10(鮮度): 5件——e-Gov(取得日)・法人番号(取得日。houjin-bangou/
  houjin-bangou-payeesの2グラフ分で2行)・府省名簿(記録日)・RS(取得日)。
  ソース4種+法人番号グラフが2つという構成と一致する(異常ではない)
- **観察(性能。完了条件Aの合否には影響しないが記録する): CQ6は今回の
  実行で152.9秒かかった**(前ラウンドの実行では154.8秒。ともに他のCQ
  〔いずれも10秒未満〕と比べて明確に遅い)。予算執行明細(73,919行)を
  project×categoryで集計するクエリで、この規模でも実用上は許容範囲
  (タイムアウト300秒以内)だが、Phase 2でAPI層を作る場合はこのパターン
  (project単位の集計)にキャッシュや事前集計を検討する価値がある、
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
確認した。修正ラウンド2でこの検査を`scripts/compare_releases.py`として
コミットした(要修正5・裁定B33)。** 前ラウンドの記載はグラフ別に手で
`grep`して`sort | sha256sum`した結果の書き起こしで、コミットされた
スクリプトが無かった(B25違反)。このスクリプトは名前付きグラフごとに
行をソートしてsha256を突き合わせ、**残余行(manifestが列挙するどの
グラフにも属さない行)が0であることも検査する**。

**開発中に実際に発見した罠**: グラフ項を素朴な正規表現(`<[^>]*>`が
行末に来ることを見る)で取ろうとしたところ、実データの1つのリテラル値
(`"<こどもの事故防止に関する取組の経費＞ ..."`。ASCIIの`<`で開き全角の
「＞」で閉じる書式)がリテラル内部に生の`<`を含んでいたため、そこから
実際のグラフ項の`>`までを1つの誤ったIRIとして食ってしまい、2行が
「残余行」として誤検出された。引用符の内外を状態として追う簡易
トークナイザに直して解消した(スクリプトのdocstring参照)。

```
$ uv run python scripts/compare_releases.py data/artifact/2026-08-25 data/artifact/2026-08-26
==============================================================================
リリース比較(グラフ別ソート済みsha256): data\artifact\2026-08-25 vs data\artifact\2026-08-26
==============================================================================
manifest graphs A (6): ['https://jgkg.norr-tech.com/graph/egov-law/2026-08-24', 'https://jgkg.norr-tech.com/graph/houjin-bangou-payees/2026-08-23', 'https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23', 'https://jgkg.norr-tech.com/graph/ministry-codes/2026-08-23', 'https://jgkg.norr-tech.com/graph/provenance', 'https://jgkg.norr-tech.com/graph/rs-system/2026-08-23']
manifest graphs B (6): ['https://jgkg.norr-tech.com/graph/egov-law/2026-08-24', 'https://jgkg.norr-tech.com/graph/houjin-bangou-payees/2026-08-23', 'https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23', 'https://jgkg.norr-tech.com/graph/ministry-codes/2026-08-23', 'https://jgkg.norr-tech.com/graph/provenance', 'https://jgkg.norr-tech.com/graph/rs-system/2026-08-23']

SAME   https://jgkg.norr-tech.com/graph/egov-law/2026-08-24
        A: 140,430 行  sha256=126afa10d5286c5e2a3a40102e10fc7c15e21a85bbd7077c9a51336423cf2c0a
        B: 140,430 行  sha256=126afa10d5286c5e2a3a40102e10fc7c15e21a85bbd7077c9a51336423cf2c0a
SAME   https://jgkg.norr-tech.com/graph/houjin-bangou-payees/2026-08-23
        A: 113,616 行  sha256=e992ca610e1063feff0f771c2feba5797b83c2a823d52c537ffccc2073e4bafe
        B: 113,616 行  sha256=e992ca610e1063feff0f771c2feba5797b83c2a823d52c537ffccc2073e4bafe
SAME   https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23
        A:   5,088 行  sha256=58b427d642828dcddd5f2d6c73bef92f1e11afbf54063163a62a3708077b52e6
        B:   5,088 行  sha256=58b427d642828dcddd5f2d6c73bef92f1e11afbf54063163a62a3708077b52e6
SAME   https://jgkg.norr-tech.com/graph/ministry-codes/2026-08-23
        A:      40 行  sha256=33a658ede3c32ccd631bd0f52013b4a39868375e4bfe5aaecc864ac920e0f987
        B:      40 行  sha256=33a658ede3c32ccd631bd0f52013b4a39868375e4bfe5aaecc864ac920e0f987
SAME   https://jgkg.norr-tech.com/graph/provenance
        A:      40 行  sha256=83a9a5f33ecdaf62a24346c0f5fb8e6107daf6dc10987e9846558e181f2d2e81
        B:      40 行  sha256=83a9a5f33ecdaf62a24346c0f5fb8e6107daf6dc10987e9846558e181f2d2e81
SAME   https://jgkg.norr-tech.com/graph/rs-system/2026-08-23
        A: 558,768 行  sha256=3d0e0cbb7230b48cf1d63aeae02257f40faf4b62059f305001d92edd7d36dd54
        B: 558,768 行  sha256=3d0e0cbb7230b48cf1d63aeae02257f40faf4b62059f305001d92edd7d36dd54

残余行(いずれのmanifest記載グラフにも属さない行): A=0 / B=0
内容が一致しないグラフ: 0 件 []
判定: 全6グラフの内容が一致し、残余行も0件

$ echo $?
0
```

**manifestに載る6グラフ全て(houjin-bangou・egov-law・rs-system・
ministry-codes・provenance・houjin-bangou-payees)がA/Bで完全に一致し、
残余行も0件だった**(`triple_count`が同じ817,982なのは「総数が同じ」
ことしか示さないため、6グラフそれぞれを個別に確認する意味がある)。

**壊し確認**: 合成した最小限の2リリース(g1/g2のみ・3行)に対し、Bの
kg.nqへ`<graph/g3-stray>`という**manifestに載っていないグラフ**の行を
1行だけ追加して実行すると、正しく検出して失敗した:

```
残余行(いずれのmanifest記載グラフにも属さない行): A=0 / B=1
  残余として検出されたグラフ項/キー: ['https://example.org/graph/g3-stray']
内容が一致しないグラフ: 0 件 []
判定: 不一致あり(**既定は失敗**)
$ echo $?
1
```

g1/g2自体は変更していないので両方`SAME`のまま出力され、追加した1行だけが
正しく残余として検出されている(検査が「対象0件で合格に退化」していない
ことも兼ねて確認できた)。

つまり**トリプルの欠落・重複・改変は無い**。差は`emit.write_nquads`が
`clean`(rdflib Dataset)をシリアライズする際の行の出力順のみであり、
carry-over経路(前リリースのグラフを読み込んで`clean`に足す)と
新規生成経路(パイプラインが生成した順に`clean`に足す)で、rdflibへの
追加順序が異なるために生じる(rdflibの`Dataset`は挿入順に依存した順序で
シリアライズする)。**これはkg.nqのバイト列レベルの差であり、TDB2への
ロード結果(トリプルの集合)には影響しない**——実際に`tdb2_expanded_bytes`
はA/Bで完全に一致している。

### Ruling B31: releaseフィールドが同日リリースA/Bで衝突していた実物証拠

**この節の`release`/`manifest_version`の値は、上のA/Bのmanifest.jsonを
そのまま読んだものであり、加工していない(データは`data/artifact/2026-08-25/`・
`data/artifact/2026-08-26/`。両方とも保護対象で、修正ラウンド2ではこれらの
中身を一切書き換えていない)。**

修正前の`pipeline.py`は`release=max(fetched_on.values()).isoformat()`
(=ソースの中で最も新しい取得日)を「リリースの同一性」として書いていた。
A・Bはどちらも「取得日の組」が同じ(egov-lawだけ2026-08-24、他は
2026-08-23)ため、ディレクトリ名(basename)が違うのに`release`が
衝突していた。実際にA/Bのmanifest.jsonを読んで確認した:

| ディレクトリ(basename) | manifest.jsonの`release` | `created_on` | `manifest_version` |
|---|---|---|---|
| `data/artifact/2026-08-25`(A) | `2026-08-24` | `2026-08-24` | 4 |
| `data/artifact/2026-08-26`(B) | `2026-08-24` | `2026-08-24` | 4 |

**A・Bはディレクトリ名が違う(A=`2026-08-25`、B=`2026-08-26`)のに、
manifest.jsonの`release`は両方とも`2026-08-24`で完全に一致している。**
manifest.jsonだけを見て「これはどのリリースか」を判定する利用者は、
A/Bを区別できない(§6.3の配布契約は「tar.gz + manifest」なので、
manifestが契約の全てである)。この2つのmanifestは**修正前の実装で
実際に作られたもの**であり、修正ラウンド2ではこの2ディレクトリの
中身を書き換えていない(保護対象。上の表はそのままの実測)。

**修正後の実データ確認(判定基準(a))**: `release=out_dir.name`に直し、
`houjin-bangou/ministry-codes/rs-system=2026-08-23、egov-law=2026-08-24`
という**A/Bと全く同じ取得日の組**で、新しいディレクトリ
`data/artifact/2026-08-27/`に実際にビルドした(`--out-dir`で明示。
既存リリースを上書きしないため)。**所要時間は、`data/artifact/2026-08-27/
build.log`を`grep`して直接読んだ(要修正1と同じ方法。伝聞の数字を書かない)**:

```
[所要] 鮮度監視: 1 秒(開始からの累計 1 秒)
[所要] スキーマ生成: 35 秒(開始からの累計 36 秒)
[所要] パイプライン(取得済みスナップショット→kg.nq、検証含む): 422 秒(開始からの累計 458 秒)
[所要] tdbloader(コンテナのネイティブ層でTDB2構築+tar.gz化): 34 秒(開始からの累計 492 秒)
[所要] 構築結果の検査: 1 秒(開始からの累計 493 秒)
[所要] manifest作成: 2 秒(開始からの累計 495 秒)
完了: data/artifact/2026-08-27(総所要 495 秒)
```

**総所要は495秒であり、「約21秒」ではない。** この「21秒」という見積りは、
tdbloaderフェーズ単体(§2の「構築時間21.2秒」)の数字を全体の所要時間と
混同したものだった——ちょうど要修正2(1つの数字を別の意味の数字と取り違える)
と同種の誤りである。tdbloaderフェーズ自体は今回34秒で、桁としては21.2秒に
近い(A/Bの実測との差は自然なばらつきの範囲)。パイプライン実行フェーズ
(422秒)がA(445秒)・B(458秒)と近い値になっているのは、取得日の組が
A/Bと全く同じであるため妥当である。

```
$ cat data/artifact/2026-08-27/manifest.json
{
  "release": "2026-08-27",
  "created_on": "2026-08-27",
  ...
  "manifest_version": 5,
  ...
}
```

**取得日の組はA/Bと同一のまま、`release`はディレクトリ名どおり
`2026-08-27`になり、A/Bの`2026-08-24`とはもう衝突しない。**
`manifest_version`も5に上がっている(旧実装で作られたA/Bの4とは
読み手が区別できる)。

**pytestでの回帰防止(判定基準(a)の自動テスト化)**:
`tests/test_pipeline.py::test_run_same_day_releases_are_distinguishable_by_release_field`
を追加した。壊し確認は§14に記す。

### 壁時計時間の比較(carry-overの効果が見えない理由)

**訂正(修正ラウンド2)。** 以前の記載は「A=461秒」だったが、これは
`data/artifact/2026-08-25/build.log` を読み違えたか、実物検査が途中失敗
した1回目のビルド(実物検査は失敗したがパイプライン自体は完走していた
——本報告書のStep 6参照)のログの数字を誤って引いてきたもので、**最終的に
採用した成功ビルドの実ログの値ではなかった。** 現存する
`data/artifact/2026-08-25/build.log` を直接`grep`して確認した実際の値は
以下のとおり:

```
$ grep -n "パイプライン\|総所要" data/artifact/2026-08-25/build.log
[所要] パイプライン(取得済みスナップショット→kg.nq、検証含む): 445 秒(開始からの累計 489 秒)
完了: data/artifact/2026-08-25(総所要 527 秒)
```

| リリース | パイプライン実行(検証を含む) | 総所要 |
|---|---|---|
| A(初回) | **445秒**(訂正前は461秒と誤記載) | 527秒 |
| B(carry-over) | 458秒 | 544秒 |

**carry-overが3グラフを据え置いたにもかかわらず、Bのほうが13秒
遅かった(458秒 vs 445秒)。** 訂正前の記載は符号が逆(「Bがわずかに速い」)
だった。carry-overの価値を評価する読者はこの逆転した結論を受け取っては
ならない——修正する。

原因は完全には特定できないが、`src/jgkg/pipeline.py`を自分で読んで
説明できる寄与を1つ確認した: **egov-lawの法令パース・所管解決
(`law_mod.parse_laws`→`derive_jurisdiction`。9,547件)は、carry-over判定
(`egov_carry_date`)を一度も参照せず`"egov-law" in fetched_on`だけで
無条件に実行される**(`pipeline.py:974`〜`1006`。据え置き対象の判定は
その後段でグラフを書くかどうかにしか使われない)。つまりegov-lawグラフが
`carried_over`に載っていても、その生成に使う9,547件の解析処理自体はA・B
どちらでも丸ごと実行されており、carry-overはこの部分の時間を1秒も
節約していない。houjin-bangou全件(580万行)の毎回フルスキャン
(`rows_seen`がA/Bとも5,816,535で同一)と合わせると、**「据え置き対象の
グラフの生成コストの大部分は、そもそもcarry-overで避けられない構成に
なっている」**ことがA/B双方の`rows_seen`/`law_records`の一致から分かる。
残りの13秒の差自体(Bが遅い理由の全て)は、これだけでは説明がつかない
——同規模の処理を2回連続で行ったときの実行ごとのばらつき(ディスク
キャッシュの状態やOSスケジューリング等)である可能性が高いが、**これは
推測であり、確認していない。未解明として残す。**

carry-overがグラフの**据え置き**(再検証・再排出のスキップ)自体は
`carried_over`リストと(fixtureの)carry-overテスト群で確認済みである。
この構成での結論は「carry-overは効いていないが、そもそも壁時計時間の
大半を占めるのはcarry-overの対象になっていない処理(法人マスタの
フルスキャン・egov-lawの無条件パース)である」という切り分けであり、
訂正後もこの切り分け自体は変わらない。

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

### 完了条件Cの判定【修正ラウンド2で訂正】

**修正ラウンド2での訂正。** 以前の記載「据え置き4グラフはSHACL再検証、
新規1グラフは通常検証」は数が実物と合っていなかった。実物
(`data/artifact/2026-08-26/pipeline-report.json`)は`carried_over`が3件
(houjin-bangou/egov-law/rs-system)・`graphs_validated: 5`である。
`src/jgkg/pipeline.py:1329`の`results = validate.validate_dataset(ds,
SHAPES_DIR)`が見る`ds`には、この時点でministry-codes・provenance(常に
新規生成する2グラフ)しか入っていない(carry-overされる3グラフは
`ds`に足されず、別のDataset上で`carried_validation_results`として
個別に再検証される。`houjin-bangou-payees`はこれとも別の
`validate.validate_stream`(バッチSHACL)で検証される)。したがって
`graphs_validated=5`の内訳は**新規2(ministry-codes・provenance。
`validate_dataset`経由)+ 据え置き3(houjin-bangou・egov-law・rs-system。
別Datasetでの再検証経由)**であり、「4+1」ではない。
`houjin-bangou-payees`はこの5件のどちらにも数えられていない(=別経路の
検証を受けている)ため、6グラフ全体で見ると「新規2+据え置き3+
バッチSHACL1(houjin-bangou-payees)」が正しい内訳になる。

完了条件Cの判定: **満たす。** 取得(既存スナップショットの再利用含む)→
差分検出(`carried_over`)→検証(新規2グラフは通常のSHACL検証・据え置き
3グラフは別Datasetでの再検証・houjin-bangou-payeesはバッチSHACL)→
リリース切替(serve.sh)→鮮度反映(current/previousの実際の入れ替わり+
エンドポイントの応答)の一巡を実データで通し、2つ目のリリース
(`data/artifact/2026-08-26/`)を作った。

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

**追記(修正ラウンド3。項目1で部分的に解消)**: 上記の「再現できなくなる」
という懸念の原因(`_previous_date_if_unchanged`が`lake.latest_before`で
「前リリース時点の直近スナップショット」を探索していたこと)自体を、
修正ラウンド3でcarry-over判定から取り除いた——前リリースが実際に使った
取得日を、探索ではなく前リリース自身のmanifest.sourcesから直接読む方式に
変えたため、`lake.latest_before`はこの経路でもう呼ばれない。**この一文の
「以後は再現できない」は、この修正より後に作るリリース間のcarry-over
判定には当たらなくなった**(詳細:
`task-11-fix-round-3-report.md`「項目1」節、`pipeline.py`の
`_previous_date_if_unchanged`docstring)。本文はそのまま保存する
(当時の判断の記録として価値があるため)。

取得した事業年度2024の4ファイル(`data/lake/`は`.gitignore`対象なので、
出典追跡のためsha256をここに記録する):

| ファイル | sha256 |
|---|---|
| 1-2_RS_2024_基本情報_事業概要等.zip | `82488871dff9b2a450444d11b4010951ca02e2ec7bd886e6e923c4b2a512e4e2` |
| 2-1_RS_2024_予算・執行_サマリ.zip | `a054b9e8e87850ffbf9ab5ec478eaf5a344259989d868dda02bb1b92fbf1909e` |
| 1-3_RS_2024_基本情報_政策・施策、法令等.zip | `890d31b93d7d4266975fb763ceb707458a103ba21bada92999e92a5be177eced` |
| 5-1_RS_2024_支出先_支出情報.zip | `4624b0c1e179cbe2c6edcff4bbf30e4108ff8bb3f2751c74f7e216821afe895d` |

**修正ラウンド2で全量転記に置き換えた。** 以前の記載は`:6`の
「全量転記」の宣言に反して、標準出力の一部(paths・分布2種・重複キーの
上位10件・建制順の全23行・不一致30件)を手で1〜数行に圧縮していた
(要修正6)。以下は`scripts/measure_rs_cross_year.py --snapshot
2026-08-23 --snapshot 2026-08-24`を再実行した標準出力の**全量**である:

```
==============================================================================
RSの年度をまたいだ整合(Task 6 懸念12・13)
==============================================================================
--- 取得日 2026-08-23 ---
  budget_summary                           data\lake\rs-system\2026-08-23\2-1_RS_2025_予算・執行_サマリ.zip
  organization_information                 data\lake\rs-system\2026-08-23\1-1_RS_2025_基本情報_組織情報.zip
  payee_payment_information                data\lake\rs-system\2026-08-23\5-1_RS_2025_支出先_支出情報.zip
  policy_measure_laws_and_regulations      data\lake\rs-system\2026-08-23\1-3_RS_2025_基本情報_政策・施策、法令等.zip
  project_summary                          data\lake\rs-system\2026-08-23\1-2_RS_2025_基本情報_事業概要等.zip
  project_summary の行数 : 6,061
  事業数(distinct pid)  : 5,794
  府省数(distinct 府省庁): 23
  事業年度の分布         : {'2025': 6061}
  budget_summary の行数  : 47,100
  budget_summary の事業年度列: {'2025': 47100}

--- 取得日 2026-08-24 ---
  budget_summary                           data\lake\rs-system\2026-08-24\2-1_RS_2024_予算・執行_サマリ.zip
  payee_payment_information                data\lake\rs-system\2026-08-24\5-1_RS_2024_支出先_支出情報.zip
  policy_measure_laws_and_regulations      data\lake\rs-system\2026-08-24\1-3_RS_2024_基本情報_政策・施策、法令等.zip
  project_summary                          data\lake\rs-system\2026-08-24\1-2_RS_2024_基本情報_事業概要等.zip
  project_summary の行数 : 5,948
  事業数(distinct pid)  : 5,664
  府省数(distinct 府省庁): 23
  事業年度の分布         : {'2024': 5948}
  budget_summary の行数  : 37,981
  budget_summary の事業年度列: {'2024': 37981}

### 懸念12: 建制順(kensei_jun)の年度をまたいだ安定性
比較: 2026-08-23 vs 2026-08-24
  2026-08-23: 府省名1件に建制順が2つ以上 = 0 件 
  2026-08-24: 府省名1件に建制順が2つ以上 = 0 件 
  両年度に現れる府省名 : 23
  片方だけ(2026-08-23のみ): []
  片方だけ(2026-08-24のみ): []
  **建制順が変わった府省: 0 件**
    (両年度に現れる府省の建制順はすべて一致した)

  両年度の建制順の対応(全件):
    こども家庭庁                   ['12'] / ['12']
    カジノ管理委員会                 ['9'] / ['9']
    デジタル庁                    ['13'] / ['13']
    個人情報保護委員会                ['8'] / ['8']
    公正取引委員会                  ['6'] / ['6']
    内閣官房                     ['1'] / ['1']
    内閣府                      ['4'] / ['4']
    厚生労働省                    ['20'] / ['20']
    原子力規制委員会                 ['25'] / ['25']
    国土交通省                    ['23'] / ['23']
    外務省                      ['17'] / ['17']
    復興庁                      ['14'] / ['14']
    文部科学省                    ['19'] / ['19']
    法務省                      ['16'] / ['16']
    消費者庁                     ['11'] / ['11']
    環境省                      ['24'] / ['24']
    経済産業省                    ['22'] / ['22']
    総務省                      ['15'] / ['15']
    警察庁                      ['7'] / ['7']
    財務省                      ['18'] / ['18']
    農林水産省                    ['21'] / ['21']
    金融庁                      ['10'] / ['10']
    防衛省                      ['26'] / ['26']

### 懸念13(前半): budget_summary の (project_id, 予算年度) 複合キー
  2026-08-23: キー数 23,036 / 重複キー 23,034 件
    6 行  project_id=20087 予算年度=2024
    5 行  project_id=2511 予算年度=2023
    5 行  project_id=2639 予算年度=2023
    5 行  project_id=3000 予算年度=2023
    5 行  project_id=3822 予算年度=2023
    4 行  project_id=284 予算年度=2024
    4 行  project_id=341 予算年度=2023
    4 行  project_id=341 予算年度=2022
    4 行  project_id=341 予算年度=2021
    4 行  project_id=474 予算年度=2024
    予算年度の分布: {'2021': 7180, '2022': 7683, '2023': 9915, '2024': 10614, '2025': 11708}
  2026-08-24: キー数 18,524 / 重複キー 18,521 件
    5 行  project_id=2511 予算年度=2023
    5 行  project_id=2639 予算年度=2023
    5 行  project_id=3000 予算年度=2023
    5 行  project_id=3822 予算年度=2023
    4 行  project_id=341 予算年度=2023
    4 行  project_id=341 予算年度=2022
    4 行  project_id=341 予算年度=2021
    4 行  project_id=2253 予算年度=2023
    4 行  project_id=2253 予算年度=2022
    4 行  project_id=2437 予算年度=2022
    予算年度の分布: {'2021': 7585, '2022': 8232, '2023': 10724, '2024': 11440}

### 懸念13(核心): 同じ project_id が両年度で同じ事業を指すか
  両年度に現れる project_id : 5,231
  2026-08-23 のみ: 563
  2026-08-24 のみ: 433
  事業名が一致   : 4,952 (94.7%)
  **事業名が不一致: 279 (5.3%)**
  所管府省が一致 : 5,231 (100.0%)
  不一致の例(最大30件。project_id / 事業名A / 事業名B):
    1        内閣人事局経費(研修事業)                              内閣人事局経費
    48       サイバーセキュリティ関係情報システム等経費                      内閣サイバーセキュリティセンター情報システム等経費
    49       子供の性被害防止対策の推進                              人身安全関連事案対策の推進
    50       「魅力的な地域をつくる」ための調査・研究事業                     「魅力的な地域をつくる」ための先行事例調査・研究
    114      地域の社会課題解決に資する起業者展開推進事業                     地域の担い手展開推進事業
    119      リモートワークを活用した官民共創による人流創出事業                  地方創生テレワーク推進事業
    134      地方創生特区推進事業費                                スーパーシティ構想等の推進に必要な経費
    163      沖縄振興交付金事業推進費                               沖縄振興交付金推進事業推進費
    168      沖縄北部連携促進特別振興対策特定開発事業推進費                    沖縄北部連携促進特別振興対策特定開発事業費
    271      安全・安心に関するシンクタンク機能の構築・運営                    安全・安心に関するシンクタンク機能の構築
    422      金融危機対応の円滑な実施                               金融危機対応の円滑な実施のための経費
    423      金融仲介機能強化事業                                 金融仲介機能の強化
    424      金融デジタライゼーション推進事業                           金融デジタライゼーション関連経費
    426      金融知識普及功績者表彰事業                              金融経済教育の推進
    429      金融サービス利用者保護推進事業                            金融サービス利用者保護の推進に必要な経費
    430      課徴金制度の施行                                   課徴金制度関係経費
    432      企業財務諸制度調査等事業                               企業財務諸制度の整備
    433      公認会計士試験実施事業                                公認会計士試験実施経費
    436      コーポレートガバナンス推進事業                            コーポレートガバナンスの更なる推進に係る事業費
    437      金融分野のサイバーセキュリティ対策向上事業                      金融分野におけるサイバーセキュリティ対策向上
    438      サステナブルファイナンス推進事業                           サステナブルファイナンス推進に必要な経費
    439      アカデミアとの連携強化事業                              アカデミアとの連携強化に必要な経費
    440      自然災害による被災者の債務整理支援事業                        自然災害による被災者の債務整理支援
    441      新興国に対する技術協力事業                              新興国に対する技術協力に必要な経費
    442      アジア諸国等との金融連携・協力事業                          アジア諸国等との金融連携・協力に必要な経費
    443      気候変動リスクをはじめとする新たなリスクへの対応                   気候変動リスクをはじめとする新たなリスクへの対応に必要な経費
    455      家計の安定的な資産形成推進のための制度周知・広報及び税制の調査・検証事業       家計の安定的な資産形成推進のための制度周知・広報及び税制の調査・検証
    461      エシカル消費の普及啓発                                エシカル消費の普及・啓発
    653      放射性物質環境汚染状況監視等調査に必要な経費                     放射性物質環境汚染状況監視等調査研究に必要な経費
    717      ICTアクセシビリティ推進事業(旧:デジタル活用共生社会推進事業、令和7年度要求)   ICTアクセシビリティ推進事業/(旧:デジタル活用共生社会推進事業)
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

実測(2026-08-25。`uv run python scripts/measure_jurisdiction_resolution.py`)
【→ **最終レビュー⚠️A**: 以下の転記中の「名称単位」小計(resolved/unresolved/
OBSOLETE_ORGANIZATION)と、未解決の名称一覧にある共管規則2件の行は、
要修正3(裁定B41)**修正前**の実測である。修正後の実測による訂正は
この転記の直後にある】:

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

**最終レビュー⚠️A(阻害扱い): 上記「名称単位」の小計(1465〜1469行)と、
未解決の名称一覧中の1498行目は2026-08-25時点(要修正3の修正前)の実測
である。** 要修正3(裁定B41。「規則」経路も共管を「・」で分割)の修正後に
`uv run python scripts/measure_jurisdiction_resolution.py`を再実行して
確認した(2026-08-26。以下は実測、pipeline-reportからの推測ではない):

~~resolved 4243 / unresolved 2274(OLD_MINISTRY 1995・
OBSOLETE_ORGANIZATION 276・NO_CANDIDATE 3)~~ → **再実行後: resolved 4269
(+26) / unresolved 2272(−2)(OLD_MINISTRY 1995・OBSOLETE_ORGANIZATION 274
(−2)・NO_CANDIDATE 3。後の2つは不変)。要修正3の修正により変化した。**

~~1498行目「2 OBSOLETE_ORGANIZATION 内閣府・公正取引委員会・…・
原子力規制委員会」(共管規則2件)~~ → **再実行後の出力にこの行は存在しない
(13機関×2件=26本の`law:jurisdiction`が個別に解決されたため)。**

(「名称単位…pipeline-report.json の law_jurisdiction_* と一致する」という
ラベル自体は今も正しい。再実行した出力の数字が実際に
`data/artifact/2026-08-26-law-jurisdiction-check/pipeline-report.json`の
`law_jurisdiction_*`と一致することを確認済み。詳細は`final-fix-report.md`
要修正3・5節)

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

### Ruling B31の壊し確認(修正ラウンド2。判定基準(a)(b))

**判定基準(a): `release`が再びソース取得日由来に戻ると、pytestが実際に落ちる。**
`src/jgkg/pipeline.py`の`release=out_dir.name`を一時的に
`release=max(fetched_on.values()).isoformat()`に戻し、
`test_run_same_day_releases_are_distinguishable_by_release_field`だけを実行:

```
$ PYTHONUTF8=1 uv run pytest tests/test_pipeline.py -q -k test_run_same_day_releases_are_distinguishable_by_release_field
F                                                                        [100%]
================================== FAILURES ===================================
_______ test_run_same_day_releases_are_distinguishable_by_release_field _______
>       assert release_a.release != release_b.release, (...)
E       AssertionError: 取得日が同じ2つのリリースのreleaseフィールドが衝突している(manifestだけではリリースを区別できない。Ruling B31違反)
E       assert '2026-08-01' != '2026-08-01'
E        +  where '2026-08-01' = PipelineReport(release='2026-08-01', ...).release
E        +  and   '2026-08-01' = PipelineReport(release='2026-08-01', ...).release
1 failed, 42 deselected in 1.59s
```

`out_dir`を`tmp_path / "2026-08-25"`と`tmp_path / "2026-08-26"`に変えても
`release`は取得日(fixtureの`FETCHED`。2026-08-01)しか見ないため、
意図どおり衝突して落ちた。`release=out_dir.name`に戻して再実行すると、
このテストを含め全緑に戻ることを確認した:

**同じ壊し方で、今回変更した他の`release`アサーションも個別に壊し確認した**
(ブリーフ「追加・変更したテストは、わざと壊して落ちることを実際に見せる」
は新規テストだけでなく変更したテストにも及ぶため):

```
$ PYTHONUTF8=1 uv run pytest tests/test_pipeline.py -q -k "test_run_records_a_date_per_source or test_cli_accepts_multiple_sources_and_writes_report"
FAILED tests/test_pipeline.py::test_run_records_a_date_per_source - AssertionError: リリース名がout_dirのbasenameになっていない: '2026-08-01'
FAILED tests/test_pipeline.py::test_cli_accepts_multiple_sources_and_writes_report - AssertionError: assert '2026-08-01' == 'out'
2 failed, 41 deselected in 1.47s
```

`build.py`の`manifest_version: int = 5`も一時的に`4`に戻し、変更した
`test_build.py`の2本を実行した(3本目の`test_read_manifest_treats_a_missing_version_field_as_1`
はこの既定値と無関係なので当然green のままだった):

```
$ PYTHONUTF8=1 uv run pytest tests/test_build.py -q -k "test_build_manifest_produces_version_5 or test_manifest_version_roundtrips_through_write_and_read or test_read_manifest_treats_a_missing_version_field_as_1"
FAILED tests/test_build.py::test_build_manifest_produces_version_5 - AssertionError: assert 4 == 5
FAILED tests/test_build.py::test_manifest_version_roundtrips_through_write_and_read - AssertionError: assert 4 == 5
2 failed, 1 passed, 11 deselected in 0.79s
```

いずれも元の値(`out_dir.name`・`5`)に戻して再実行し、全緑に戻ることを
確認した(コミット済みのファイルとの`git diff`が空であることも確認済み)。

```
$ PYTHONUTF8=1 uv run pytest tests/test_pipeline.py -q -k "test_run_same_day_releases_are_distinguishable_by_release_field or release"
....                                                                     [100%]
4 passed, 39 deselected in 1.08s
```

**判定基準(b): 引数なしの`build.sh`が既存リリースディレクトリに書けない。**
実際に**A/Bと全く同じ取得日の組**(houjin-bangou/ministry-codes/
rs-system=2026-08-23、egov-law=2026-08-24)を`--out-dir`なしで渡した
(このコマンドは、修正前なら`data/artifact/2026-08-24/`——保護対象の
全法人13.8GiB証拠——にそのまま書き込んでいた組み合わせそのものである):

```
$ bash scripts/build.sh --source houjin-bangou=2026-08-23 --source ministry-codes=2026-08-23 \
    --source egov-law=2026-08-24 --source rs-system=2026-08-23 \
    --corporations-scope payees --include-all-corporations
エラー: 既定の出力先 data/artifact/2026-08-24 には既に何らかのファイルがある
(既存リリースの疑い)。既定(--out-dir省略)のまま実行すると上書きしてしまうため
停止した。別のリリースとして残すなら --out-dir で別のパスを明示すること
$ echo $?
1
```

**パイプラインが1行も実行される前に(スキーマ生成すら始まる前に)拒否している**
——`data/artifact/2026-08-24/`の中身(`kg.nq`・`pipeline-report.json`・
`tdb2.tar.gz`の3ファイル)はこの実行の前後で一切変化していないことを
`ls`で確認した。

**正のコントロール(ガードが誤検出でないこと)**: 同じコマンドの`egov-law`
だけを実在しない日付(`2026-08-28`。レイクに無い)に変え、既定の出力先が
本当に新規(`data/artifact/2026-08-28/`はまだ存在しない)になるようにすると、
ガードは何も言わずに素通りし、スキーマ生成まで進んだ上で、**ガードとは
無関係の別の理由(該当日のegov-lawスナップショットがレイクに無い)で
失敗した**:

```
$ PYTHONUTF8=1 bash scripts/build.sh --source houjin-bangou=2026-08-23 --source ministry-codes=2026-08-23 \
    --source egov-law=2026-08-28 --source rs-system=2026-08-23 \
    --corporations-scope payees --include-all-corporations
== 鮮度監視(...) ==
鮮度監視(2026-08-25 基準): 追跡対象 3 ソース / 陳腐化 0 件
== スキーマ生成 ==
(...スキーマ生成の出力。省略...)
== パイプライン実行(検証を含む) ==
FileNotFoundError: egov-lawのスナップショットが無い: data\lake\egov-law\2026-08-28\laws.jsonl。 先にコネクタで取得する
$ echo $?
1
```

「既定の出力先 ... には既に何らかのファイルがある」という**ガード自身の
エラー文言は出ていない**。`data/artifact/2026-08-28/`はこの実行後も
作られていない(パイプラインが出力を書く前に落ちたため)。つまりガードは
「出力先が既に塞がっている」ときだけ発火し、出力先が本当に新規のときは
素通りする——判定基準(b)は誤検出(false positive)側も確認できた。

(このスキーマ再生成は`schema/generated/`を書き換えるが、決定的な生成の
ため常にコミット済みの内容と同一になる。`git status --short schema/generated/`
が2回とも空であることを確認済み——このラウンドで唯一触ってはいけない
ファイル群だが、実際には差分が残っていない。)

---

## 15. Phase 1 完了条件の判定

| 条件 | 判定 | 根拠 |
|---|---|---|
| (A) CQ1〜CQ10 に実データ・実エンドポイントで答えられる | **満たす** | §4(2026-08-25リリース。Fuseki実エンドポイントで全10本が非0件) |
| (B) 縦の接続スライスを双方向に辿れ、出典が付く | **満たす** | `tests/test_vertical_slice.py`(fixture、全ホップ往復)+ 実データ: CQ1(法令→府省)・CQ5(法令→事業→府省)・CQ4(法人→支出→事業→府省→法令。逆方向を明示ジョインで確認、2,021件)・CQ7(出典。graph/source/fetchedOn/licenseが1件で返る) |
| (C) 更新の一巡を実データで通し、2つ目のリリースを作れる | **満たす** | §5(`data/artifact/2026-08-26/`。据え置き3グラフ+新規2グラフ〔通常SHACL〕+houjin-bangou-payees〔バッチSHACL〕+serve.sh切替+新規回帰テスト。`graphs_validated=5`の内訳は本文参照) |

**Phase 1(計画B)の完了条件A・B・Cを実データで満たした。** 併せて
task-11-brief.mdの必須項目6〜10(RS年度整合・PAGE_LIMIT・
old-ministries.csv出典・EXTRACTION_FAILED内訳・内閣官房令実在)も
本記録(§6〜§11)で全て実データにより確認済み。詳細な経緯・気になる点は
`.superpowers/sdd/2026-08-23-phase1-vertical-slice-data-layer/task-11-report.md`
を参照。

**追記(A-4。2026-08-25)**: 上記(C)の実データ検証(§5)は、いずれも
要修正3(法令所管の`law:jurisdiction`欠落。26本)の**修正前**のコードで
作られたリリース(`2026-08-25`・`2026-08-26`)を使っていた。判定(C)自体
——一巡の機構(取得→差分検出→検証→切替→鮮度反映)が実データで動く
という結論——は変わらないが、**修正後のコードで一巡を実際に通したのは
今回(§16)が初めて**である。

---

## 16. A-4: 修正後コードによる一巡の再実行(初めて正しいリリース。`2026-08-25-corrected`)

要修正3の修正(A-2)後、その修正が実際の政府サーバからの新規取得・
carry-over・実Fusekiの全経路を通しても正しく効くことを確認するため、
`jgkg.fetch`によるe-Gov法令の実取得(このCLIの初の本番実使用)から
リリース構築・配置・CQ実行・`compare_releases.py`による前リリースとの
差分確認までを実データで一巡させた。詳細な経緯は
`.superpowers/sdd/2026-08-23-phase1-vertical-slice-data-layer/task-A4-report.md`
参照。ここでは礎定(A-4ブリーフ)が明示した5項目を転記する。

### 16.1 叩いたURLと回数(政府サーバへの礼儀の記録)

| URL | 回数 | 結果 |
|---|---|---|
| `https://laws.e-gov.go.jp/api/2/laws?limit=100&offset={0,100,...,9500}` | **96回**(ページング。offset 0刻み100、最終offset=9500) | 成功。全9,550件取得 |
| `https://rssystem.go.jp/files/2026/rs/1-1_RS_2026_基本情報_組織情報.zip` | **1回**(2026年度が公開されているかの確認) | 失敗(SPAフォールバック検出。`UnexpectedResponseError`)。2026年度は未公開と判断し、以降RSへの追加リクエストは行っていない |

合計97リクエスト。houjin-bangou・ministry-codesへの新規リクエストは0件
(既存スナップショット・参照表を流用)。並列実行はしていない。RS
2026年度probeの失敗は`fetch_group`内の`_get()`(zip署名検査)で発生し、
`lake.save`に到達する前に例外化するため、`data/lake/rs-system/`には
何も書き込まれていない(`ls`で実測確認済み)。

### 16.2 B31ガードの拒否出力

`--out-dir`を明示せずに実行(既定出力先が保護対象`data/artifact/2026-08-25`
と衝突):

```
$ bash scripts/build.sh --source houjin-bangou=2026-08-23 --source egov-law=2026-08-25 \
    --source rs-system=2026-08-23 --include-all-corporations --corporations-scope payees \
    --previous-release 2026-08-26
エラー: 出力先 data/artifact/2026-08-25 には既に何らかのファイルがある(既存リリース
または失敗したビルドの残骸の疑い)。上書きするなら --allow-overwrite を
明示すること。失敗したビルドのやり直しも --allow-overwrite を明示する
(既存リリースとの区別をディレクトリの中身だけでは判定できないため)
終了コード: 1
```

ガードは`mkdir`より前の判定なので拒否は即時かつ副作用が無い(実測:
拒否後も`data/artifact/2026-08-25/`の内容は変化していない)。その後
`--out-dir data/artifact/2026-08-25-corrected`を明示して実行した
(`--source ministry-codes=...`は`pipeline.py:1731`のヘルプ文言
「リポジトリにコミットした参照表は渡さない」に従い渡していない)。

### 16.3 carry-overの判定

`--previous-release 2026-08-26`で実行した`pipeline-report.json`の
`carried_over`:

```json
"carried_over": [
  "https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23"
]
```

houjin-bangouグラフのみが「差分検出により再生成をスキップされた」対象。
他の3グラフ(houjin-bangou-payees・ministry-codes・rs-system)は
recomputeされたが入力が変わらなかったため出力がバイト同一になった
(下記16.4のsha256一致)——「carried_overに載る」ことと「結果が同一で
ある」ことは別の仕組みである。ministry-codesは設計上そもそもcarry-over
の対象外(毎回再計算)。houjin-bangou-payees・rs-systemは`pipeline.py`の
依存関係定義上egov-lawの変化に依存するため、今回はcarry-over対象になら
ず再計算された(が入力自体は変わっていないので結果はバイト同一)。
「一部のソースだけ変化した」分岐が実データで実際に踏まれた——ただし
A-4ブリーフが想定していた「e-Gov法令とRSが両方新規」ではなく、RS 2026
年度が未公開だったため「e-Gov法令のみ新規」という1ソース変化になった。

### 16.4 CQ1〜10の結果

`scripts/serve.sh 2026-08-25-corrected`で配置し実行。**全10本が非0件で
回答**。行数・構造(変数名・出力形式)は§4と同一のため行内容は再転記せず、
値が変化した項目のみ示す:

| CQ | 行数 | 補足 |
|---|---|---|
| CQ1 | 1 | 厚生労働省令の所管=厚生労働省(§4と同じ答え) |
| CQ7 | 1 | `fetchedOn=2026-08-25`(egov-lawの新しい取得日を正しく反映。§4は`2026-08-24`) |
| CQ8 | 1 | `417M60000100021`の2026-04-01の版(provenance由来のカットオフでも同じ正答を再現) |
| CQ9 | 6,541 | §4(旧リリース2026-08-26)では6,517行だった(+24。16.5参照) |
| CQ10 | 5 | egov-law取得日=2026-08-25として正しく反映 |
| CQ2〜6 | §4と同数 | jurisdiction解決には依存しない経路のため変化なし |

### 16.5 compare_releases の差分(26本の予想との一致/不一致)

`uv run python scripts/compare_releases.py data/artifact/2026-08-26 data/artifact/2026-08-25-corrected`:

```
DIFFER https://jgkg.norr-tech.com/graph/egov-law/2026-08-24  (A: 140,430行 / B: 0行)
DIFFER https://jgkg.norr-tech.com/graph/egov-law/2026-08-25  (A: 0行 / B: 140,482行)
SAME   https://jgkg.norr-tech.com/graph/houjin-bangou-payees/2026-08-23  (113,616行、両者sha256一致)
SAME   https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23  (5,088行、両者sha256一致)
SAME   https://jgkg.norr-tech.com/graph/ministry-codes/2026-08-23  (40行、両者sha256一致)
DIFFER https://jgkg.norr-tech.com/graph/provenance  (40行、40行。値が違う——egov-lawの取得日が変わったため)
SAME   https://jgkg.norr-tech.com/graph/rs-system/2026-08-23  (558,768行、両者sha256一致)
残余行: A=0 / B=0
内容が一致しないグラフ: 3件(egov-law新旧2つの改名+provenance)
判定: 不一致あり(既定は失敗)
```

`compare_releases.py`はグラフ単位のハッシュ一致/不一致しか見ないため、
述語単位の実数は別に`kg.nq`へ直接`grep -c`した:

```
$ grep -c "def/law#jurisdiction>" data/artifact/2026-08-26/kg.nq
4243
$ grep -c "def/law#jurisdiction>" data/artifact/2026-08-25-corrected/kg.nq
4269
```

**+26。予想と一致した。** `pipeline-report.json`の集計値
(`law_jurisdiction_resolved`)も**別の測り方(kg.nqのトリプル行を数える
vs パイプラインが解決イベントを数える)で同じ4243→4269**になっている
(トートロジーではなく、独立した2つの測定が一致した):

| 指標 | 2026-08-26(旧) | 2026-08-25-corrected(新) | Δ |
|---|---|---|---|
| law_records | 9,547 | 9,550 | +3 |
| law_jurisdiction_resolved | 4,243 | 4,269 | **+26** |
| law_jurisdiction_unresolved | 2,274 | 2,272 | -2 |
| law_jurisdiction_extraction_failed | 13 | 13 | 0 |

**正直な限定**: 今回のegov-law再取得では法令総数自体も9,547→9,550(+3)
と実データが動いている(政府側の通常の更新。要修正3の効果とは別の変数)。
したがって「+26のすべてが要修正3の修正効果」とは断定しない——分離する
には修正後のコードを古いegov-lawスナップショット(2026-08-24)に対して
別途実行し比較する必要があり、今回はそこまでは行っていない。それでも、
**「予想された26という数字が、実際の比較で正確に再現された」という
事実は実測どおり成立している。**

`law_jurisdiction_unresolved_by_reason`(A-2以降の形)は新リリースに
存在し(`{"OLD_MINISTRY": 1995, "OBSOLETE_ORGANIZATION": 274,
"NO_CANDIDATE": 3, "AMBIGUOUS": 0}`)、旧リリース
(`2026-08-26/pipeline-report.json`)にはこのフィールド自体が無かった
(grep確認済み)。

## 17. C-3: ministry_succession結線の実測(2026-08-26)

C-1/C-2が抽出した18件の旧省庁→現存府省の対応(412CO0000000315の対応表)を
`pipeline.py`へ結線し、`law:jurisdiction`が旧省庁名を`AbolishedGovernmentOrgan`
(`succeededBy`で現在の後継を持つ)へ解決できるようにした。新たな政府サーバ
アクセスは0件(houjin-bangou 2026-08-23・egov-law 2026-08-25・
egov-law-data 2026-08-26のレイクスナップショットに対して`pipeline.run`を
直接実行。出力先はビルド成果物ではなく一時ディレクトリ)。

### 17.1 jurisdiction解決率の変化

| 指標 | 値 |
|---|---|
| law_records | 9,550 |
| law_jurisdiction_resolved(現存府省) | 4,269 |
| law_jurisdiction_resolved_abolished(AbolishedGovernmentOrgan、新設) | 1,995 |
| law_jurisdiction_unresolved | 277(OBSOLETE_ORGANIZATION 274・NO_CANDIDATE 3・OLD_MINISTRY 0・AMBIGUOUS 0) |
| law_jurisdiction_extraction_failed | 13 |
| graphs_quarantined | 0 |
| reference_violations(裁定1の和集合参照整合ゲート含む) | `[]` |

解決率(resolved + resolved_abolished ÷ 分類対象総数): **65.27%(4,269/6,541。
C-2以前の分類基準相当)→ 95.77%(6,264/6,541)。OLD_MINISTRYは1,995件→0件**
——team-leadの事前予想(65%→約96%)と一致。**1,995という数字は独立な
2つの測定で一致している**: 本表の`law_jurisdiction_resolved_abolished`と、
§16(C-3導入前の2026-08-25-correctedリリース)の
`law_jurisdiction_unresolved_by_reason.OLD_MINISTRY`——後者はC-3導入前に
「OLD_MINISTRYとして未解決」だった件数そのものであり、C-3後にそれが
すべて`resolved_abolished`側へ移ったことをトートロジーでなく裏付ける。

18機関すべてに`skos:prefLabel`・`org:abolitionDate`
(`2001-01-06`。412CO0000000315自身の`revision_info.amendment_enforcement_date`
から導出。手書きではない)・`org:succeededBy`が付くことを確認済み
(§17.2のCQ11実行結果も参照)。

### 17.2 CQ1・CQ5・CQ11を実データに対して実行(2026-08-26)

上記と同じ`kg.nq`(rs-systemは含まない。houjin-bangou/egov-law/
egov-law-dataのみ)に対して、C-3で追加・変更した3本のCQを直接実行した:

```
cq01-jurisdiction-of-ordinance.rq: 1行
  厚生労働省(6000012070001)。successor/successorNameは未束縛
  (焼き込んだ417M60000100021は現存府省を指すため、実データでも
  fixtureと同じく負のコントロール側になる)

cq05-ministry-of-basis-law.rq: 0行
  この実行にrs-system(budget:basisLaw/budget:ministryの源)を含めて
  いないため0件——CQ5の答えではなく、この実行の入力範囲による0件である
  (test_cq5_*のfixtureテストが答え自体は別途保証している)

cq11-succession-of-abolished-ministry.rq: 1,995行
  distinct AbolishedGovernmentOrgan数 = 11/18
  (労働省・厚生省・大蔵省・建設省・文部省・総理府・自治省・通商産業省・
  運輸省・郵政省・金融再生委員会。残り7機関
  〔北海道開発庁・国土庁・沖縄開発庁・環境庁・科学技術庁・経済企画庁・
  総務庁〕を発令機関とするe-Gov法令が、この9,550件の中に1件も無い
  ——18機関すべてが解決可能なことと、実際にそれらを引用する現行法令が
  データ中に存在するかは別の話であることの実例)
```

行数1,995は§17.1の`law_jurisdiction_resolved_abolished`と完全一致する
(SPARQL側とパイプライン集計側、独立な2つの経路が同じ数字に達した)。

**「11/18」の観察について(team-lead、2026-08-27)**: 残り7機関(北海道開発庁・
国土庁・沖縄開発庁・環境庁・科学技術庁・経済企画庁・総務庁)がいずれも
「庁」級の機関であることは偶然ではない——**庁級の機関は府省令の発令主体に
なりにくく、当時は総理府令が庁を覆う形で発令されていたため**、庁自身の
名前で発令された省令自体が実データに少ない(または存在しない)。これは
「継承マッピングの欠陥」ではなく**歴史的な発令実務の反映(データの事実)**
であり、18機関すべてが対応表上は解決可能であることと矛盾しない。

## 18. D-1: 公開リリースからの起動経路の実測(2026-08-28)

決定#42(サーバーレスコンテナ+起動時ダウンロード)の実行時経路そのものを、
**「外部の利用者としてふるまう」ことで実証した**。`data/artifact/`・`data/lake/`
は一切参照していない——取得は`scripts/run-from-release.sh`が公開リリースの
GitHub ReleasesのURLからのみ行い、展開先もダウンロード先も
job-tmpの作業ディレクトリ(`$WORKDIR`)に隔離した。

対象リリース: `2026-08-27-c3-succession-v3`
(https://github.com/nomhiro/japan-government-kg/releases/tag/2026-08-27-c3-succession-v3)。

### 18.1 取得したURLと実sha256(manifestの記録との一致)

```
https://github.com/nomhiro/japan-government-kg/releases/download/2026-08-27-c3-succession-v3/manifest.json
https://github.com/nomhiro/japan-government-kg/releases/download/2026-08-27-c3-succession-v3/tdb2.tar.gz
https://github.com/nomhiro/japan-government-kg/releases/download/2026-08-27-c3-succession-v3/kg.nq.gz
```

| 検査対象 | manifestの記録 | 取得物の実測 | 一致 |
|---|---|---|---|
| tdb2.tar.gz の sha256 | `8e9a053746e9d2bd85d44cc4ae0ede101be8d9794d6abf10cecf8ad4534ed616` | 同一 | ○ |
| kg.nq(展開後)の sha256(nquads_sha256) | `a86be52614ecf25678d0889e4d083aae0926b004fc9c585473fa9a38c7a71186` | 同一 | ○ |
| tdb2展開後の実サイズ | 449,227,816 バイト | 449,227,816 バイト | ○(バイト単位で一致) |

manifestの`git_commit`(`f1de9184200039d3f46b24f2ef042214afa370a2`)は、この検証を
実行したworktreeの`git rev-parse HEAD`と一致する——**成果物を検証するツール自体が、
その成果物を作ったコードそのもの**であることを確認済み(循環検証にならないよう、
検証はここまでローカルの`data/artifact/`を一度も経由していない)。

### 18.2 CQ1〜11の実行結果(件数)

新規に起動したFuseki(検証専用コンテナ、既存の`requirements-draft-fuseki-1`とは
別ポート・別コンテナ)に対して`scripts/run_cq.py`を実行:

| CQ | 行数 | 応答時間 | 備考 |
|---|---:|---:|---|
| cq01-jurisdiction-of-ordinance | 1 | 0.078秒 | successor/successorNameは未束縛(現存府省が発令機関) |
| cq02-ministry-budget-by-year | 1 | 3.047秒 | |
| cq03-recipient-expenditures-by-year | 13 | 0.094秒 | |
| cq04-money-trace-to-ministry-and-law | 2,033 | 8.750秒 | |
| cq05-ministry-of-basis-law | 5,680 | 8.391秒 | issuingOrgan/successor列も一部の行で束縛済み(例: 外務省) |
| cq06-unresolved-recipients-per-project | 8,151 | **149.875秒** | 突出して遅い。§18.6参照 |
| cq07-provenance-of-edge | 1 | 0.062秒 | |
| cq08-law-revision-as-of-date | 1 | 0.063秒 | |
| cq09-jurisdiction-resolution-status | 6,541 | 6.328秒 | |
| cq10-release-freshness | 6 | 0.032秒 | 5ソース分の行 |
| cq11-succession-of-abolished-ministry | 1,995 | 0.281秒 | |

(応答時間は`scripts/run_cq.py`が計測してstdoutに出したもの。裁定B25の
「使い捨てにしない」に合わせてここへ転記する。)

`全 11 本のCQが非0の答えを返した(完了条件A)`。**cq09=6,541・cq11=1,995は、
C-3実測(§17.1の`law_jurisdiction_resolved_abolished`)・C-4のローカルビルド実測と
完全に一致する**——ローカルでビルドしたものだけでなく、**公開リリースから
ダウンロードして展開しただけのFusekiが、同じ答えを返す**ことをこれで確認した。

### 18.3 測定した4つの時間とメモリ

| 項目 | 実測値 |
|---|---|
| ダウンロード時間 | 4秒(manifest.json + tdb2.tar.gz 44,088,732バイト≈42.1MiBのみ。**kg.nq.gzは含まない** — 下記の注参照) |
| 展開時間 | 4秒(`jgkg.serve`のsha256・Jenaバージョン照合を含む) |
| Fuseki起動〜最初のクエリ応答 | 6秒 |
| 合計コールドスタート(ダウンロード+展開+起動) | 14秒 |

**この14秒が測っている区間について、正直な限定**: `scripts/run-from-release.sh`は
既定(`FETCH_NQUADS=1`)でkg.nq.gzも取得してnquads_sha256を照合するが、
その区間(取得14,793,375バイト+gunzip+sha256計算)は`DOWNLOAD_SEC`の計測が
終わった**後**に走るため、上記のどの数字にも入っていない。**実行時
(コンテナ起動)が本当に必要とするのはtdb2.tar.gzだけ**なので、コンテナの
起動スクリプトとしての実測はこの14秒で正しいが、**このスクリプトを
そのまま人間が実行した場合の壁時計時間は、nquads照合を含めるとこれより
数秒〜十秒程度長くなる**(kg.nq.gz取得+展開+sha256の分。この検証では
実測を独立の項目として測っていない)。D-4で実際のコンテナに焼き込む際は
`FETCH_NQUADS=0`(tdb2.tar.gzの照合のみ)が実行時の既定として妥当と考える。
| メモリ(`docker stats`、cgroup) | 539.4 MiB |
| メモリ(`/proc/1/status` VmRSS/VmHWM、プロセス常駐) | 641,668 KB(≈626.6 MiB) |
| 参考: 展開後のTDB2実サイズ(manifest記録) | 449,227,816バイト(≈428.5 MiB) |

**常駐とページキャッシュの区別について**: cgroupのメモリ使用量(539.4 MiB)と
プロセスのVmRSS(626.6 MiB)の差、およびいずれもTDB2展開後の実サイズ
(428.5 MiB)を上回っている分は、JVMのヒープ/メタスペースの基礎消費と、
CQ1〜11実行でmmap経由で実際にページインされたTDB2ファイル領域が
プロセス常駐に含まれるため(起動直後だけを計測すればこれより小さいはずだが、
「11本のCQに答えられる状態でどれだけ使うか」の方が容量計画には実用的な
数値と判断し、CQ実行後の値を報告する)。

**Cloud Runのtmpfs落とし穴(実測できない部分の扱い)**: このマシンでの展開先は
実ディスク(Docker DesktopのWSL2バッキングディスク)であり、Cloud Runの既定の
一時ディスク(tmpfs)を直接観測することはできない。**プラットフォームが
tmpfsを使う場合、展開後サイズ(428.5 MiB)がそのままメモリ使用量に加算される
と考えるべき**(tmpfsのページはメモリそのものだから)。実ディスク上の
一時領域を使えるプラットフォームなら、上記の実測値(539.4〜626.6 MiB)が
そのまま上限に近い。**この差(428.5 MiBの有無)がプラットフォーム選定で
必要メモリの見積りを変える**、という数値的な根拠がこれで揃った。

### 18.4 わざと壊して落ちることを見せる(3件)

**(1) sha256が合わないtarballを渡すと起動を拒否する。** 取得済みの正常な
tarballを1バイトだけ改変したコピーを作り、同じ経路に通した:

```
manifestの記録: 8e9a053746e9d2bd85d44cc4ae0ede101be8d9794d6abf10cecf8ad4534ed616
改ざん後の実物 : 512ad108acc1ffbad453369f15e72879ddbd97bbea62f5cb2056077ddad4a171
```

素朴な比較(スクリプト第1段)がまず不一致を検出する。**さらに独立な第2段**
(`jgkg.serve`経由の`build.verify_manifest`。実際に`scripts/run-from-release.sh`が
呼ぶ本物のコード)も同じ入力に対して:

```
ValueError: 成果物のsha256が一致しない。
  manifest=8e9a053746e9d2bd85d44cc4ae0ede101be8d9794d6abf10cecf8ad4534ed616
  actual=512ad108acc1ffbad453369f15e72879ddbd97bbea62f5cb2056077ddad4a171
```

を投げて`exit 1`、配置先ディレクトリは作られない(`ls`で未存在を確認済み)。
この経路自体は`tests/test_serve.py::test_stage_release_refuses_a_corrupted_artifact`が
すでに(`tmp_path`配下の任意の`current/tdb2`という、data/artifact/以外の場所で)
固定しているため、D-1では新規のpytestは追加していない。

**(2) CQが0件を返したら失敗として扱われる。** 空の(0トリプルの)TDB2ストアに
対して同じFuseki設定で別コンテナを起動し、`scripts/run_cq.py`を実行:

```
### cq01-jurisdiction-of-ordinance.rq
形式: SELECT / 変数: ['ministry', 'ministryName', 'successor', 'successorName']
行数: 0 / 0.047 秒
**0件**
答えが返らなかったCQ: 1 本 -> ['cq01-jurisdiction-of-ordinance.rq']
完了条件A(CQに答えられること)を満たしていない
exit=1
```

**(3) TDB2は読み取り専用FSを開けない(既知の落とし穴の再確認)。** 展開済みの
TDB2ディレクトリのコピーを`:ro`で別コンテナにマウントすると、
`docker-compose.yml`のコメントが記録していたのと同じ例外を実際に再現した:

```
Caused by: java.nio.file.FileSystemException:
  /fuseki/databases/kg/tdb.lock: Read-only file system
```

一時ディスクが書き込み可能でありさえすれば問題にならないことを確認済み
(`scripts/run-from-release.sh`は`:ro`を付けていない)。

### 18.5 踏んだ落とし穴

**Windows Git Bashでの`MSYS_NO_PATHCONV`が2方向で矛盾する。** `docker run -v`は
コンテナ側パス(`/fuseki/config`)までホスト側絶対パスと誤認して変換してしまう
(`MSYS_NO_PATHCONV=1`が必要)。**しかし同じ変数をスクリプト全体にexportすると、
今度はcurlのホスト側絶対パス出力(`-o /c/Users/...`)の変換が止まり、
`curl: (23) client returned ERROR on write`で失敗する**(相対パスや
変数未設定なら同じ絶対パスで成功することを確認して原因を切り分けた)。
**解決: exportせず、`docker run`の行にだけインライン変数として渡す**
(`scripts/run-from-release.sh`に理由をコメントで明記)。この落とし穴は
Windows Git Bash特有で、実際のコンテナ内(Linux)では発生しない。

**新規に見つけた既存の欠陥(D-1と無関係)**: `tests/test_rdf_emit.py`に
2026-08-23由来の`ruff E402`(ファイル中盤の`# emit_budget`区切り直後に
`from pathlib import Path` / `from jgkg import uris` / `from jgkg.transform import rs`
がモジュール先頭以外に置かれていた)があり、D-1の`ruff check src tests scripts`
実行で初めて検出された。D-1のスコープ外の技術的負債だが、ゲートを満たすため
先頭のimport群へ統合した(別コミット)。

### 18.6 気になる点

- **cq06-unresolved-recipients-per-projectが149.875秒かかっている**
  (他は最大でも8.75秒)。8,151行という行数自体は他のCQと同程度なので、
  クエリの計算量(集計・分類のしかた)側の問題と見られる。プラットフォーム
  選定に直結する: 多くのサーバーレスプラットフォームの既定リクエストタイムアウトは
  30〜60秒程度で、150秒は超えうる。API層(D-2)がこのCQに相当する集計を
  同期リクエストで返す設計なら、cq06のクエリ自体の見直し(または非同期化)が
  D-2着手前に必要になる可能性がある——D-1の範囲では計測のみ行い、クエリの
  最適化はしていない
- ダウンロード・展開・起動の3段はいずれも数秒(合計14秒)で、決定#42の
  「起動時ダウンロード」方式のコールドスタートは実用上問題ない範囲に見える。
  ただし本番相当のネットワーク帯域・実プラットフォームのディスク特性
  (Cloud Runのtmpfs等)ではこの数字は変わりうる
- メモリは「CQを11本実行した後」の値。起動直後だけの値はこれより小さいはずだが、
  「実際に使われている状態でどれだけ使うか」の方をプラットフォーム選定の
  材料として優先した
- kg.nq.gzの取得・展開・sha256照合は行ったが、展開した`kg.nq`(175MB相当)自体は
  照合後に削除している(`scripts/run-from-release.sh`の既定動作)。ディスクに
  余裕があるため今回は行ったが、次回以降ディスクが厳しければ`FETCH_NQUADS=0`で
  tarball側の照合だけに絞れる
- この検証用コンテナ・作業ディレクトリは本報告のあと後片付けする
  (既存の`requirements-draft-fuseki-1`・`data/artifact/`・`data/lake/`には
  最初から最後まで触れていない)

**訂正(2026-08-28、§19参照)**: 上記の「合計コールドスタート14秒」は
**Fusekiが応答を返すまで**の時間であり、**索引(428.5 MiB)のページインは
含んでいない**。cq06のように大きい部分に初めて触るクエリは、この14秒の
「後」に別途ページフォルトのコストを払う(§19.3の実測: 175.250秒)。
プラットフォーム選定では両方を合算した数字を見る必要がある。

## 19. D-2: cq06の新レイテンシ実測とキャッシュ効果の発見(2026-08-28)

`budget:recipientMatchCategory`を結線したリリースを実測した
(`data/artifact/2026-08-28-d2-recipient-category-v2`。前リリース
`2026-08-27-c3-succession-v3`と同じ5ソース+houjin-bangou-payees。
`--previous-release`を指定し、carry-overの挙動も併せて観測した)。

### 19.1 トリプル数の変化(実測)

| 指標 | 値 |
|---|---|
| トリプル数(旧、manifest記録) | 810,133 |
| トリプル数(新、manifest記録) | **884,052** |
| 差分 | **+73,919**(見積り+74,000とほぼ一致。支出73,919件×1トリプル) |
| `git_dirty` | **false** |
| `git_commit` | `21caf13c1a31200597f6dcc9c7498e42a9bffacd` |
| `report_graph_mismatches` | **`[]`** |
| `reference_violations` | `[]` |
| `graphs_quarantined` | `0` |

(この数字を得るまでに1回、作業ツリーが汚れた状態でのビルドがあった
——team-leadが私のビルド中に別コミットを行ったため。**当該ビルド
〔`2026-08-28-d2-recipient-category`、末尾`-v2`無し〕は`git_dirty: true`
のため公開判断の根拠にしない**。作業ツリーを再度cleanにしてから
`-v2`として作り直したものが上表)

### 19.2 carry-overの検証(team-leadが事前に指摘した罠)

**`--previous-release`を渡したので、rs-systemのスナップショット自体は
不変(2026-08-23)だが変換コード(スキーマ)は変わった、というcarry-overの
罠に当たる可能性があった**(carry-overはスナップショットのハッシュだけを
見るため)。実測:

```
carried_over: [
  "https://jgkg.norr-tech.com/graph/houjin-bangou/2026-08-23",
  "https://jgkg.norr-tech.com/graph/egov-law/2026-08-25"
]
```

**rs-systemは入っていない**(=支出のグラフは再生成された)。ビルドログに
理由が明記されている:

```
警告: 前リリースの据え置き候補グラフ
  https://jgkg.norr-tech.com/graph/rs-system/2026-08-23
  がSHACL再検証に失敗した。carry-overを諦めて再生成する(Ruling B26)
```

**理由は`_GRAPH_DEPENDENCIES`でもD-2の変更が偶然避けたのでもない。**
`_validate_carried_graphs`(裁定B26(b)。Task 10修正ラウンド1)が、
据え置き候補を**現行のSHACLシェイプ**で再検証する既存の仕組みが働いた
——このシェイプは今回`recipientMatchCategory`をminCount 1にしたため、
`recipientMatchCategory`を持たない前リリースのrs-systemグラフはこの
再検証に落ち、carry-overを諦めて素通りせず再生成された。**「現行の
SHACLシェイプが前リリース当時より厳しくなった場合を検出する」という
このモジュールの元々のdocstring(2026-08-23由来)が想定していた状況が、
今回スキーマ進化として実際に起きた最初の例**。

### 19.3 cq06のレイテンシ: 149.875秒/175.250秒はクエリの問題ではなかった

**team-leadが実測を引き取り、同じFusekiに対してcq06を3回連続実行した**:

```
1回目: 8,151行 / 175.250 秒
2回目: 8,151行 /   0.812 秒
3回目: 8,151行 /   0.953 秒
```

**約200倍の差。原因はクエリの構造ではなくページフォルト(コールドキャッシュ)
だった。** cq06は(ファイル名のアルファベット順で)73,919件の支出データに
**最初に**触るCQで、cq01〜cq05は法令・府省・事業(いずれも規模が小さい)
しか触らない。索引の大部分(428.5 MiB相当)を初めてページインするコストが
cq06に集中して現れていた——旧クエリ(3重OPTIONAL)の**構造そのものが
遅かったわけではない**。

私自身も独立に確認した(team-leadの3回目の後、`scripts/run_cq.py`の
全CQ実行で。キャッシュは既に温まっている状態):

```
cq06-unresolved-recipients-per-project.rq: 8151行 / 0.750秒
```

行数(8,151)はD-1(§18.2)の旧クエリでの実測と一致し、他のCQの
行数(cq01=1・cq04=2033・cq05=5680・cq09=6541・cq11=1995)も新リリースで
不変であることを確認した——**推論から明示に変えても答えの実体は
変わっていない**ことの追加的な裏付け。

**追加確認: 旧クエリ(OPTIONAL推論)を同じ温まったインスタンスに対して
実行し、「材料化そのものの効果」と「キャッシュ状態の効果」を分離した**
(このタスクの完了報告前に、advisor指摘を受けて実施):

```
$ uv run python scripts/run_cq.py --endpoint http://localhost:3030/kg/sparql \
    --query-dir queries/cq --pattern 'legacy-cq06*.rq' --head 2
legacy-cq06-optional-inference.rq: 8151行 / 1.641秒
```

同じ(既に温まった)インスタンスで、旧クエリ=1.641秒、新クエリ=
0.750〜0.953秒。**約200倍の差(175.250秒→0.8秒台)はキャッシュ状態が
支配的要因であり、クエリを単一結合にしたこと自体が持つ効果は
約1.7〜2.2倍(1.641秒→0.750〜0.953秒)にとどまる。** 「materializationに
レイテンシ改善効果が無かった」わけではないが、**「cq06が遅かった主因は
クエリの複雑さだ」という当初の(誤った)診断を、この数字は裏付けない**
——正しくは「キャッシュが支配的要因、構造の単純化は控えめだが実在する
副次効果」。B42の脆さを直したという構造上の価値と、この控えめな
レイテンシ改善は両方、独立に成立する。

**裁定B55(team-lead、2026-08-28。要旨)**: 「他のCQは最大8.75秒なのに
cq06だけ150秒」という単発の観測から**クエリ固有の問題だと推論したのは
誤りだった**。**同じクエリを2回流して初めて、原因がクエリではなく実行順序
(何が最初にページインされるか)だと判別できた。** 1回の実測で構造上の
結論を出してはならない、という教訓。

**この訂正はD-2の価値を損なわない。** レイテンシ自体は
`recipientMatchCategory`の新設で「直っていない」(そもそも壊れていたのは
クエリではなくキャッシュの状態だった)が、**裁定B42が指摘した脆さ
(分類を不在から推論する構造そのもの)を直したことは独立に正しい**:

- 読み手が「何が無いか」から推論しなくて済む(公開オントロジーの明快さ)
- センチネルと実在しない法人番号を区別できないことが、値の名前
  (`sentinel_or_nonexistent_houjin_bangou`)自体から分かる
- 新旧クエリの突き合わせ(§19.2 = 裁定B54の`report_graph_mismatches`を
  再利用)で、将来のドリフトを検出できる

### 19.4 CQ1〜11の確認(完了条件A)

team-leadが確認済み、かつ私が独立に`scripts/run_cq.py`(全本・既定設定)で
再実行して確認した。**全11本が非0件**:

```
cq01: 1行 / cq02: 1行 / cq03: 13行 / cq04: 2033行 / cq05: 5680行 /
cq06: 8151行 / cq07: 1行 / cq08: 1行 / cq09: 6541行 / cq10: 6行 / cq11: 1995行
全 11 本のCQが非0の答えを返した(完了条件A)
```

### 19.5 実行時への影響(2点)

**(1) API層は起動時にキャッシュを温める必要がある。** D-1(§18.3)の
「合計コールドスタート14秒」は**Fusekiが応答を返すまで**の時間で、
**索引のページインを含んでいなかった**(上記の訂正注記参照)。起動直後の
最初のリクエストが実際には175秒待たされる、という利用者体験を防ぐには、
起動シーケンスに**ウォームアップクエリ**(索引の主要部分に触れる、
軽量な問い合わせ)を追加する必要がある——D-3(API層)の設計事項として
持ち越す。

**(2) プラットフォームの判断が一部逆転しうる。** D-1(§18.3)は
「Cloud Run既定のtmpfsはメモリを消費するので不利」と評価した。
**しかし「索引が最初からRAM(tmpfs)上にある」ことは、初回クエリの
速さという観点では有利にもなる**——実ディスクなら初回アクセス時に
ページフォルトで175秒相当を払うが、tmpfsなら(展開時点で既にメモリに
乗っているため)その代償が構造的に発生しない。**測る前は欠点だと
思っていたものが、利点でもあった。** メモリコスト(+428.5 MiB)と
コールドスタート時のレイテンシ、どちらを優先するかはD-5(プラットフォーム
選定)の判断事項として両方の数字を残す。

### 19.6 気になる点

- cq06に限らず、**他のCQも「そのCQが最初に触る領域」次第で同じ
  ページフォルト効果を受ける可能性がある**(cq04・cq05も対象が
  2,000〜5,700件規模で相対的に大きい)。今回はcq06だけを3回測ったが、
  ウォームアップの設計(D-3)では「どのCQが索引のどの部分を最初に
  温めるか」を意識する必要がある
- 稼働中のFusekiに`SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }`を直接投げると
  883,662件と出た。`manifest.json`の`triple_count`(884,052件。生N-Quads行数)
  より390件少ない。本表は`manifest.json`の値(既存の全測定と同じ基準)を
  正式な数値として採用した——`COUNT(*)`は和集合デフォルトグラフでの
  数え方(重複除去の単位等)が生N-Quadsの行数と一致しない場合があると
  見られるが、D-2の変更由来という証拠はなく、詳細は未調査(今回のスコープ外)
- `_validate_carried_graphs`がスキーマの厳格化を理由に据え置きを拒否する
  という挙動(§19.2)は今回**初めて実際に発生した**。裁定B26(b)自体は
  2026-08-23時点で「将来のスキーマ厳格化を検出する」ためのものだったと
  docstringに書かれていたので、**約5日後にその想定シナリオが現実に
  起きた**ことになる
- **ビルド時の新旧照合(`_expenditure_category_mismatches`)が追加する
  コストを、厳密な前後比較では切り出せていない。** v1/v2いずれのビルドも
  「パイプライン(取得済みスナップショット→kg.nq、検証含む)」段が
  2353秒/2392秒(2回の独立ビルドで近い値であり、安定している)。
  直前のリリース`2026-08-27-c3-succession-v3`自身のbuild.logは保存
  されておらず、**同一コミット・同一corporations-scopeでのD-2適用前**の
  数字が無い。参考として、別タスク(Task 10修正ラウンド2、2026-08-27、
  トリプル数817,982・houjin-bangou-payeesグラフあり=corporations-scope
  payeesらしい)ではこの段が422〜458秒だった——**間接的な類似はあるが、
  同一コミットでのA/Bではないため、この差(+約1900秒)を「新チェックの
  正味コスト」として主張することはしない。** 新チェックはrdflib(純Python
  実装のSPARQLエンジン)で884,052トリプルに対するGROUP BY集計を2本
  (新旧クエリ)実行するので、大きなコストが乗ることは構造的にありうるが、
  厳密な切り分けは今回のスコープ外とする

---

## 20. D-3: API層を実データ・実HTTPで初めて通した実測(2026-08-28)

D-3のAPI層は667件のテストが緑でmainに入っていた。**実Fuseki
(884,052クアッド)に対して初めて動かした**ときの実測。

### 20.1 温めが効いていなかった(裁定B60)

`docker restart` 直後(**ラベル領域は真に未読**):

```
warm_up()                :   4.734 秒
search('厚生', limit=10)  : 111.219 秒   ← 温めた後の最初の検索
```

温まった後:

```
search('厚生')   : 0.312 秒
search('国土')   : 0.625 秒
search('デジタル'): 0.609 秒
search('年金')   : 0.703 秒
```

**温めは支出述語(`budget:Expenditure`/`project`/`recipientMatchCategory`)を
温めていたが、検索が触るのは `skos:prefLabel` を全型横断で走る別の領域だった。**
`warm_up()` が4.734秒で終わったこと自体が証拠 —— §19.3が175秒を測った同じ
領域が4.734秒で済んだのは、**その領域が既に常駐していた**から。

**1本の普通の語がラベル領域全体をページインする**(111秒の後、別の語も
0.6〜0.7秒)。`_build_search_query` の `ORDER BY ?label ?entity` が
**LIMITの前に全件の計算を強制する**ため。

### 20.2 温めの語の費用(裁定B67。温まった状態、limit=1)

```
空文字列(採用)   1.437秒 / 1.204秒   ← 5つのOPTIONALの領域も全件分温まる
一致0件の語      0.234秒 / 0.250秒
普通の語「厚生」  0.281秒 / 0.453秒
1文字「省」       0.266秒 / 0.266秒

skos:prefLabel の総数: 109,005
```

**空文字列の追加費用は約1秒。** その代わりに `law:lawNum`・
`org:prefectureName`・`org:cityName`・`budget:fiscalYear`・
`budget:ministry/skos:prefLabel` の領域も温まる —— これらは
`/search` の要約導出と `/entity/{id}` が実際に読む領域である。

**controllerは当初 `warm_up()` が22.313秒かかるのを見て「全件ソートが
無駄なコスト」と診断したが誤り。** 22.313秒は**その時点で索引が部分的に
コールドに戻っていた**ため(直前に全テストスイートが走ってメモリ圧が
かかっていた)。**温めは一度払えば終わりではなく、メモリ圧で減衰する。**

### 20.3 検索は1リクエストあたりラベル全走査である(規模の限界)

**109,005件の `skos:prefLabel` を毎リクエスト全走査する**
(`ORDER BY` が全件計算を強制)。温まった状態で0.25〜0.45秒。
**データが増えると線形に悪化する。** 全文索引(Jena text / Lucene)は
Phase 2 の課題。

### 20.4 §19.3の175秒はバインドマウント越しの数字である(裁定B62)

`docker-compose.yml` は TDB2 索引を `./data/artifact/current/tdb2`
(**Windowsパスのバインドマウント**)から読んでいる。
**§3の発見7が「Docker Desktop for Windowsのバインドマウントは実質
ネットワークファイル共有」を実測している** —— 仕様§6.3が
「TDB2はmmapを使うのでネットワークファイル共有に置くな」と警告した
置き方そのものである。

**§19.3・§20.1の初回読みの数字は、配備先の代表値ではない。**
発見7が測ったのは**索引構築のスループット**(書き込み中心)であり、
**その倍率を読み取りに転用することはできない**(controllerが一度
「58倍だから配備先なら数秒」と書いたが撤回した)。
**配備先の構成での初回読みは未実測 —— D-6で測る。**

### 20.5 `%` を含むIRIと、到達可能性(裁定B69・観察O10)

`/def/` ではなく `/id/` 名前空間で、IRIにパーセントエンコードを含む型:

| 型 | 総数 | `%`含み | 入る辺 | 出る辺 | 検索可 | APIから到達可 |
|---|---|---|---|---|---|---|
| `LawRevision` | 9,550 | 7,795 | **0** | **0** | いいえ | **いいえ** |
| `UnresolvedReference` | 771 | 742 | 0 | 771 | いいえ | はい |
| `AbolishedGovernmentOrgan` | 18 | 18 | 11 | 18 | はい | はい |

**通常の遷移(検索・関係パネル)で踏むのは 742 + 18 = 760 件。**
残る 7,795 件は `/entity/{id}` を直接叩く経路でのみ到達する。

**測り方の注意**: エンティティ詳細は**関係の両方向**を出すので、
**目的語側だけを数えると `UnresolvedReference` を「到達不可」と誤る**
(controllerが一度そう出した)。**入る辺と出る辺の両方**を数える。

### 20.6 `LawRevision` はグラフの辺を1本も持たない(観察O10)

```
type                     9,550件  [uri]     law#LawRevision
lawId                    9,550件  [literal] "505AC0000000067"    ← 辺ではない
revisionStatus           9,550件  [literal] "CurrentEnforced"
amendmentEnforcementDate 9,550件  [literal] "2026-05-21"
amendmentLawNum          7,795件  [literal] "令和七年法律第三十九号"

IRIを目的語に持つ LawRevision: 0 件
```

IRIの形は `.../id/law/505AC0000000067/20260521_<改正法令番号のエンコード>`
——**法令IDはIRIのパスに埋まっているだけで、`.../id/law/505AC0000000067`
(法令そのもの)への辺は存在しない。**

**法令 → 改正 も、改正 → 法令 も、辺を辿って行けない。**
`cq08-law-revision-as-of-date.rq` は `lawId` のリテラルで絞るため動く。

**設計書§9.1の近傍サブグラフとパス探索(D-4)は辺を辿る機能なので、
改正は原理的に一度も現れない。** 辺を足すのはオントロジーとKGの変更に
なるためPhase 2の課題(観察O10)。**「なぜアプリに改正が出ないのか」を
次に調べる人は、ここを読めば同じ調査を繰り返さなくてよい。**

### 20.7 その他の実測(この節で確定した数字)

- `budget:recipientMatchCategory` の値は**プレーンリテラル**:
  `resolved` 56,607 / `sentinel_or_nonexistent_houjin_bangou` 9,982 /
  `bundled` 7,326 / `unresolved` 4。**合計 73,919 = 支出件数と完全一致**
  ——すべての支出がちょうど1つの分類を持ち、4分類が厳密に分割している
- 公開オントロジー(`/def/all.owl.ttl`)の `owl:AllDisjointClasses` は
  **メンバー7個**(`Agent` `Concept` `Event` `MonetaryItem` `Place`
  `UnresolvedReference` `Work`)= **排他21組**。設計書どおり
- `/def/all.shacl.ttl` は **16 NodeShape すべてが `sh:closed`**。
  実クラス16 ↔ シェイプ16 で1:1(残る10 `owl:Class` は列挙型とその値)
- `schema/generated/*.ttl`(10本)= `site/def/*`(10本)= 本番URL が
  **全件バイト一致**。拡張子なしエイリアス5本も一致。
  **HTMLだけはCloudflareがボット検出スクリプト(938バイト)を挿入するため
  一致しない**(裁定B65)
