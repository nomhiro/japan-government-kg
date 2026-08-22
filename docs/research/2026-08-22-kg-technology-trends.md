# オントロジーエンジニアリング/KG構築 技術動向調査(2024〜2026)

> 調査日: 2026-08-22。対象: 日本政府公開データ(法令XML・統計・PDF)のオントロジー定義→KG化→可視化アプリ提供システムの技術選定基礎資料。

## 1. LLM支援のKG構築パイプライン

**現状の結論**: KG構築はルール/統計ベースからLLM駆動へパラダイムシフトが完了しつつある。手法は (a) 事前定義オントロジーにLLM抽出を従わせる「スキーマ誘導型」と (b) LLMにスキーマ自体を発見させる「オープン型」に二分され、実運用では圧倒的に前者が主流([LLM-empowered KG construction survey, arXiv:2510.20345](https://arxiv.org/abs/2510.20345))。完全自動のontology learningはまだ研究段階で、人手レビュー前提のドラフト生成が現実解。ツール成熟度: Neo4j LLM Knowledge Graph Builderは2025年にcommunity summaries・カスタムプロンプト・local/global retrieverを追加し活発に開発中([Neo4j blog](https://neo4j.com/blog/developer/llm-knowledge-graph-builder-release/))。LangChainのllm-graph-transformer、LlamaIndexのKG抽出も実用水準。構造化出力層ではInstructor(Pydantic検証+自動リトライ、回復率95%超)とBAML(Schema Aligned Parsingで壊れた出力からも復元)が本番品質([比較記事](https://medium.com/@rajkundalia/how-baml-brings-engineering-discipline-to-llm-powered-systems-983c06d31bf8))。

**本件への示唆**: 法令XMLは既に構造化されているため、KGの骨格(法令・条・項・改正関係)は決定的パースで構築すべきで、LLMは使わない。LLMの出番は (1) PDF・白書等の非構造文書からのスキーマ誘導抽出、(2) オントロジー初期ドラフト生成、(3) 関係候補の提案。抽出はBAML/Instructor+Pydanticで型安全にし、SHACL等での検証+人手レビューをパイプラインに組み込む。

## 2. GraphRAGとKGの関係

**現状の結論**: Microsoft GraphRAGはOSSとして活発、LazyGraphRAG(インデックスコストをベクトルRAG並みに削減)は2025年6月からMicrosoft Discovery/Azure Local経由で利用可、OSSライブラリへの統合は2026年前半時点でまだ作業中([MS Research](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)、[GitHub Discussion](https://github.com/microsoft/graphrag/discussions/1490))。HippoRAG 2はPersonalized PageRankでマルチホップ検索を10〜30倍安価に実現([比較](https://medium.com/graph-praxis/graphrag-vs-hipporag-vs-pathrag-vs-og-rag-choosing-the-right-architecture-for-your-knowledge-graph-a4745e8b125f))。重要な整理: GraphRAGが作る「検索用グラフ」(LLMが自動生成、使い捨て可)と「正式なオントロジーに基づくKG」(キュレーション・ガバナンス対象)は別物であり、2026年の本番構成はベクトル+グラフのハイブリッドをクエリ種別でルーティングするのが主流。

**本件への示唆**: 本件の主デリバラブルは「正式KG+可視化」なので、KG本体をオントロジー準拠で構築し、GraphRAGは後付けの検索/QA層として分離する。正式KGをGraphRAGの入力(entity graph)として再利用すれば二重構築を避けられる。GraphRAGツールの出力をそのまま正式KGにしないこと。

## 3. データモデル選択(RDF vs プロパティグラフ)

**現状の結論**: 使い分けの合意は明確化した — 「外部データセット・標準識別子・独立ドメインを跨いで結合するならRDF、アプリ内の操作的トラバーサルと開発速度ならLPG」([Neo4j自身の整理](https://neo4j.com/blog/knowledge-graph/rdf-vs-property-graphs-knowledge-graphs/)、[解説](https://deonvdv.com/blog/rdf-vs-property-graphs))。ISO GQL(ISO/IEC 39075:2024、2024年4月発行、SQL以来のISO DB言語)によりLPG側も標準化が進み、Neo4jはCypher 25でGQL必須機能の大半に準拠、2026.02からデフォルト化([Neo4j GQL conformance](https://neo4j.com/docs/cypher-manual/current/appendix/gql-conformance/))。RDF-starはメタデータ(出典・時点)の一級市民化を実現しRDF 1.2に取り込まれつつある。両立はAWSのOneGraph構想が先行し、Neptune AnalyticsはRDFグラフへのopenCypherクエリを2024年8月からサポート([AWS](https://aws.amazon.com/about-aws/whats-new/2024/08/amazon-neptune-analytics-opencypher-queries-graphs))。

**本件への示唆**: 政府データは「標準URI・外部連携(e-Gov/Wikidata/統計LOD)・長期保存」が本質的要件でRDFの強みがそのまま効く。一方、可視化アプリの開発体験はLPGエコシステムが優位。決め手は公開形態: LODとして外部公開するならRDF必須、アプリ内完結ならLPGで十分。出典・改正時点の注釈にはRDF-star(RDF案)またはエッジプロパティ(LPG案)を使う。

## 4. オントロジー記述・管理ツール

**現状の結論**: Protégéは5.6.8(2025年9月)で保守継続、WebProtégéが協調編集用、TopBraid EDGがエンタープライズガバナンス向け([Protégé](https://protege.stanford.edu/)、[比較](https://www.ovaledge.com/blog/ontology-management-tools))。ただしトレンドは「スキーマをコードとして管理」へ移行: LinkMLが単一YAMLソースからOWL/SHACL/JSON Schema/Pydantic/SQL DDL/GraphQL/ドキュメントを生成でき、Git+CIでスキーマ進化を管理するのが現代的ベストプラクティス([LinkML論文 arXiv:2511.16935](https://arxiv.org/pdf/2511.16935)、[LinkML docs](https://linkml.io/linkml/faq/why-linkml.html))。LinkML作者らのSPIRESはLLM抽出とLinkMLスキーマを直結する手法も示している([arXiv:2304.02711](https://arxiv.org/pdf/2304.02711))。

**本件への示唆**: LinkMLをスキーマのソース・オブ・トゥルースにするのが本件に最適 — 同一定義からRDF用(OWL/SHACL)とアプリ用(JSON Schema/Pydantic=LLM抽出の型定義)を両方生成でき、RDF案/LPG案どちらに転んでも資産が生きる。Protégéは生成OWLの検証・閲覧用に限定。

## 5. グラフDB/トリプルストアの現状

- **Neo4j**: LPGの事実上の標準。マネージド(AuraDB)あり。サードパーティ情報では6.0系GA・AuraDB Pro $65/GB/月とされる([KnodeGraph](https://knodegraph.com/blog/best-knowledge-graph-database-2026/))。
- **Amazon Neptune**: RDF(SPARQL)とLPG(Gremlin/openCypher)両対応の唯一の主要マネージド。Bedrock Knowledge BasesのGraphRAG統合あり([AWS docs](https://docs.aws.amazon.com/neptune/latest/userguide/intro.html))。
- **GraphDB (Ontotext)**: RDF+OWL推論の商用有力。Freeエディションあり。
- **Apache Jena Fuseki**: 軽量OSS SPARQLサーバ。小〜中規模の定番。
- **QLever**: 高速OSS SPARQLエンジン。Wikidata全量(70億トリプル)を約40GB RAMで扱い、2025年夏からin-place update対応、WikidataのWDQS後継候補([QLever benchmarks](https://github.com/ad-freiburg/qlever/wiki/QLever-performance-evaluation-and-comparison-to-other-SPARQL-engines)、[Wikidata評価](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/WDQS_backend_update/WDQS_backend_alternatives))。
- **Oxigraph**: Rust製軽量組込みRDFストア。小規模・組込み用途。
- **KuzuDB**: **2025年10月に開発停止が確定**。GitHubリポジトリはアーカイブ済み、Kùzu Inc.はApple買収と報道され、コミュニティフォーク(bighorn、Ladybug)が発足([The Register](https://www.theregister.com/2025/10/14/kuzudb_abandoned/))。新規採用は避けるべき。
- **FalkorDB**: 低レイテンシ特化のLPG。GraphRAG用途で台頭([FalkorDB](https://www.falkordb.com/blog/best-database-for-knowledge-graphs-falkordb-neo4j/))。

**本件への示唆**: RDF路線ならGraphDB(推論必要時)/Fuseki(小規模PoC)/QLever(大規模・読取中心の公開エンドポイント)。LPG路線ならNeo4j一択に近い。AWS前提ならNeptuneで両様式を保険にできる。KuzuDBは除外。

## 6. エンティティ解決・ID体系

**現状の結論**: LLMによる「semantic entity resolution」が2025年の主流トレンド — 長コンテキストで複数レコードを一括マッチングし、KGGEN等はLLM誘導クラスタリングで表層一致を超えた同一性判定を行う([Towards Data Science](https://towardsdatascience.com/the-rise-of-semantic-entity-resolution/))。ただしコスト面からblocking(候補絞り込み)+LLM判定の二段構成が実務標準([arXiv:2602.05708](https://arxiv.org/pdf/2602.05708))。URI設計はW3C GLD Working Groupのベストプラクティス(`https://{domain}/{type}/{concept}/{reference}`、技術非依存・コンテンツニュートラル・永続性はポリシーの問題)とEUの永続URIガイドラインが依然として規範([W3C GLD](https://www.w3.org/2011/gld/wiki/223_Best_Practices_URI_Construction)、[EU指針](https://interoperable-europe.ec.europa.eu/sites/default/files/document/2015-05/d2.1.2_training_module_2.3_persistent_uri_design_and_management_v1.00_en.pdf))。日本固有: 組織の名寄せは**法人番号**がIDアンカーで、gBizINFOが名寄せツール(法人名+所在地→法人番号)とCSV/JSONデータを提供([gBizINFO](https://info.gbiz.go.jp/tools/nayose/index.html))。RDFでの提供は現在確認できない。

**本件への示唆**: (1) 組織は法人番号、法令はe-Gov法令ID/法令番号を正準IDにし、自前URIはその上に被せる(例: `https://{domain}/id/law/{法令ID}`、`/id/org/{法人番号}`)。(2) 名寄せはgBizINFO名寄せツール+文字列blocking+LLM判定の三段。(3) URIは最初に設計を固める — 後から変えられない唯一の要素。

## 7. 可視化

**現状の結論**: 2026年の実務則は「解析機能重視ならCytoscape.js、大規模WebGL描画ならSigma.js」。Canvas系(Cytoscape.js等)は3,000〜5,000ノードで性能限界、Sigma.jsはWebGLで10万ノード級([PkgPulse比較](https://www.pkgpulse.com/guides/cytoscape-vs-vis-network-vs-sigma-graph-visualization-2026)、[学術比較 PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12061801/))。G6(AntV)はCanvas系で中規模向け、Gephi LiteはSigma.jsベースのブラウザ版Gephiとして探索用に有用。UXでは「hairball(全体グラフの毛玉表示)」が明確なアンチパターンとされ、(a) 検索起点でサブグラフを展開、(b) パス探索・推論経路のハイライト、(c) 自然言語→クエリ変換+プレビュー、(d) コミュニティ検出でのフィルタ、が推奨パターン([研究動向](https://www.emergentmind.com/topics/interactive-visual-knowledge-graphs))。

**本件への示唆**: 「グラフ全体を見せる」設計は避け、検索ボックス起点→エンティティ詳細→近傍サブグラフ展開→パス探索、というUXを基本にする。レンダラは規模拡大を見込みSigma.js(React連携可)を第一候補、グラフアルゴリズム(最短路・中心性表示)が要件ならCytoscape.js併用。

## 8. 公共部門KGの標準

**現状の結論**: データセットメタデータはDCAT 3(2024年8月W3C勧告)/DCAT-AP 3.0.1(2025年10月、EU標準として各国ポータルが実装)が確立([DCAT-AP政策文書](https://interoperable-europe.ec.europa.eu/sites/default/files/file-visibility/resource/2025-11/national_peer-learning-policy-dcat-ap.pdf))。schema.orgへの公式マッピングもJRCが提供([DCAT-AP to Schema.org](https://ec-jrc.github.io/dcat-ap-to-schema-org/))。法令ドメインではELI(European Legislation Identifier)オントロジーとAkoma Ntoso(OASIS LegalDocML)が国際標準で、両者のマッピング研究も進み、国横断legal KGの基盤とされる([ACM論文](https://dl.acm.org/doi/10.1145/3614321.3614327))。日本ではデジタル庁のGIF(政府相互運用性フレームワーク)とIMI共通語彙基盤(コア語彙)が対応物で、2025年3月にも説明資料が更新されている([IMI](https://imi.go.jp/goi/)、[デジタル庁GIF資料](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/c1bdb4a2-850f-48ec-a938-a8369f820ac1/d47def21/20250325_policies_development_management_outline_03.pdf))。e-Gov法令APIはv2(2025年3月、JSON化・時点指定検索)が利用可能。

**本件への示唆**: 車輪の再発明をせず、(1) データセット記述=DCAT-AP準拠(日本のDCAT-AP適用も視野)、(2) 法令オントロジー=ELI+Akoma Ntosoの構造を参考に日本法令(法令-条-項-号、改正、委任関係)をモデル化、(3) 組織・住所等=IMIコア語彙/GIFデータモデルに整合、(4) 外部連携=Wikidata/schema.orgへのsameAsリンク。これで将来の国際連携・検索エンジン露出も確保できる。

---

# 推奨技術スタック2案(2026年時点)

**対立軸: 「標準準拠・外部連携・長期資産」(案A) vs 「開発速度・アプリUX・GraphRAGエコシステム」(案B)**

## 案A: RDF中心スタック(LOD公開・長期保存重視)

| レイヤ | 選定 |
|---|---|
| スキーマ管理 | **LinkML**(Git管理、CIでOWL/SHACL/JSON Schema/Pydantic生成)+ Protégéで検証 |
| 語彙 | DCAT-AP、ELI参考の独自法令オントロジー、IMIコア語彙、SKOS(用語集)、RDF-star(出典・時点注釈) |
| ストア | **GraphDB Free/SE**(推論要)or **Fuseki**(PoC)→ 公開SPARQLは**QLever**(大規模・読取) |
| 取込 | 法令XML→決定的変換(Python/RML)、PDF→LLM+**BAML/Instructor**(LinkML由来Pydanticスキーマ)→**SHACL検証**→人手レビュー |
| ER/ID | 法人番号・e-Gov法令IDアンカーの永続URI(W3C GLD方式)、blocking+LLM名寄せ |
| 可視化 | SPARQL→REST API層→**Sigma.js**(検索起点サブグラフUX) |

利点: URI永続性・W3C標準・Wikidata/EU連携・SHACLによる品質保証。政府データの「公共財」性格に最適。
欠点: 開発人材が薄い、GraphRAG統合は自前実装、アプリ層とのインピーダンスミスマッチ。

## 案B: プロパティグラフ中心スタック(アプリ提供速度重視)

| レイヤ | 選定 |
|---|---|
| DB | **Neo4j**(Aura or self-host、Cypher 25=GQL準拠) |
| スキーマ管理 | LinkMLで論理モデル定義→Neo4j constraints+ドキュメント生成(オントロジーは軽量運用) |
| 取込 | 法令XML→Cypherバルクロード、PDF→**Neo4j LLM KG Builder**/LangChain llm-graph-transformer |
| RAG | Microsoft GraphRAG or HippoRAG 2(正式KGを入力に再利用) |
| ER/ID | ノードプロパティに法人番号・法令IDを保持(URIは持たない) |
| 可視化 | Neo4j Bloom(社内)+ **Sigma.js/react-force-graph**(公開アプリ) |

利点: 立ち上がり最速、LLM抽出・GraphRAG・可視化のエコシステムが最も厚い、採用しやすい人材プール。
欠点: 外部LOD連携・標準準拠が弱く、後からのRDF化はマッピング工数が発生。ベンダーロックイン。

**折衷案**: AWS前提なら**Amazon Neptune**(OneGraph路線: RDFで格納しopenCypherでも操作)が両軸のヘッジになる。またハイブリッド(正式KG=RDFで管理し、可視化/RAG用にLPGへ一方向ETL投影)は実務でよく採られる構成。

**判断の目安**: 本件が「政府公開データの二次公共財(LOD)」を目指すなら案A、「まず動く可視化アプリで価値実証」なら案Bで開始し、LinkMLでスキーマを持っておくことで将来の案A移行余地を確保する — どちらの場合もLinkML採用とURI/ID設計の先行確定が共通の後悔しない打ち手。
