# Japan Government Knowledge Graph (JGKG)

日本政府が公開する資料・データを、統一オントロジーに基づくナレッジグラフ(KG)として統合し、政府情報の「つながり」を誰でも検索・探索できるようにする公共財プロジェクト。

> [!IMPORTANT]
> **このプロジェクトは日本国政府とは無関係です。** 日本国政府が公開するデータを第三者が構造化したものであり、**政府による公式なデータセットではありません。** 一次データの出典は各名前付きグラフに機械可読な形で保持しています。判断の根拠には必ず一次資料をご確認ください。

> [!NOTE]
> **現在の状態: Phase 0(データレイヤー基盤)の完了条件 9件のうち 5件。テスト115件。**
> オントロジー(LinkML → OWL/SHACL)、出典付きスナップショット、名前付きグラフでの出力、SHACL検証ゲート、CQ(適格性質問)テストとCIは動きます。
>
> **一方で、実行系を一度も動かしていません。** 成果物ビルド(`build.sh`)と Fuseki での提供、実データでのパイプライン実行は未実施で、TDB2の実サイズ・府省の突合率・実行時間という**実測すべき3つの数字がありません**。コードとテストはありますが「動くと思っているが確かめていない」状態です。
>
> **公開エンドポイントはありません。** 識別子の名前空間は `https://jgkg.norr-tech.com/` に確定しましたが、解決(dereference)は未実装です。
>
> 詳細は **[進捗状況](docs/status.md)** に、できていないことも同じ精度で書いてあります。

## なぜ作るのか

**政府は結合キーを配っているが、結合済みグラフは誰にも渡していない。**

権威ある識別子は整備・公開されています — 法令ID/法令標準XML、法人番号、町字ID(アドレス・ベース・レジストリ)、氏名突合モデル。しかしそれらのキーで横断結合されたグラフは公開されていません。政府提供物の到達点は「個別APIによる単一ソースの検索・取得」です。

| 政府提供物でできること | できないこと |
|---|---|
| 法令条文の検索・取得(法令API v2) | 法令 ↔ 予算・支出 ↔ 所管組織 の横断接続 |
| 統計表の取得(e-Stat API) | 統計指標と政策・予算事業の接続 |
| 住所の正規化(ABR + `abr-geocoder`) | 正規化した住所を軸にした横断結合 |
| 補助金・行政手続の自然言語検索(デジタル庁公式MCP 2本) | 「ある法令に基づく支出がどの法人にいくら流れたか」の追跡 |

例えば「ある法令の根拠に基づく支出が、どの省庁の予算科目から、どの法人にいくら流れたか」は、政府提供物のどの組み合わせでも辿れません。各APIが独立し、共通の識別子体系で結合された層が存在しないためです。

## 何を作るのか

2層構成です。

1. **データレイヤー** — 収集(コネクタ群)→ 生データレイク → 正規化・抽出 → エンティティ解決 → オントロジー準拠KG
2. **可視化アプリ** — 検索起点でエンティティとその関係を探索できるWebアプリ

| Phase | 内容 |
|---|---|
| Phase 0 | URI/ID設計、LinkMLスキーマ基盤、収集フレームワーク、コアマスター(府省・法人・地域) |
| Phase 1 | 法令と資金の骨格 + 縦の接続スライス「法令 → 所管府省 → 予算事業 → 支出先法人」 |
| Phase 2 | 各ドメインの深化(国会審議・パブコメ・官報・裁判例 / 調達・EDINET)+ 人物・組織レイヤー |
| Phase 3 | PDF非構造層のLLM抽出、GraphRAGによる自然言語質問、統計指標・地理空間 |

## 設計の要点

- **本体はオントロジーとKG。アプリはその検証装置** — 先行事例調査で死んだのは *使われないエンドポイント* であり、生き残ったのは *更新が業務に埋め込まれたKG*(EU CELLAR、英 legislation.gov.uk、統計LOD)。投資の中心はオントロジー設計と更新機構に置く
- **上位オントロジーは6軸のイベント中心設計** — 誰が / 何を / どこで / いつ / いくらで / 何について。政府データのほぼ全ての関係が「いつの時点で真か」を持つため、時点情報を失うエッジを作らない
- **コンピテンシー質問(CQ)で妥当性を判定** — 「KGが答えられるべき質問」を先に書き、SPARQLテストとして持つ。CQに答えられないオントロジーはアプリが動いても不合格
- **識別子設計を最優先で固定** — 欧州ELIの前例どおり、識別子と語彙はトリプルストアより長生きする。URI体系はPhase 0で確定し以後変えない
- **更新は名前付きグラフの置換で行う** — 追記しない。訂正・削除・遡及改訂が特別な仕組みなしに反映され、再取得さえできれば常に正しい状態に収束する
- **全エッジに出典(provenance)** — 出典を持たない事実をKGに入れない。どの一次資料の何日取得分に基づくかを常に辿れる

## ドキュメント

### 設計書
- [Phase 0+1 設計書](docs/superpowers/specs/2026-08-22-japan-government-kg-design.md) — 現在の設計。Phase 2以降は対象外
- [要求詳細化ドラフト](docs/2026-08-22-requirements-draft.md) — 設計に至る要求整理と意思決定の記録

### 調査レポート
- [政府公開データソースカタログ](docs/research/2026-08-22-government-data-sources.md) — 35エントリ(データソース34件 + 語彙・設計基盤1件)、URL検証済み
- [政府API/MCP提供状況](docs/research/2026-08-22-government-api-mcp-landscape.md) — デジタル庁公式MCP・ベース・レジストリ・ガバメントAI「源内」の現状と差別化分析
- [オントロジー/KG技術動向 2024-2026](docs/research/2026-08-22-kg-technology-trends.md) — LLM支援KG構築、GraphRAG、RDF vs プロパティグラフ、可視化
- [政府KG先行事例と教訓](docs/research/2026-08-22-government-kg-precedents.md) — 国内外の事例が生き残った/死んだ理由
- [スキーマ単一ソース技術選定の比較](docs/research/2026-08-22-schema-tooling-comparison.md) — LinkML vs 手書きOWL/SHACL vs SHACL単一ソース等5案の比較、公共部門の実際の慣行
- [AzureでのRDFホスティング](docs/research/2026-08-22-azure-rdf-hosting.md) — Azureにマネージドトリプルストアが無いことの確認、選択肢の比較とコスト、TDB2のストレージ要件
- [Neptuneの正体とOSS RDFストア選定](docs/research/2026-08-22-neptune-and-oss-rdf-stores.md) — NeptuneとBlazegraphの関係の実際、Wikidataが選んだもの、OSS 6製品の比較

## 技術スタック(設計上の選定)

| レイヤ | 選定 |
|---|---|
| スキーマ管理 | LinkML(単一定義から OWL/SHACL/Pydantic/JSON Schema を生成) |
| ストア | Apache Jena Fuseki(公開読取は規模到達時に QLever を検討) |
| パイプライン | Python(rdflib, pySHACL, LinkML) |
| API層 | FastAPI |
| フロント | React + Vite + Sigma.js |
| 実行環境 | docker-compose |

## データソースと利用規約

一次データはすべて政府公開データです。ソースごとの利用規約は機械可読メタデータとしてKGに保持し、アプリ表示時に出典と規約を自動表示する設計です。Phase 1 で使う4ソースはいずれも「公共データ利用規約(第1.0版)」(PDL1.0。CC BY 4.0と互換)に準拠し、商用・再配布可です(一次資料で確認済み。旧称「政府標準利用規約」は2024-07-05にPDL1.0へ改訂され廃止されています)。

## KGをダウンロードして使う

ビルド済みのKGは [GitHub Releases](https://github.com/nomhiro/japan-government-kg/releases) から配布します(公開の仕組みは `scripts/publish-release.sh` / `src/jgkg/publish.py`)。各リリースには3つの資産が付きます: `kg.nq.gz`(N-Quads本体)・`tdb2.tar.gz`(Jena TDB2の索引済みデータ)・`manifest.json`(トリプル数・グラフ一覧・各ソースの取得日・各資産のsha256)。リリースノートに出典表示・ライセンス・sha256を全量載せています。

### N-Quadsから読む(どのRDFストアでも読める。長く使えるのはこちら)

```sh
gunzip kg.nq.gz
# 任意のトリプルストア(Fuseki以外でも)にN-Quadsとしてロードする
```

`tdb2.tar.gz` はJenaのバージョンに縛られますが、`kg.nq.gz` は標準のN-Quads形式なので、将来別のRDFストアに載せ替えたくなった場合にはこちらが本体になります。

### TDB2から読む(即起動できるが**Jena 6.2.0に固定される**)

```sh
tar xzf tdb2.tar.gz
# Jena 6.2.0 の Fuseki にこの tdb2/ ディレクトリを指させて起動する
```

**注意**: TDB2のオンディスク形式はJenaのバージョンに紐づきます。このリポジトリが配布するTDB2成果物は Jena 6.2.0 で構築したものなので、別バージョンのJena/Fusekiでは読めない可能性があります(`scripts/serve.sh` は配置前にJenaバージョンの一致を照合します)。バージョンに縛られたくない場合はN-Quads経路を使ってください。

いずれの経路でも、読み込んだ後は同じSPARQLエンドポイントとして使えます(`queries/cq/` のコンピテンシー質問を参照)。ダウンロードした資産のsha256は `manifest.json` およびリリースノートに記載の値と照合できます。

## ライセンス

- **コード**: [MIT License](LICENSE)
- **ドキュメント・データ**: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)

デジタル庁自身のOSS公開(コードMIT / 文書CC BY 4.0)と同じ慣行に揃えています。

スキーマは `license: https://creativecommons.org/licenses/by/4.0/` を宣言しており、生成した OWL/SHACL に `dcterms:license` として焼き込まれています。**変更するには再生成が必要です。**

## English

**Japan Government Knowledge Graph (JGKG)** — a public-good project to integrate Japanese government open data into a knowledge graph under a unified ontology, with a visualization app on top.

**Not affiliated with the Government of Japan.** This is a third-party structuring of data published by the Japanese government; it is **not** an official government dataset. Provenance for every source is retained in machine-readable form in named graphs.

**Status: 5 of 9 Phase 0 completion criteria met — 115 tests passing.** The ontology (LinkML to OWL/SHACL), provenance-bearing snapshots, named-graph emission, a SHACL validation gate, and competency-question tests with CI all work. **However, the runtime path has never been executed:** artifact builds, Fuseki serving, and pipeline runs on real data are all untried, and the three required measurements (TDB2 index size, ministry match rate, run time) do not exist. **No public endpoint.** The identifier namespace is fixed at `https://jgkg.norr-tech.com/`, but dereferencing is not implemented. See [docs/status.md](docs/status.md) for what is and is not done. Design documents and research reports are in Japanese.

The core premise: the Japanese government publishes authoritative *join keys* (law IDs, corporate numbers, address registry IDs) and many individual APIs, but no cross-source joined graph exists. Questions like "which corporations received expenditures under a given law, from which ministry's budget line" cannot be answered with any combination of existing government offerings.

Design highlights: a six-axis event-centric upper ontology, competency-question-driven validation, LinkML as the single source of truth for schemas, named-graph replacement semantics for updates, and provenance on every edge.

Code is MIT licensed; documentation and data are CC BY 4.0.
