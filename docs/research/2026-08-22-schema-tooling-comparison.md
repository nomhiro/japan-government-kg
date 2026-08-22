# スキーマ単一ソース技術選定 比較調査(2026-08-22)

> 目的: オントロジー/スキーマ定義の単一ソース・オブ・トゥルースとして何を使うべきか。LinkMLを暫定採用していたが、それが最適でない可能性を含めて公平に評価した。

## 結論

**LinkMLを維持する。ただし条件付き。** 決定的だったのは3点。

1. **Gaia-Xがこのプロジェクトとほぼ同型の構成でLinkMLを本番運用している**(LinkML YAML → SHACL + JSON-LD context + OWL、EU連邦データ基盤、非生物医学、2026年も継続中)
2. **公共部門の規範形式は「SHACL(検証) + OWL(語彙)」であり、その上流ソースは各所バラバラ**(SEMIC=UML/Enterprise Architect、SPDX=SHACL、ELI=手書きOWL)。LinkMLを規範形式にしている公共機関は現時点でGaia-X以外に見つからない
3. **LinkML公式が自ら「LinkMLはスキーマモデリングのフレームワークであり、オントロジーモデリングのフレームワークではない」と明言している**([FAQ: Modeling](https://linkml.io/linkml/faq/modeling.html))

そしてこの判断は**安く巻き戻せる**(生成物をコミットしていれば1〜3人週)。悩むべきはURI設計・PROV-O出典設計・6軸の概念設計であり、そこに検討予算を回すべき。

## 1. 評価表(主要3案)

| 基準 | A. LinkML | B. OWL/TTL手書き + SHACL手書き | C. SHACL単一ソース |
|---|---|---|---|
| **RDF側+アプリ側を1定義から** | 唯一これが一撃で成立。`gen-owl`/`gen-shacl`/`gen-pydantic`/`gen-json-schema`/`gen-doc`が全部同一YAMLから出る。Gaia-Xが実運用で証明 | 成立しない。OWL・SHACL・Pydanticの3系統を人手で同期。K-CAP2025論文はOWL+SHACLの2系統でも変更管理が課題だと報告 | `shacl2code`でPython/JSON Schema/JSON-LD contextが出る(SPDX 3.0の実装方式、生成Python約6000行)。ただし**PydanticではなくshaCl2code独自クラス**でFastAPIと摩擦。SHACL→OWLは**原理的にロッシー** |
| **イベント中心・関係実体化** | **問題なし。むしろ得意。** メタモデルに`represents_relationship: true`と`relational_role`(SUBJECT/PREDICATE/OBJECT)が一級市民として存在 | 最も自然。n項関係も`owl:Restriction`も自由 | SHACLでイベントノードの形は書けるが、6軸の「概念的な意味」を書く場所がない。SHACLは制約言語であり語彙定義言語ではない |
| **CQ駆動の反復(CI)** | `linkml generate` 1コマンド。ただし間接層が1つ増えるので、SHACL shapeが間違っているとき変換を疑う手間が発生 | 編集→即テスト。最短ループ。ただしOWLとSHACLの乖離はSPARQLテストでは検出できない | SHACL自体が直接テスト対象なのでループは短い |
| **バージョニング/URI安定性** | **公式ドキュメント化された運用手順がある。** `deprecated`スロット、2リリース制の廃止手順、`deprecated.yaml`への移動、`gen-doc --include`でPURLを404させない | 完全に自前運用。規律は人間側 | SHACLにdeprecation規約がない。自前annotation運用 |
| **日本語/多言語ドキュメント** | `--default-language`(BCP 47)で`rdfs:label`等に`@ja`。**弱点**: `description`は単一文字列で言語別に複数持てない。docgenの見出しは英語(テンプレート差し替えで日本語化可) | 完全自由。`rdfs:label "組織"@ja`を直接書ける。docsはpyLODE/Widoco | SHACL Playが SHACL から HTML docs + UML図を生成 |
| **健全性/バス係数** | 1.11.1 (2026-05-20)、最終更新2026-08-19。CZI EOSS Cycle 6 + Wellcome Trust助成。中核メンテナ複数・複数機関。月例コミュニティコール。**KuzuDB型の放棄リスクは低い** | 依存ゼロ(rdflib/pySHACL/Jenaのみ)。**最も放棄リスクが低い** | `shacl2code`は**スター7・メンテナ1名**。ただしSPDX/Linux Foundation・Yoctoが実運用依存 |
| **学習コスト/間接層** | 「slotのグローバル名前空間」「slot_usageの冗長さ」が構造的な学習の壁 | 学習コストはOWL/SHACL自体のみ。ただしPydanticを人手同期する恒久コスト | SHACLの学習のみ。`shacl2code`のannotation規約は独自 |
| **公共部門の採用実績** | **Gaia-X**が規範形式として採用、npm `@gaia-x/ontology`で配布。**独NFDI DCAT-AP+がSEMICにLinkML単一ソース化を提案済み(issue #79、未回答)**。他の政府採用例なし | ELI(欧州法令識別子)が該当。`eli.owl` v1.5を手書き維持。**法令領域では手書きOWLが標準** | **SPDX 3.0がSHACLを規範モデルとして採用**。DCAT-AP 3.0.xもSHACL shapesを適合性検証の規範アーティファクトとして配布 |

### 参考3案

- **D. JSON-LD context + JSON Schema**: JSON Schemaは**グラフ形状制約を表現できない**(`sh:targetClass`、パス制約、`sh:qualifiedValueShape`)。RDFが主成果物のプロジェクトで検証能力を捨てることになる。**選ぶ理由がない**
- **E. owlready2**: OWLを操作するライブラリでコード生成器ではない。SHACLもPydanticも出ないため基準1を満たさない。**単一ソース戦略の代替ではない**。かつ自前SQLiteクアッドストア前提でFuseki運用と競合。バス係数1(Jean-Baptiste Lamy単独、主リポジトリBitBucket)
- **F. その他**: `schemasheets`(xlsx/Google Sheets → LinkML。GIFのxlsx配布と相性が良い)、`model2owl`(UML/XMI → OWL + SHACL。EU調達オントロジーePOの公式ツールチェーン)、`ShEx`(表現力はSHACL相当だがW3C Community Group止まり、新規採用の理由なし)、`CUE/Dhall`(RDF/OWL/SHACLターゲットが無く生成器の自作になる。非現実的)、`TopBraid EDG`(商用・高額、公共財OSSに不適)

## 2. LinkMLの制約の実態

### OWL表現力の限界(公式が認めている事実)

[公式OWL生成器ドキュメント](https://linkml.io/linkml/generators/owl.html)より:

- 「LinkMLのruleのうちOWLで表現できるのは一部のみ」
- 「OWL-DLで直接表現できないLinkMLを書くのは比較的容易」 — `Any`レンジのスロットはDatatypeProperty/ObjectPropertyのどちらかに確定できず、結果は**OWL Full**になる
- プロパティ連鎖(`owl:propertyChainAxiom`)、複雑な和・積・補の公理はドキュメントに記載なし
- 出せるのは実質: クラス、`rdfs:subClassOf`、Datatype/ObjectProperty、基数制限、`only`による全称制限、enumの`unionOf`/`oneOf`
- 既知issue: [examplesが失われる #2308](https://github.com/linkml/linkml/issues/2308)、[スキーマレベルのメタデータが文字列リテラルになる #3543](https://github.com/linkml/linkml/issues/3543)

### この制約は本プロジェクトで困るか — 大半は困らない

- Fuseki(既定構成)とQLeverは**クエリ経路でOWL DL推論を回さない**。CQはSHACL検証済みデータに対するSPARQLテスト。したがって「プロパティ連鎖が出せない」は実行時挙動に影響せず、ドキュメントと相互運用の見え方の問題に留まる
- **6軸の関係実体化は「困る側」ではなく「得意な側」**。`Event`を介した実体化はn項関係パターンであり普通のクラス+普通のスロット。LinkMLは[`represents_relationship`](https://linkml.io/linkml-model/latest/docs/represents_relationship/)をメタモデルに持ち、ER図では菱形、RDF文脈では`rdf:Statement`、PG文脈ではエッジとして扱うと明記
- `owlgen`がRDF-star/PGエッジ属性を非対応にしているのは**意図的**([issue #1760](https://github.com/linkml/linkml/issues/1760))で、データ層の出典表現の話。名前付きグラフ+PROV-Oが主戦略なので影響は限定的
- ELIのWork/Expression二層も、単に2クラスと`eli:realizes`相当のスロット。素直に書ける

### 本当に効く制約 — URIの既定値の不整合

最も実害の出やすい落とし穴。PROV-O/ELI/schema.orgの語彙を再利用する設計なので直撃する。

- `gen-owl`の`--use-native-uris`の**既定値はTrue** = 生成OWLは**自分の名前空間のURI**でクラスを宣言し、外部語彙は`skos:exactMatch`でリンク
- `gen-shacl`の`--use-class-uri-names`の**既定値もTrue**(こちらは`class_uri`側を使う)
- `linkml-convert`は`class_uri`でデータに型付けする

つまり**既定のままだと、OWLは`kg:Event`を語り、SHACLとデータは`prov:Activity`を語る**乖離が起きる。CIで気づかないまま進むと後で全部やり直しになる種類のバグ。

**対策(必須)**: `gen-owl`に`--no-use-native-uris`を明示し、**「生成SHACLの`sh:targetClass`のIRI == 生成OWLのクラスIRI == サンプルインスタンスの`rdf:type`のIRI」を突き合わせるCIテストを1本書く**。30分で書けて最大の事故を防ぐ。

### SHACL生成器の成熟度

[gen-shacl](https://linkml.io/linkml/generators/shacl.html)は**「Beta」と明記**。`--closed`(既定True)、`sh:maxCount`、`sh:pattern`、`sh:minInclusive`/`maxInclusive`、rulesからの`sh:sparql`は対応。一方`sh:node`、`sh:qualifiedValueShape`、`sh:or`/`sh:and`/`sh:not`の対応は記載なし。天井に当たると手書きSHACLとの混在(=両方の悪いところ取り)になるリスク。

### 実務者の不満

**HN/Redditには実質的な批判が存在しない**(HN言及2件のみ、Redditは議論なし)。これ自体が所見 — 独立した批判が見つからないのは、コミュニティがニッチ外に広がっていないことの裏返しでもある。

代わりに査読文献に具体的な不満が記録されている。[SchemaLink論文(arXiv 2608.12529、2026-08-12、**LinkML中核開発者Caufield/Mungallを共著に含む**)](https://arxiv.org/html/2608.12529)が専用エディタを作る動機として:

1. 「非専門のキュレータはLinkMLの構文とベストプラクティスに苦労する」
2. **「LinkMLの豊かさと柔軟さは多様なスキーマ形態を許すため、不整合を招きやすく、類似ドメイン間でスキーマの比較や統合が難しくなる」**
3. 「既存のLinkMLスキーマを理解・検証するには数百行のコードを目視検査する必要があり、時間がかかりエラーを招きやすい」
4. **「スキーマの更新とバージョニングは不整合を持ち込みうる」**
5. 「オントロジー用語とLinkMLクラスの不整合が構文・意味の両方のエラーを持ち込む」

構造的な設計上の不満は**slotがグローバル名前空間である**点。`attributes`は`<ClassName>__<slot_name>`の形でグローバル空間にスロットを注入し`slot_usage`で特殊化する設計で、公式ドキュメント自身が「単純なスキーマには少々不便」と認めている。

### 生物医学以外の採用実績

[GigaScience掲載論文(2025-12, DOI 10.1093/gigascience/giaf152)](https://academic.oup.com/gigascience/article/doi/10.1093/gigascience/giaf152/8378082)が挙げる採用先は圧倒的に生物医学寄り(NMDC, Biolink Model, NCATS Translator, Alliance of Genome Resources, MIxS, Monarch Initiative, Neurodata Without Borders)。論文は化学・金融・電気工学・輸送にも言及するが、**具体名が挙がる非生物医学の事例は実質Gaia-Xのみ**。

そのGaia-Xが極めて重要な参照事例。[Service Characteristics WG](https://gaia-x.gitlab.io/technical-committee/service-characteristics-working-group/service-characteristics/)が「Gaia-XオントロジーのLinkML表現を保持し、SHACL shapes・JSON-LD Schema・OWLオントロジーを生成する」と明記。コンテントネゴシエーションで配布し、**「SHACLやJSON-LDの出力を直接編集せず、LinkMLを通して拡張すること」を公式に推奨**。2026年4月にもLinkML解説のTech Deep Diveを開催しており**現行の運用**。

## 3. 公共部門の実際の慣行

**「公共部門はSHACLを規範形式にしている」は半分だけ正しい。** SHACLは規範的な**検証アーティファクト**だが、その**上流のソースは機関ごとに全く違い、しかもLinkMLではない。**

| 機関/仕様 | ソース・オブ・トゥルース | 生成物 |
|---|---|---|
| **EU SEMIC**(DCAT-AP等の全AP) | **UML(Enterprise ArchitectのEAPファイル)** | HTML仕様(人間向けの規範)、JSON-LD context、SHACL、XSD。Oslo EA-to-RDF Docker → CircleCI |
| **DCAT-AP 3.0.x** | 同上 | SHACL shapesが適合性検証の規範アーティファクト |
| **ePO**(EU調達オントロジー) | **UML/XMI** → [model2owl](https://github.com/OP-TED/model2owl) | OWL DL(Turtle)+ SHACL + 推論公理 |
| **ELI**(欧州法令識別子) | **手書きOWL**(`eli.owl`) | OWL v1.5(2024)。SHACLバリデータを**別途**開発 |
| **SPDX 3.0**(Linux Foundation) | **SHACL(規範モデル)** | [shacl2code](https://github.com/JPEWdev/shacl2code)でPython約6000行/C++/Go + JSON Schema + JSON-LD context |
| **Gaia-X** | **LinkML** | SHACL + JSON-LD context + OWL。npm配布 |
| **独NFDI DCAT-AP+** | LinkML(**SEMICへの提案段階、未回答**) | [issue #79](https://github.com/nfdi-de/dcat-ap-plus/issues/79): 現行慣行の問題として「公開される仕様アーティファクトが別々のツールで生成されたり手編集されたりして相互に不整合になる」を挙げる |
| **日本 IMI共通語彙基盤** | RDF Schema + 必要に応じてOWL | [コア語彙2.4](https://imi.go.jp/core/core240/)。XML/RDF/JSONの3形式 |
| **日本 デジタル庁 GIF** | **Excel(.xlsx)** | GIF v2.2(2026-01-08)。`438_コアデータモデル_DMD.xlsx`等。**RDFネイティブな規範形式は存在しない** |

**読み取るべきこと:**

1. **「公共部門はLinkMLを使っている」とは言えない。** Gaia-X 1件と未回答の提案1件。DCAT-AP+のissue #79を「公共部門がLinkMLを採用」に膨らませてはいけない
2. **SEMICのUML/Enterprise Architect方式は本プロジェクトには真似できない**(商用ツール依存、個人〜小規模のOSS公共財に不適)
3. **専門家の推奨は「OWLとSHACLを併存させる」であって「片方から片方を生成する」ではない。** [K-CAP 2025論文](https://dl.acm.org/doi/10.1145/3731443.3771340)は鉄道輸送の実案件で「クラスとプロパティを**両方の言語で表現し**、制約は推論要件と検証要件に応じて片方または両方で表現する」方式を提案。EU調達オントロジーを担当する[Meaningfy](https://meaningfy.ws/what-do-we-put-in-owl-what-do-we-put-in-shacl-a-rule-of-thumb/)も「OWLは何が存在するか、SHACLはどう使うべきか」と役割分担を推奨し、**単一ソース化を推奨していない**
4. **日本政府側の規範形式はxlsx/XSDなので、本プロジェクトは形式の制約を受けない。** ただしGIFのxlsxとIMIのRDFSを**取り込める**ことが要件。`schemasheets`(xlsx → LinkML)がGIFのxlsx配布と相性が良いという副次的な利点がある

## 4. 実施すべき具体策(LinkML維持の必須条件)

1. **生成物をgitにコミットする。** `.gitignore`に入れないこと。**LinkMLの賭けを可逆にする唯一の措置**。差分レビューで生成器の回帰も検出できる
2. **LinkMLのバージョンをピン留めする**(`linkml==1.11.1`等)。1.11.0が誤ったコミットに紐づいてyankされた前例あり(2026-05-13 yank → 05-20に1.11.1)
3. **URI整合性のCIテストを書く。** `gen-owl --no-use-native-uris`を明示し、「生成SHACLの`sh:targetClass` == 生成OWLのクラスIRI == サンプルインスタンスの`rdf:type`」を突き合わせる。**これが最重要**
4. ~~**`--default-language ja`を`gen-owl`と`gen-shacl`の両方に指定する。**~~ **← 訂正: このオプションは `linkml==1.11.1` に存在しない(下記の訂正を参照)。** 言語タグは生成後にrdflibで付ける後処理で実現する。日英併記の規約(日本語を`description`、英語を`structured_aliases`+`in_language: en`)を最初に決める点は有効
5. **[公式の廃止手順](https://linkml.io/linkml/howtos/deprecating-elements.html)を初日から採用する。** URIを404させない運用は後付けが難しい
6. **`gen-shacl`が要件を満たさなくなったら、手書きSHACLの混在ではなく「その制約はSPARQL CQテスト側で見る」に逃がす。** 混在は最悪の状態
7. **LinkMLに書けないことを書かない。** 生成された出力を読んで理解できる範囲に留める

## 5. 移行コスト — いま慎重になるべき度合い

**結論: 低い。この決定に時間をかける価値はあまりない。**

LinkMLは**生成器**であり、ランタイム依存でもデータフォーマットでもない。

**無駄になるもの**: LinkML YAMLソース本体、CIの生成配線(数十行)、LinkMLの学習時間。合計**1〜3人週相当**(推測)

**無駄にならないもの(資産として残る)**: URI体系、RDFデータ本体と名前付きグラフ/PROV-O出典構造、**生成済みSHACL/OWL/Pydantic**(そのまま手書き管理に移行 = C案の状態に着地)、SPARQL CQテスト群、6軸の概念設計

**撤退手順**: 生成を止める → 最後の生成物を`git add` → YAMLを削除 → 続行。**ただしこれは生成物をコミットしている場合に限る。**

**逆に、高価で不可逆な決定は別のところにある**: URI設計(一度公開したら消せない)、名前付きグラフ+PROV-Oの出典モデル(データ全体の再生成)、6軸の概念的な切り方(全ドメインスキーマに波及)、ELIのWork/Expression二層の粒度(法令データ全体の再構築)。**検討予算はこちらに回すべき。**

## 訂正(2026-08-22、実装時に実機で判明)

**この調査の「`--default-language` オプションがある」という記述は誤りである。** 実装時に検証した結果:

- `uv run gen-owl --help` / `gen-shacl --help` に `--default-language` は出現しない
- インストール済みの `linkml` / `linkml_runtime` を `default_language` でgrepしても0件。メタモデルにもこのフィールドは無い
- 実行すると `Error: No such option: '--default-language'` で即エラー
- `linkml` の最新リリースは 1.11.1(2026-05-20)であり、「バージョンを上げれば直る」話ではない

linkml.io の現行ドキュメント(https://linkml.io/linkml/generators/owl.html)には記載があるが、**未リリースブランチのドキュメントが先行しているだけで、どのリリース版にも実装されていない**。

**教訓: ツールのCLIオプションは公式ドキュメントではなく `--help` と実行結果で確認する。** この調査はドキュメントを一次情報として扱ったが、実装との乖離があった。

あわせて判明した事実:
- LinkMLは説明文を `rdfs:comment` ではなく **`skos:definition`** に出力する
- Windowsでは `gen-owl ... > file.ttl` のリダイレクトでstdoutがコンソールのコードページ(cp932)で開かれ、生成Turtleが不正なUTF-8になる。`PYTHONUTF8=1` で回避できる

対応: 言語タグは生成後にrdflibで付ける後処理(`jgkg.schema_lang`)で実現した。対象は定義文(`skos:definition` / `sh:description`)のみで、要素名である `rdfs:label` には付けない。詳細は設計書§5.7。

## 補足: 推測と事実の区別

- **事実(出典あり)**: バージョン番号、日付、CLIオプションと既定値、公式ドキュメントの引用、採用機関とそのソース形式、論文の主張
- **調査エージェントの分析(出典なし)**: OWL表現力の制約がFuseki/QLever構成では実行時に影響しないという判断、移行コスト1〜3人週、LinkML習得1〜2週間
- **確認できなかったこと**: LinkMLからの移行・放棄事例(公開議論が見つからないという意味)。HN/Redditでの実務者批判(2026年8月時点で実質的な議論なし)。K-CAP 2025論文の全文(ACM DLが403のため要旨とリポジトリからの再構成)
