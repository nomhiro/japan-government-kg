# Azure上でのRDFナレッジグラフ公開ホスティング調査(2026-08-22)

> 目的: 「いずれAzureにホスティングして公開する」ことを踏まえ、RDF中心(案A)の設計判断が揺らぐかを判定する。
> 価格はすべて **2026年8月22日時点の公開価格**(USD、pay-as-you-go、East US / Japan East)。

## 1. Azureにマネージドトリプルストアはあるか → **無い**

**2026年8月時点で、AzureにRDF/SPARQLのファーストパーティ・マネージドサービスは存在しない。AWS Neptuneに相当するものはない。**

根拠(いずれも一次情報):

- **Microsoft自身のAWS→Azure対比表が、Amazon Neptune (Graph) を Azure Cosmos DB にマップしている。** つまりMicrosoftの公式回答は「Neptuneの代替はプロパティグラフのCosmos DB」であり、SPARQLを話すサービスは提示されていない
  https://learn.microsoft.com/azure/architecture/aws-professional/databases#service-comparison
- **Microsoft Fabric の Graph は RDF を明示的に非サポート。** 原文「Graph in Microsoft Fabric only supports the LPG model. Resource Description Framework (RDF) isn't supported.」さらに「セマンティックウェブ標準やオントロジー、グローバルなデータ統合が必要なら、**RDFをサポートする他のプラットフォームを検討せよ**」と他プラットフォームを勧めている。クエリ言語はGQL
  https://learn.microsoft.com/en-us/fabric/graph/graph-data-models
- Azure Feedback に「Support RDF to use as triplestore」の機能要望が未実装で残っている
  https://feedback.azure.com/d365community/idea/d5734c02-555b-ed11-a81b-000d3ae49307

### 個別サービスの現状

**Azure Cosmos DB for Apache Gremlin**
- 廃止アナウンスは確認できず、提供継続中(2026-03-15のREST APIバージョンが存在)
- ただし**全ドキュメントページの冒頭に誘導バナーが付いた**: 「高スケールならCosmos DB for NoSQLを検討」「OLAPグラフの実装、または既存のApache Gremlinアプリの移行なら**Graph in Microsoft Fabricを検討**」。正式な廃止ではないが新規採用を積極的に勧めない**ソフトな縮小シグナル**と読むのが妥当(推測)
- **RDFではなくプロパティグラフ**(TinkerPop準拠)。本プロジェクトに効く制限: traversal timeout **30秒**、`.repeat()` の反復上限 **32**(=32ホップまで)、degree of parallelism 32、スクリプト長64KB
  https://learn.microsoft.com/azure/cosmos-db/gremlin/limits
- **名前付きグラフの概念がない。** 出典管理を名前付きグラフで行う本設計とは根本的に噛み合わない

**Microsoft Fabric Graph** — LPGのみ、RDF非サポート(上記)。Fabric capacity (F SKU) が前提で小規模個人プロジェクトの予算に合わない。スキーマ変更には「新しいグラフモデルを作ってデータを再ロード」が必要と明記

**Azure Digital Twins** — 廃止アナウンスなし。ただし**RDFの代替にならない**: DTDLはJSON-LD風だがデジタルツインのモデリング用で、任意のRDFグラフをSPARQLで問い合わせるトリプルストアではない。クエリ言語も独自のSQL風

**Azure AI Search / GraphRAG** — **マネージドなGraphRAGサービスは存在しない。** MicrosoftのGraphRAGはOSSライブラリで自前デプロイ。AI Searchはベクトル/キーワード検索でRDFストアではない

**Azure HorizonDB + Apache AGE 拡張 (Preview)** — 2026年にPreview登場。ただし**openCypherのプロパティグラフ**でRDF/SPARQLではない
  https://learn.microsoft.com/azure/horizondb/graph/age-overview

### Azure Marketplace のサードパーティ

RDFトリプルストアは**あるが、ほぼ全てBYOLのVMイメージ**で「マネージド」ではない。VM代は自分で払い運用も自分で行う。

- **Ontotext GraphDB Enterprise Edition** — BYOL VMイメージ。SPARQL/SHACL/RDF-star対応。Ontotext公式の**Azure用Terraformモジュール**(HAクラスタ)も提供 https://github.com/Ontotext-AD/terraform-azure-graphdb
- **AllegroGraph 8.0.1 VM** — VMイメージあり
- **Stardog Cloud** — 価格非公開(商談ベース)。Azureリージョンでの提供有無は公開情報から確定できず
- **Neo4j Aura** — Marketplace経由でサブスクライブ可能。ただし**プロパティグラフ**。Professionalは概ね$65/GB/月から

GraphDB EE / Stardog / AllegroGraph はいずれもエンタープライズ向けで価格非公開。個人〜小規模の公共財OSSの予算に乗らない。GraphDB Freeを自前運用する選択はあるが、ホスティングの構図は下記と同じ。

## 2. 選択肢の比較表

| 構成 | RDF/SPARQL | 名前付きグラフ | 永続化 | 月額目安 | 評価 |
|---|---|---|---|---|---|
| **Azure VM + managed disk で Fuseki (docker)** | ○ | ○ | **managed disk (block)** = mmap安全 | B2ls_v2(2vCPU/4GiB)+E6 64GiB = **$35.17**(East US)/**$44.51**(Japan East)。8GiBなら B2s_v2+E10 = **$70.34** | **◎ 現状の最有力。**TDB2の要件を素直に満たす唯一の構成。運用は自前 |
| **Azure Container Apps + Fuseki** | ○ | ○ | **Azure Files (SMB/NFS) のみ**。block storage無し。ephemeralは**最大8 GiB** | 1vCPU/2GiB 常時active ≈ **$73**、idle料金 ≈ **$18**、minReplicas=0 なら **$0** | **△ 条件付き。**永続ボリューム=Azure FilesはTDB2と相性最悪。**DBをイメージに焼く/起動時DLなら成立** |
| **App Service for Containers + Fuseki** | ○ | ○ | Azure Files。`/`・`/home` へのマップ不可。**Docker ComposeシナリオでAzure Storage非サポート** | B1 $12.41 / B2 $24.82 / P0v3 $56.58 | **✕ 非推奨。**B1/B2はRAM 1.75/3.5GiBで数千万トリプルに不足 |
| **AKS + Fuseki** | ○ | ○ | Azure Disk CSI (ReadWriteOnce) = block、mmap安全 | ノード代+コントロールプレーン。VM単体より高い | **△ 過剰。**単一ノードのステートフルDBにK8sを持ち込む理由が薄い |
| **Cosmos DB for Gremlin** | **✕**(プロパティグラフ) | **✕** | フルマネージド | RU/s課金 | **✕ 設計非互換。**名前付きグラフ無し、30秒timeout、32ホップ上限 |
| **Microsoft Fabric Graph** | **✕**(RDF明示的に非サポート) | ✕ | フルマネージド | Fabric capacity必要 | **✕ 設計非互換+高コスト** |
| **Marketplace: GraphDB EE / AllegroGraph** | ○ | ○ | VM+managed disk(自前) | VM代+**ライセンス非公開** | **✕ 予算外** |
| **AWS Neptune(比較対象)** | **○ 本物のマネージドRDF** | **○** | フルマネージド | db.t4g.medium **$67.89**(us-east-1)/**$103.95**(Tokyo)+storage。Serverlessは1 NCU下限で**$117.38/月、scale-to-zeroしない** | **AWSの明確な優位。**ただし最安でもAzure VM自前運用の**2〜3倍**。SHACL/推論は無し |
| **Blobでダンプ配布のみ + Static Web Apps** | ✕(クエリ不可) | — | Blob | Blob hot $0.0208/GB/月(50GBで$1.04)+egress 100GB/月無料、以降$0.087/GB(East US)/$0.12/GB(Japan East)。SWAは**Free $0** | **◎ 最安の第一歩。**クエリ可能な構成との差は実質**VM代$35〜70/月** |
| **Hetzner / Fly.io(比較)** | ○ | ○ | ローカルNVMe / Fly Volumes | Hetzner CPX32(4vCPU/8GB/160GB NVMe)≈**$41.99**。Fly shared-cpu-2x 8GB ≈**$47.32**+volume | Hetznerは2026年4-6月に値上げ(CPX/CCX系で100-200%超)。**かつての圧倒的な安さは薄れた**。Flyのegressは$0.02/GBでAzureの1/4〜1/6 |

### コスト面で見落としやすい点

- **Japan East は East US より約+30%。** VM代だけでなく**egressも$0.087→$0.12/GB**と高い
- **egressが最大の伏兵。** 公開SPARQLで月1TB返すとJapan Eastで**約$108/月** = VM代を超える。無料枠は月100GBまで
- **バースト系(B-series)はRAM 4GiB超だと得しない。** B2s_v2(2/8GiB)$60.74 vs D2as_v5(2/8GiB)$62.78で差は3%。**お得なのは B2ls_v2 (2vCPU/4GiB) $30.37 だけ**
- **バーストクレジットの落とし穴**: `tdbloader2` の一括ロードは数十分CPU 100%継続でクレジットを枯渇させ、**ベースライン(B2ls_v2なら30%)に絞られる**。→ ロードは別マシン/CIで行い成果物をコピーする運用が正解
- **Premium SSD v2 が実は最安の高性能ディスク**: 64GiBで**約$5.14/月**(3,000 IOPS / 125 MBpsまで追加課金ゼロ)。Premium SSD v1 (P6 $10.21)の約半額、Standard SSD (E6 $4.80)とほぼ同額。トランザクション課金も無し

## 3. TDB2のストレージ問題の実態

### 事実として確認できたこと(Jena公式)

- 「**On 64 bit Java, TDB uses memory mapped files.**」
- 「**TDB uses memory mapped files heavily**... Memory mapped files live outside of the JVM heap and are **managed by the OS**.」
- 「TDB2 can be used as a high performance RDF store on **a single machine**.」
- 「**Multiple applications, running in multiple JVMs, using the same file databases is not supported and has a high risk of data corruption.**」
- 「Databases **can not be copied while TDB is running**」
- `fileMode` パラメータが存在(既定は64bit Javaで `mapped`)。ただしJenaは変更について「**production用途には良い考えではない、実験用のみ**」と警告

出典: https://jena.apache.org/documentation/tdb/requirements.html / https://jena.apache.org/documentation/tdb/faqs.html / https://jena.apache.org/documentation/tdb2/ / https://jena.apache.org/documentation/tdb/store-parameters.html

### 重要な訂正

**Jenaの公式ドキュメントには「NFS/SMB上で動かすな」という明文の禁止規定は見つからなかった。** requirements・FAQs・architecture・store-parameters の各ページにネットワークファイルシステムへの言及は存在しない。ここは断定を避けるべき箇所である。

### 危険である根拠(上記事実からの演繹)

1. **キャッシュコヒーレンシの保証がない。** mmapはOSのページキャッシュに依存し、TDBは「OSがRAMとディスク間のキャッシュを管理する」前提で設計されている。SMB/CIFSやNFSではコヒーレンシとflushの意味論がローカルブロックデバイスと同等に保証されない。TDB2のWAL/トランザクションは「書いたものが順序通り永続化される」ことに依存するため、**静かなデータ破損**になりうる(クラッシュではなく後から壊れたインデックスに気づく形)
2. **ロックが効かない。** TDBのロックファイルは同一ホスト上の別JVMを排除する仕組み。共有ファイル共有を複数レプリカがマウントすると、Jenaが「非サポート・破損リスク高」と明記した状態そのものになる。**ACA/App Serviceは複数レプリカへスケールしうるので現実的な危険**
3. **性能が出ない。** mmapのページフォルトが毎回ネットワーク往復になる

### Azure側の地雷 — 「デフォルトでSMBを掴まされる」

- **Azure Container Apps の永続ストレージは Azure Files (SMB/NFS) しかない。** 原文「Azure Container Apps **doesn't support mounting file shares from Azure NetApp Files or Azure Blob Storage**」。**block storage を attach する手段がない**
- **ACAのephemeral storageは最大8 GiB**(vCPU数連動: >1 vCPU→8 GiB)
  https://learn.microsoft.com/azure/container-apps/storage-mounts#ephemeral-storage
- **App Service Linux** のcustom-mounted storageはAzure Filesで、「Mapping `/` or `/home` to custom-mounted storage isn't supported」「**Azure Storage isn't supported with Docker Compose scenarios**」
  https://learn.microsoft.com/azure/app-service/configure-connect-to-azure-storage

**つまり「Container Appsにdocker-composeのFusekiをそのまま持っていく」と、永続ボリュームが自動的にSMBになり、TDB2にとって最悪の組み合わせが完成する。**

### 回避策(有効な順)

1. **【最有力】VM + managed disk。** ブロックデバイスなのでmmapが素直に動く。Premium SSD v2なら64GiBで約$5/月
2. **【ACAを使うなら】永続ボリュームを使わない。** DBをコンテナイメージに焼く、または起動時にBlobからephemeral disk(最大8GiB)へダウンロードして展開する。**読み取り専用・月次更新という本プロジェクトの特性はこれに完璧に合致する**
3. **【AKSを使うなら】Azure Disk CSI (ReadWriteOnce)** を使い、Azure Files (ReadWriteMany) は選ばない。レプリカ数は1に固定
4. **`fileMode: direct` は回避策として当てにしない。** Jena自身が「production用途には良い考えではない」と書いている

## 4. 推奨構成

### Phase 1(内部利用のみ / FastAPI経由、公開SPARQLなし)

**Azure VM (B2s_v2, 2vCPU/8GiB) + Premium SSD v2 64GiB + docker-compose のまま Fuseki と FastAPI を同居**

- **月額目安: 約$66(East US)/約$85(Japan East)**
- TDB2の要件を素直に満たす唯一の構成で、**現在のdocker-composeをそのまま持ち込める**。Phase 1は内部利用のみなので可用性要件が低く単一VMで十分
- **RAMは8GiB推奨。** 数千万トリプルのTDB2ではmmapされたインデックスがOSページキャッシュに乗るかがクエリ性能を決める。4GiB(B2ls_v2 $30.37)でも動くが、法人番号500万件を含む規模ではキャッシュミスが増える。**まずB2ls_v2で始めて遅ければリサイズ**が予算的に合理的(VMリサイズは再起動のみ)
- **ロードはVM上でやらない。** バーストクレジット枯渇のため。**CI(GitHub Actions等)で `tdbloader2` を回してTDB2ディレクトリを生成 → tar.gz をBlobかGHCRに置く → VM側は落として差し替えるだけ**。SHACL検証もロード前ゲートとしてCIに自然に入る

**さらに安く始めるなら**: クエリ可能なエンドポイントが本当に要るまでは**BlobでRDFダンプ配布 + Static Web Apps (Free $0)**のみで**月$1〜2**。クエリ可能にする差額が実質**VM代$35〜70/月**と分かっていれば意思決定しやすい。

### 将来(公開SPARQLエンドポイント提供)

**イミュータブル・デプロイに倒す**のがこの読み取り中心・月次更新のワークロードに最も効く。

- **ACAのephemeral storage上限は8 GiB。** 数千万トリプルのTDB2が収まるなら成立するが**上限が近いので実測が必須**
- **より安全な同型パターン: 「CIでインデックス構築 → Blobに置く → コンテナ起動時にローカル/ephemeral diskへダウンロード」。** イメージを肥大させず、更新はBlobのオブジェクト差し替えとリビジョン再起動だけ

| | 構成 | 月額目安 | 備考 |
|---|---|---|---|
| **Phase 2a: 低トラフィック公開** | ACA (1vCPU/2GiB, minReplicas=0 or idle課金) + 起動時にBlobからDB取得 | **$18〜73** + Blob $1〜2 + egress | scale-to-zeroでコールドスタート許容なら実質$0近く。**DBが8GiBに収まる場合のみ** |
| **Phase 2b: 実用的な公開** | VM (B4s_v2 4vCPU/16GiB) + Premium SSD v2 + Front Door/CDNでキャッシュ | **約$127**(East US) | DBサイズ制約なし。**FastAPI層でクエリ制限(timeout, result size)とキャッシュを必ず入れる** |

**QLeverについて**: **2025年6月にSPARQL 1.1フル準拠を達成し、名前付きグラフ・SPARQL Update・Graph Store HTTP Protocolをサポート。** 本プロジェクトのquad必須要件を満たす。ただし「Current deviations from the SPARQL 1.1 standard」Wikiページが維持されているので採用前に確認すること
https://github.com/ad-freiburg/qlever/wiki/Current-deviations-from-the-SPARQL-1.1-standard
- RAM要件は寛容。Wikidata(数百億トリプル、約500GBインデックス)の構築が**約20〜40GB RAM**で回るという報告があり、Blazegraphが最低128GB要求するのとは対照的。**数千万トリプルなら8〜16GiBで十分**と見込める
- ただしQLeverも**ディスク上のインデックスをmmap前提で読む**ので、**ローカルブロックデバイス要件はFusekiと同じ**

## 5. Azure前提はRDF中心の設計判断を変えるか → **変えない**

### RDFは「不利になる」のではなく「マネージドの恩恵が受けられない」だけ

**Azureを前提にしてもRDFの技術的な優位性は何も減らない。減るのは"運用を任せられる"という選択肢だけ。**

そして重要なのは、**Azureではプロパティグラフに倒しても大して得しない**こと:

- **Cosmos DB Gremlinは本プロジェクトの中核要件と非互換。** 名前付きグラフが無い = 出典管理の設計が崩壊する。SHACL相当もない。30秒timeout / 32ホップ上限は探索的クエリに厳しい。そして**縮小シグナルが出ている**サービスに公共財プロジェクトの基盤を賭けるのは筋が悪い
- **Fabric GraphはRDF非サポートを公言した上で「RDFが要るなら他のプラットフォームを検討せよ」と書いている。** Microsoft自身が「うちにRDFの受け皿は無い」と認めているのと同じ
- **Neo4jに倒すなら、それはもうAzureのマネージドサービスではない**(Marketplace経由の別会社SaaS)。だったらFusekiを自前運用するのと運用負荷の構図は大差なく、RDF標準を捨てる代償だけが残る

**「Azureに寄せるためにRDFを捨てる」という取引は成立しない。**

### 他クラウドとの比較

- **AWSの方がこの用途では明確に有利。** Neptuneは本物のマネージドRDFクアッドストアで、quadのG位置にnamed graph identifierを格納する。**Azureにはこれに相当するものが無い**のが本調査の核心
- **ただしNeptuneも高い。** 最安の実用構成db.t4g.mediumで**$67.89/月(us-east-1)/$103.95/月(Tokyo)**+ストレージ。Serverlessは**1 NCU (2GiB)が下限でscale-to-zeroしない**ため**$117.38/月**が床になり、低トラフィック用途では逆に高くつく。SHACLや推論もない。**Azure VMでFusekiを自前運用する($35〜70)方が安い**
- **Azureを選ぶ追加コスト**: Japan EastはEast US比**+約30%**、egressも高め($0.12/GB)。Hetzner (CPX32 ≈$42)と同等〜やや高、Fly.ioと比べるとegressが4〜6倍高い。**ただしHetznerは2026年に大幅値上げしており差は縮んでいる**
- **Azureを選ぶ制約**: ACA/App Serviceという「安くて楽な」PaaS層が**ストレージの都合で使いにくい**。結果として「VMを立てる」というクラウドの旨味が最も薄い選択肢に落ち着く。**ただしそれはどのクラウドでも同じ**

### 「クラウド非依存でdocker-composeのまま」という方針の評価 → **妥当。むしろ最適**

1. **どのクラウドにもマネージドRDFの安価な選択肢が無い**(AWS Neptuneが唯一の本格派だが高くscale-to-zeroしない)。**どこに行っても自前運用**なので、特定クラウドのマネージドサービスにロックインする理由が存在しない
2. **自前運用が前提なら、可搬性がそのままコスト交渉力になる。** Azureが高ければHetznerに、egressが問題ならFly.ioに移せる
3. **ただし1点、ポータビリティの前提に注意。** 「docker-composeのままどこにでも載せられる」は**ブロックストレージがある環境に限って**真。ACAのようなサーバーレスコンテナ環境には**そのままでは載らない**。この制約を織り込むなら、**「DBを成果物として扱い、実行環境から切り離す」**——CIでインデックスを構築してtar.gz/イメージとして配布し、実行側はそれを取得して起動するだけ——という形にしておくのが最も可搬性が高い。**読み取り中心・月次バッチ更新という本プロジェクトの特性はこの形に理想的に合致する**

## 付記: 確認できなかったこと

- Stardog Cloud の Azureリージョン提供状況と価格(商談ベースで公開情報なし)
- GraphDB EE / AllegroGraph の Marketplace 価格(ページが403/404。BYOL形態であることは確認済み)
- Premium SSD v2 の Japan East での提供可否(リージョン/ゾーン制限あり)
- ACAのコンテナイメージサイズ上限(文書化されたハード上限は「無い」とのMicrosoft Q&A回答のみ)
- **数千万トリプルのTDB2実サイズ(未実測)。ACAの8 GiB ephemeral上限に収まるかは実測が必須**
