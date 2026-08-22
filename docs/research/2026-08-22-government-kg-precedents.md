# 政府・公共データKG化 先行事例カタログ

> 調査日: 2026-08-22。生死判定は一次ソースを直接確認したもの。

## 1. EU/欧州

### CELLAR(EU出版局のRDFリポジトリ) — 【稼働中・最重量級の成功例】
- 対象: EU官報・法令・判例等の全公刊物メタデータ。約10億トリプル、9,500万リソース。
- 技術: RDF/SPARQL(https://publications.europa.eu/webapi/rdf/sparql)、独自オントロジーCDM(Common Data Model)。REST APIでXML/RDF取得可。
- 生きている理由: EUR-Lex等の公式サイト群の「裏側の配信基盤」そのものであり、KGが業務システムの中核。展示用でない。
- 出典: https://op.europa.eu/en/web/cellar/cellar-data/metadata/knowledge-graph
- 教訓: KGを「公開実験」でなく「自らの出版業務のマスターDB」にすると死なない。

### EU Knowledge Graph(Wikibase、linkedopendata.eu) — 【稼働(推定)】
- 対象: EU機関・加盟国・EU出資プロジェクト等、7.26億トリプル。市民向けアプリKohesio(EU助成プロジェクト検索)の基盤。
- 技術: Wikibase(Wikidataと同じソフト)。SPARQL提供。
- 現状: linkedopendata.euへの直接アクセスはbot遮断(403)で未確認。Kohesio本体は2026-08時点で応答あり。
- 出典: https://www.researchgate.net/publication/354927446_Wikibase_as_an_Infrastructure_for_Knowledge_Graphs_The_EU_Knowledge_Graph
- 教訓: Wikibaseは「政府KGの現実解」として実績あり。市民向けアプリ(Kohesio)を持つことが存続を支えている。

### ELI(European Legislation Identifier) — 【拡大中】
- 法令の恒久URI+メタデータ+サイト埋め込みの3層規格。2012年に理事会合意、任意採用ながら2025年末時点で25か国以上(ノルウェー・スイス含む)がコア識別子を実装。仏Légifrance・伊Normattivaは3層フル実装。
- 出典: https://eur-lex.europa.eu/eli-register/implementation.html
- 教訓: トリプルストアより「識別子の規格」の方が圧倒的に長生きし、広がる。KG設計はURI設計から。

### SEMIC Core Vocabularies — 【稼働中】
- Core Person/Location等の共通語彙。2024-05にも改訂勧告が出ており活動継続。22か国69人のWGで開発、フィンランド・スペイン・オランダ等が採用。
- 出典: https://interoperable-europe.ec.europa.eu/collection/semic-support-centre/core-vocabularies
- 教訓: 語彙は「勧告+改訂プロセス+採用国コミュニティ」という運営体制があると継続する。日本のIMIに欠けていたのはこれ。

### data.europa.eu — 【稼働中】
- 36か国182カタログ・160万データセットのメタデータをDCAT-APでRDF化、SPARQL提供(https://data.europa.eu/data/sparql)。
- 教訓: 「データ本体」でなく「メタデータのKG化(DCAT-AP)」は費用対効果が高く持続している。

## 2. 各国政府

### 米国 data.gov / vocab.data.gov — 【死亡】
- 2009-2012年頃、RPI(Hendler教授ら)と組んでsemantic.data.gov・vocab.data.govでLOD化を推進。学術論文まで出たが、その後関心が減退。vocab.data.govは現在DNS解決すらしない(2026-08-22確認: ENOTFOUND)。data.gov本体はCKAN型カタログとして継続。
- 出典: https://ieeexplore.ieee.org/document/6185527/
- 教訓: 研究者主導・ショーケース型のLODは政権交代と予算見直しで消える。カタログ(CKAN)だけが生き残った。

### 英国 legislation.gov.uk — 【稼働中・16年継続】
- 2010年からAPIファースト設計。任意の法令ページに.data.rdf/.data.xmlを付ければ機械可読データが返る。2025年成立の法律(Data (Use and Access) Act 2025)ですらdata.rdfが返ることを確認。
- 出典: https://www.legislation.gov.uk/ukpga/2025/18/section/72/data.rdf / https://gds.blog.gov.uk/2012/03/30/putting-apis-first-legislation-gov-uk/
- 教訓: 「人間向けサイトと機械可読データを同一URL・同一編集フローで出す」設計は16年生きる。別立てのLODポータルを作らなかったのが勝因。

### フィンランド — 【研究は影響大、サービスは形を変えた】
- Semantic Finlex(Aalto大SeCo+法務省): 法令・判例をELI/ECLIベースでLOD化した国家レベルの実装(2016-2019)。学術的評価は高い。
- 現状: data.finlex.fiは新しいFinlexオープンデータサービスに再構築され、SPARQL/LODは前面から消えた(2026-08確認)。シソーラス基盤Fintoはbot遮断(403)で直接確認できず。
- 出典: https://seco.cs.aalto.fi/projects/lawlod/en/
- 教訓: 大学主導の優れたプロトタイプでも、省庁の本番システム更改時にLOD層は落とされがち。ELI/ECLIという「識別子の遺産」だけが残る。

### 韓国 — 【学術提案どまり、国立図書館LODは稼働】
- 行政区域KGで政府オープンデータを相互リンクする提案等、論文レベルの取り組みが中心(2018-2019)。国家ポータルdata.go.krはCKAN型。国立中央図書館LOD(lod.nl.go.kr/sparql)は稼働。
- 出典: https://accesson.kr/jistap/v.6/1/18/7376

### シンガポール
- 公開LOD/KG事例は今回の調査では確認できず(オープンデータはdata.gov.sgのAPI/カタログ型)。陰性結果として報告。

## 3. 日本国内

### 法令標準XML・法令API(デジタル庁) — 【現役・拡大中、本件の最重要基盤】
- e-Gov法令検索が全現行法令(約8,000超)を法令標準XMLで提供、法令API v2+一括ダウンロードあり。2024年に告示API・中間APIのプロトタイプ公開テスト、官報電子化と連動して2026年度中に「告示のベース・レジストリ」提供開始目標。法制事務のデジタル化(ワークフロー見直し、法令編集機能)も進行中。
- 出典: https://laws.e-gov.go.jp/bulkdownload/ / https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/7f49ac76-91f1-44ba-91bd-2114973fcc61/f1e3c434/20250606-policies_legal-practice_outline_01.pdf
- 教訓: 国はXML+REST APIまでは整備済み・RDFは提供していない。ここがまさに本件の空白地帯(=機会)。
- 注: 「LawFlow」は契約書レビューAI(lawflow.jp)で法制執務とは別物。法制事務デジタル化の民間側は別途要調査。

### 法令LOD/リーガルKG研究 — 【散発的、決定版なし】
- NII佐藤健教授らの論理プログラミングによる法的推論(PROLEG)等、推論系研究はあるが、法令の国家KGを構築・公開し続ける主体は不在。名古屋大にJaHIS法令データベース(研究用)。第一法規のデジタル法制調査報告書(2024)がリーガルオントロジーの欧州動向を整理。
- 出典: https://www.nii.ac.jp/faculty/closeup/satoh/ / https://mps-legal.com/wp-content/uploads/2024/05/RSE-調査報告書.pdf
- 教訓: 研究は推論寄り、行政はXML/API寄りで、「法令KGの持続運用」は誰もやっていない。

### IMI共通語彙基盤 — 【独立プロジェクトとしては終了、GIFに吸収】
- 「頓挫ではなくGIFへの吸収、独立ブランドとしては終了」が正確。GIFのコアデータモデルはIMIコア語彙を参照して定義され、IPAはプロジェクトを「IMI2(情報共有基盤)」に再編。imi.go.jpには「ドメイン移行と現URL廃止」の告知(2025-12-11)が出ており、DMD(データモデル記述)もGIFのデータモデル群に置き換わった。
- 出典: https://imi.go.jp/goi/gif / https://imi.go.jp/goi/
- 教訓: 語彙だけ作って「使うことを強制する業務」がないと、組織改編のたびにブランドごと畳まれる。ただし中身(コア語彙)はGIFに生きており、本件のオントロジー定義ではGIF/IMIコア語彙の再利用が筋。

### GIF(政府相互運用性フレームワーク) — 【継続中】
- デジタル庁が2025-03にも説明資料を更新。重点計画(2025-06)でベース・レジストリ整備とデータ相互運用性確保を継続明記。
- 出典: https://www.digital.go.jp/assets/contents/node/basic_page/field_ref_resources/c1bdb4a2-850f-48ec-a938-a8369f820ac1/d47def21/20250325_policies_development_management_outline_03.pdf

### gBizINFO SPARQL/RDF — 【死亡(2024-04-01廃止)・最重要の反面教師】
- 経産省の法人情報RDF/SPARQL。2023年3月のNRI調査報告書が「法人データにおけるLODの普及度が低く利用者評価も低い」と存続検討を提言 → 2023-09告知、更新頻度低下を経て2024-04-01完全廃止。REST API/CSVは日次更新で継続。廃止告知ページ(info.gbiz.go.jp/html/RdfStop.html)自体が2026-08-22時点で404 — 死んだプロジェクトは墓標ごと消える。
- 有志によるRDF再構築(gbizinfo-lod)がGitHubに存在: https://github.com/Babibubebon/gbizinfo-lod
- 教訓: 利用実績を示せないSPARQLエンドポイントは、利用状況レビュー一発で廃止される。「誰が何をクエリしているか」を最初から設計せよ。

### 統計LOD(data.e-stat.go.jp) — 【稼働中・国内最長寿の政府LOD】
- 総務省統計局が2016年から運用。国勢調査・経済センサス等をRDF化、SPARQLエンドポイント(https://data.e-stat.go.jp/lod/sparql/)提供。2025-09にもメンテナンス告知があり運用継続。
- 出典: https://data.e-stat.go.jp/lodw/
- 教訓: 統計局という恒常組織の定常業務に組み込まれたことが長寿の理由。ただし対象統計の拡大は緩慢で、「生きているが成長していない」。

### 自治体LOD — 【ブームは終息、カタログ型に収斂】
- LinkData.orgは存続しているが、2010年代の自治体LODブーム(鯖江市等)は終息。先進自治体だった鯖江市も現在はCKAN型カタログ+ダッシュボードに移行。5つ星LODを掲げる自治体はほぼ消えた。
- 出典: https://linkdata.org/ / https://data.city.sabae.lg.jp/opendata-list/
- 教訓: ボランティア+首長の熱意に依存したLODは人事異動で死ぬ。CSV+カタログに落ち着くのが自治体の現実解だった。

### 民間の類似サービス — 【KGでなくDB+検索UIとして成立】
- スマートニュース メディア研究所「国会議案データベース」: 衆参20年分の議案・賛否を無償公開。 https://smartnews-smri.com/research/research-1127/
- 官報情報検索サービス(国立印刷局、有料会員制)。官報は2025年の電子化法施行で電子官報が正本化。
- 政治資金収支報告書DB等の可視化サービスも複数存在。
- 教訓: 民間で持続しているのは「RDF公開」でなく「構造化DB+使いやすい検索UI」。KGは内部表現に留め、公開面はアプリにすべき。

## 4. Wikidata/DBpedia(外部IDハブとしての利用可能性)

- **e-GOV law ID(P8610)が既に存在**。ただし付与済みは約1,701件で、現行法令8,000超の2割程度。
- 国会議員: P39=衆議院議員を持つ人物は6,932人と歴代レベルでカバー。省庁・自治体エンティティも基礎的カバレッジあり。
- 日本語DBpedia: 稼働はしているが**2022-12のWikipediaダンプ基準で停滞**(2026-08確認)。ハブとしては非推奨。
- 出典: https://www.wikidata.org/wiki/Property:P8610 / https://ja.dbpedia.org/
- 結論: 外部IDハブはWikidata一択。P8610・議員・省庁への相互リンクは低コストで高価値。DBpediaは使わない。

---

# 教訓トップ5(政府KGが死ぬパターンと生き残る条件)

1. **「誰がクエリするか」不在のSPARQL公開は、利用状況レビュー一発で死ぬ**(gBizINFO=NRI報告書→廃止、米vocab.data.gov=DNSごと消滅)。生存例は必ず具体的な依存アプリを持つ(CELLAR→EUR-Lex、EU KG→Kohesio、legislation.gov.uk→官報編集業務)。公開エンドポイントを製品にせず、自分たちが依存する内部基盤+看板アプリを最初から作ること。
2. **識別子と語彙はトリプルストアより長生きする**。ELIは25か国に拡大し続け、IMIコア語彙もGIFの中で生存。一方エンドポイントは次々死んだ。投資の優先順位は URI設計・IDレジストリ > オントロジー > トリプルストア公開。
3. **「業務の副産物としてのKG」だけが持続する**。CELLARは出版業務のマスターDB、legislation.gov.ukは法令編集フローと一体、統計LODは統計局の定常業務。逆に研究者・推進派主導の「ショーケース型」(米LOD、Semantic Finlex、自治体LOD)は担当者の異動・政権交代・システム更改で消えた。
4. **日本の空白は明確**: 国は法令XML+API+ベース・レジストリまで整備し(2026年度に告示レジストリも)、RDF/KG層は誰もやっていない。政府自身に再びやらせる路線(gBizINFOの再来)ではなく、公式XML/APIを一次ソースとして外部でKGを構築し、Wikidata(P8610等)を外部IDハブに使う構成が、先行事例の失敗を全て回避できる。
5. **公開面はアプリ、KGは内部表現に**。市民・実務家に届いて生き残ったのは検索UI(国会議案DB、官報検索、Kohesio)であり、生のLODではない。SPARQLを一般公開するかは後回しでよく、まず「KGでしか作れない体験」(横断参照・改正履歴・資金と法令の接続など)を製品にすること。

補足(未確認事項): linkedopendata.eu と finto.fi の直接生死(いずれもbot遮断403、死亡の証拠はなし)。シンガポールの政府KGは公開事例を確認できず。
