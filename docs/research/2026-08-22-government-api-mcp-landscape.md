# 日本政府のAPI/MCP提供状況調査(2026-08-22)

> 調査目的: データ収集手段として政府提供のAPI/MCPが使えるか、既存の政府提供物との差別化を判断する。
> 公式(go.jpドメイン / digital-go-jp organization)と第三者製を厳密に区別している。

## 1. 公式MCP提供の有無 — 結論

**「公式に存在するが、いずれもサンプルコードであり、KG構築で必要な主要データソースは1つもカバーしていない」**

デジタル庁公式GitHub organization(`github.com/digital-go-jp`)にMCPサーバーが2本公開されている。

| リポジトリ | 対象データ | Stars | 最終更新 | ライセンス |
|---|---|---|---|---|
| [jgrants-mcp-server](https://github.com/digital-go-jp/jgrants-mcp-server) | Jグランツ(補助金電子申請)公開API | 50 | 2026-04-06 | MIT |
| [administrative-procedures-mcp](https://github.com/digital-go-jp/administrative-procedures-mcp) | 行政手続等の棚卸調査結果(令和6年度、約75,000件) | 69 | 2026-08-12 | MIT |

Jグランツ版は `search_subsidies` / `get_subsidy_detail` / `get_subsidy_overview` / `get_file_content` / `ping` の5ツールを提供し `https://api.jgrants-portal.go.jp/exp/v1/public` をラップ。行政手続版は `list_datasets` / `inspect_dataset` / `query_records` / `summarize_records` を提供し[デジタル庁公式note](https://digital-gov.note.jp/n/n56aaf580bfb6)で告知されている。

**重要な区別**: 「公式に公開されている」ことと「本番サービスとして提供されている」ことは別軸。両リポジトリは公式organizationからの公開であることに疑いはないが、いずれも「本実装は技術検証を目的としたサンプルコードです」と明記し、安定性・継続的メンテナンスについて無保証を宣言している。行政手続版はさらに「ローカルまたは管理された単一利用者での技術検証を対象」と範囲を限定。**公式提供の実験であり、SLAを伴う本番APIではない。**

### 主要データソースには公式MCPが存在しない

以下はいずれも確認した範囲では公式MCPが存在しない(確認範囲: go.jpドメインおよび digital-go-jp organization、2026-08-22時点)。

- 法令(e-Gov法令API)
- e-Stat / 統計 — [e-Stat API公式ページ](https://www.e-stat.go.jp/api/)にMCP・AIエージェント・LLM連携の記述は一切なし(API機能はVersion 3.0、2019年7月提供開始のまま)
- ベース・レジストリ(アドレス・法人)
- EDINET(金融庁)、gBizINFO(経産省)
- 国会会議録・国立国会図書館

### 政府のAI/LLM向けデータ提供方針 — ガバメントAI「源内」

MCPそのものではなく**内部向けAI基盤**として動いている。全府省庁約18万人規模で本格実証中で、政府共通データセットとして官報79年分・法令・白書・国会会議録・質問主意書などをAI活用可能な形に整備([デジタル庁資料 2026-02](https://www.cas.go.jp/jp/seisaku/gskaigi/ebpm/dai1/shiryo8.pdf)、[2026-05](https://www.digital.go.jp/assets/contents/node/information/field_ref_resources/fc155eba-e83d-4ecf-9c6a-a3c855e2e7b3/d0d53b25/20260528_news_genai_outline_01.pdf))。ガバメントクラウド上の閉域網で運用。

2026-04-24に[源内はOSS公開](https://digital-gov.note.jp/n/n84aeba282e60)された([genai-web](https://github.com/digital-go-jp/genai-web) 554 stars、[genai-ai-api](https://github.com/digital-go-jp/genai-ai-api) 344 stars、MIT / 文書CC BY 4.0)。ただし**公開対象はコードと開発テンプレートであり、政府共通データセット自体の外部提供は確認できなかった**。

方針文書として[DS-920 生成AIの調達・利活用ガイドライン(2026-06-12)](https://www.digital.go.jp/assets/contents/node/information/field_ref_resources/decb64eb-f26e-41cb-8d37-f3dd173108b8/59054b35/20260612_resources_standard_guidelines_guideline_01.pdf)、機械可読性基準として [machine_readability_rule](https://github.com/digital-go-jp/machine_readability_rule) があるが、いずれもルールであってデータではない。

## 2. 公式API一覧

### 法令系

| 名称 | URL | 提供状況 | 形式 |
|---|---|---|---|
| 法令API Version 2 | https://laws.e-gov.go.jp/api/2/swagger-ui | 本番(2025-03-19リリース) | XML、JSON(一部は試行版で仕様変更の可能性あり) |
| XML一括ダウンロード | https://laws.e-gov.go.jp/bulkdownload/ | 本番 | XML(`all_xml.zip` 全法令で約315MB。**分野別・更新日別の分割取得も可**) |

**告示API・通知通達API・中間APIの現況**: [プロトタイプ公開テストのAPI仕様書(令和6年12月12日)](https://www.digital.go.jp/assets/contents/node/information/field_ref_resources/0ac7897f-acd6-47c6-a579-48339d4805e0/8849d4f4/20241218_news_laws-digital-hackathon_api-specification-document_02.pdf)が最後に確認できる一次情報。**本番提供の告知も、公開テスト終了の明示的な告知も確認できなかった**。根拠は[お知らせページ](https://laws.e-gov.go.jp/news/)に2026年の告知が皆無であること、[法令データドキュメンテーション](https://laws.e-gov.go.jp/docs/)に3APIの記載がないこと。なおドキュメンテーションサイトはα版で「必ずしも常にアップデートされているとは限らず」と自己申告しており、v1しか記載がないことをv2非本番の証拠にはできない(v2は2025-03-19のリリース告知で本番と確定)。

### ベース・レジストリ

[第1次公的基礎情報データベース整備改善計画(2025-06-13 閣議決定)](https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/816ebeda-f081-4b18-b593-20fd12eb19a9/6e8cdb91/20250613_plan_for_development_and_improvement_of_public_basic_information_database_outline_03.pdf)がロードマップの一次情報。[公式ページ](https://www.digital.go.jp/policies/base_registry)は2026-07-21改定と記載しているが単一ソースで裏取りできていない。

| 対象 | 状況 | 提供元 |
|---|---|---|
| アドレス・ベース・レジストリ | データ提供中(町字・街区・住居・地番マスター等)。全面展開はFY2030目標 | [レジストリカタログ](https://catalog.registries.digital.go.jp/rc/dataset/)、CSV(UTF-8) |
| 法人ベース・レジストリ | [2026年3月 利用開始](https://www.cao.go.jp/bunken-suishin/teianbosyu/doc/r04/tb_r4fu_99digi_144.pdf)(主に行政機関向け) | デジタル庁 |
| 告示のベース・レジストリ | **FY2026末 提供目標**(官報デジタル化と連動)。未提供 | デジタル庁・法務省等 |
| 不動産ベース・レジストリ | FY2029以降 | 開発中 |
| 法人番号 / 財務諸表 / 法令 / 文字情報 | 既存DBを指定して運用中 | 国税庁 / EDINET / e-Gov / 文字情報技術促進協議会 |

**関連公式ツール(本設計で活用できるもの)**:
- [abr-geocoder](https://github.com/digital-go-jp/abr-geocoder) — Go、165 stars、2026-08-18更新。住所正規化
- [kanjikana-model](https://github.com/digital-go-jp/kanjikana-model) — 119 stars。氏名の漢字・カナ突合
- [mojxml2geojson](https://github.com/digital-go-jp/mojxml2geojson) — 226 stars。登記所備付地図→GeoJSON
- [abr-postcode](https://github.com/digital-go-jp/abr-postcode) — 8 stars

注意: `opendataapi.jp` や `geospatial.jp` でも町字マスターが配布されているが、これらはgo.jpドメイン外の第三者再配布。一次取得はレジストリカタログから行う。

### 統計・横断系

| 名称 | URL | 提供状況 | 形式 |
|---|---|---|---|
| e-Stat API | https://www.e-stat.go.jp/api/ | 本番(Version 3.0、2019-07〜) | XML / JSON / CSV |
| 統計LOD | https://data.e-stat.go.jp/lodw/ | 稼働中だがデータ更新は停滞の疑い | RDF、SPARQL、CC BY 4.0 |
| ジャパンサーチ | https://jpsearch.go.jp/ | 本番・活発(2026-08-20時点で322DB・32,790,663件) | RDF / SPARQL |
| e-Gov APIカタログ | https://api-catalog.e-gov.go.jp/info/ja/apicatalog/list | **掲載38件** | 各API依存 |
| Japan Dashboard | https://www.digital.go.jp/resources/japandashboard | 2025-07-10公開、約700指標。2026-04-24に地方財政ダッシュボード追加 | 画面+DL |

APIカタログ38件の主なもの: 不動産情報ライブラリAPI(国交省)、法人番号システムWeb-API(国税庁)、企業情報API・情報提供REST API(gBizINFO系)、e-Stat API、DIPS API、官公需情報ポータル検索API、文化遺産オンライン検索API、職業情報Web-API(厚労省)。

その他の公式アセット: [policy-dashboard-assets](https://github.com/digital-go-jp/policy-dashboard-assets)(103 stars)、[lawqa_jp](https://github.com/digital-go-jp/lawqa_jp)(法令4択QAデータセット、276 stars、Public Data License v1.0、RAGパイプライン検証用途を明記)。

## 3. 第三者製MCP一覧(すべて非公式)

以下はすべてコミュニティ・個人・民間による非公式実装。lobehub / smithery / glama / mcp.so 等のレジストリ掲載は公式性の根拠にならない。star数・最終更新は2026-08-22時点。

| 名称 | ラップ対象 | Stars | 最終更新 | 評価 |
|---|---|---|---|---|
| [tax-law-mcp](https://github.com/kentaroajisaka/tax-law-mcp) | e-Gov法令API + 国税庁通達 | 94 | 2026-06-18 | 実用水準に最も近い。通達まで含む |
| [labor-law-mcp](https://github.com/kentaroajisaka/labor-law-mcp) | 労働・社会保険関係法令 | 61 | 2026-03-03 | 実用的だがやや停滞 |
| [cygkichi/estat-mcp-server](https://github.com/cygkichi/estat-mcp-server) | e-Stat API | 20 | 2025-04-19 | 実質メンテ停止 |
| [edinet-mcp](https://github.com/ajtgjmdjp/edinet-mcp) | EDINET(XBRLパース含む) | 17 | 2026-08-17 | 活発 |
| [japan-tariff-mcp](https://github.com/qlitre/japan-tariff-mcp) | 関税率検索 | 9 | 2026-08-08 | 活発だがニッチ |
| [japan-data-mcp](https://github.com/Izyuusya/japan-data-mcp) | e-Stat+法人番号+不動産取引価格+インボイス | 9 | 2026-03-05 | 複数API統合型。小規模 |
| [japan-gov-mcp](https://github.com/Agentic-governance/japan-gov-mcp) | 30以上の省庁API | 4 | — | 網羅性は最大だが検証不足 |
| [EDINET DB](https://edinetdb.com/developers) | EDINET+gBizINFO+法人番号+Wikidata | — | — | 商用リモートMCP(SaaS)。稼働実績はベンダー自身の主張で第三者検証なし |
| `egov-law-mcp` 系(複数)、`law-diff-mcp` | e-Gov法令API | すべて0 | 2026-01〜07 | 実質個人の習作 |

国会会議録の単独MCPは確認できなかった(アグリゲータの一部機能としてのみ)。

**全体傾向**: star数100を超えるものが1つもない。政府APIラッパーMCPは供給過剰・品質不足で、依存先として選べる成熟実装が存在しない。

## 4. 差別化の分析

### 核心: 政府は「結合キー」を配っているが、「結合済みグラフ」は誰にも渡していない

政府は権威ある識別子を公式に整備・公開している — 法令ID/法令標準XML、法人番号、町字ID/ABR、氏名突合モデル。**しかしこれらのキーで実際に横断結合されたグラフは公開されていない。** 政府提供物の到達点は「個別APIによる単一ソースの検索・取得」であり、ソース横断の結合・名寄せ・ナレッジグラフには踏み込んでいない。キーはあるがグラフがない — ここがKGプロジェクトの埋めるべき空白。

### オントロジー/RDF/KGの新規動向 — 2025〜2026年に実質的な新展開なし

- **統計LOD**: SPARQL・RDFダンプは稼働中だが、告知は2025-09の停止メンテナンス以外に見当たらず、データ更新告知は2018〜2020年および2024-03に留まる。新規展開なし、更新停滞の疑い
- **ジャパンサーチ**: 活発(2026-08-20に金沢市埋蔵文化財センター連携追加)。ただし文化資源ドメインに限定され、法令・予算・統計には接続しない
- **法令標準XML**: 構造化されているがRDFではなく、他ドメインへのリンクを持たない
- **アドレス・ベース・レジストリ**: CSVのマスターデータでRDF/オントロジーとしては提供されていない

### 源内との関係 — 需要の証明であって競合ではない

源内の政府共通データセット整備(官報79年分・法令・白書・国会会議録・質問主意書)は、まさにソース横断のAI-Readyデータ統合そのもの。**政府自身が内部でこれを必要としている事実は方向性を強く裏付ける。** 同時にそれは閉域網の府省庁職員向け環境で外部から利用できない。しかも構成する生データは個別には公開されている — 政府は「公開されている素材を内部向けに統合した」のであって、統合成果物を外部提供したわけではない。

### 政府提供MCP/AI経由の「できること」と「できないこと」

**できること**: 補助金の自然言語検索(公式Jグランツ MCP)、行政手続75,000件の自然言語検索・集計(公式行政手続MCP)、法令条文の検索・取得(非公式MCPまたはAPI直叩き)、統計表の取得(e-Stat API)、住所正規化(ABR+abr-geocoder)。

**できないこと**: 法令 ↔ 予算・支出 ↔ 所管組織 ↔ 統計指標 の横断接続。例えば「ある法令の根拠に基づく補助金が、どの省庁の予算科目から、どの地域にいくら支出され、対応する統計指標がどう動いたか」は、政府提供物のどの組み合わせでも辿れない。各APIが独立し、共通の識別子体系で結合された層が存在しないため。組織・予算については、そもそも機械可読な権威データセット自体が法令・統計に比べて薄い。

## 5. データ収集手段としてMCPは適切か — 結論: 主系統としては不適切

バルク取得・冪等な再実行・スナップショット保全という3要件に対してMCPは構造的に噛み合わない。

1. MCPは対話的・クエリ単位の設計で、大量網羅取得を前提としない。ページネーションの完全性保証やレジューム機構が仕様上ない
2. HTTPキャッシュ意味論(ETag / If-Modified-Since / Last-Modified)がツール境界で失われ、差分取得と冪等性の担保が困難
3. LLMをループ内に含むため非決定的で、同一入力に対する同一出力が保証されない。スナップショットの再現性と正面から衝突
4. 公式MCP 2本は「技術検証目的のサンプルコード」で無保証。第三者製はstar 100未満・メンテ不安定。**どちらも収集パイプラインの依存先にできない**

**推奨する収集経路(すべて直接API/バルク)**:
- 法令: `all_xml.zip` 一括DL(約315MB)でスナップショット取得 + 法令API v2で差分更新。分野別・更新日別の分割取得がスナップショット運用に適合
- 統計: e-Stat API v3.0。統計LODのSPARQL/RDFダンプは更新停滞を前提に補助的利用
- アドレス: レジストリカタログからCSV一括取得。`abr-geocoder` をローカル名寄せに組み込む
- 企業: EDINET API、gBizINFO、法人番号システムWeb-API
- 文化資源: ジャパンサーチSPARQL

**MCPの正しい使いどころは2つ**: ①収集ではなく探索・検証・デモの層として(オントロジーが実データに合うかを対話的に確かめる)。②**構築したKG側をMCPで提供する** — 政府が単一ソースMCPしか出せていない(しかもサンプル止まり)状況で、横断結合済みKGをMCPとして提供できればそれ自体が明確な差別化になる。

## 補足: 確認できたこと / 確認できなかったこと

**確認できなかった(=不明。存在しないとは断定していない)**:
- 告示API・通知通達API・中間APIの本番提供の有無、公開テスト終了の告知
- 源内の政府共通データセット自体の外部提供の有無
- 公的基礎情報データベース整備改善計画の2026-07-21改定の内容(公式ページ記載のみで裏取り不能。閣議決定として確定しているのは2025-06-13版)

**確認した範囲では存在しない(確認範囲: go.jpドメイン、digital-go-jp organization、2026-08-22時点)**:
- 法令・e-Stat・ベース・レジストリ・EDINET・gBizINFO・国会会議録の公式MCPサーバー
- 統計LOD・ジャパンサーチ以外の政府提供オントロジー/RDF/KG(2025〜2026年の新規取組)
- ソース横断で結合済みの政府提供ナレッジグラフ
- 国会会議録の単独第三者製MCP

いずれも非公開の検討状況を否定するものではない。
