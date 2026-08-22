# Japan Government Knowledge Graph (JGKG)

日本政府が公開する資料・データを、統一オントロジーに基づくナレッジグラフ(KG)として統合し、政府情報の「つながり」を誰でも検索・探索できるようにする公共財プロジェクト。

> [!IMPORTANT]
> **現在の状態: 設計フェーズ。実装は未着手です。**
> このリポジトリには現時点で調査レポートと設計書のみが含まれます。動くコードはまだありません。

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

一次データはすべて政府公開データです。ソースごとの利用規約は機械可読メタデータとしてKGに保持し、アプリ表示時に出典と規約を自動表示する設計です。Phase 1 で使うソースはいずれも商用・再配布可(政府標準利用規約準拠、またはCC BY相当)です。

## ライセンス

- **コード**: [MIT License](LICENSE)
- **ドキュメント・データ**: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)

デジタル庁自身のOSS公開(コードMIT / 文書CC BY 4.0)と同じ慣行に揃えています。

> [!NOTE]
> ライセンス選定は設計書 §13 の残論点であり暫定です。実装開始前に確定します。

## English

**Japan Government Knowledge Graph (JGKG)** — a public-good project to integrate Japanese government open data into a knowledge graph under a unified ontology, with a visualization app on top.

**Status: design phase. No implementation yet.** This repository currently contains research reports and the design specification only (in Japanese).

The core premise: the Japanese government publishes authoritative *join keys* (law IDs, corporate numbers, address registry IDs) and many individual APIs, but no cross-source joined graph exists. Questions like "which corporations received expenditures under a given law, from which ministry's budget line" cannot be answered with any combination of existing government offerings.

Design highlights: a six-axis event-centric upper ontology, competency-question-driven validation, LinkML as the single source of truth for schemas, named-graph replacement semantics for updates, and provenance on every edge.

Code is MIT licensed; documentation and data are CC BY 4.0.
