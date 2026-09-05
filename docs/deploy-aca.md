# Azure Container Apps への配備手順(D-6b-2)

## 2026-09-06: この手順は実行され、通った(裁定B90)

**以下の記述は「一度も実行されていない」状態のときに書かれたものである。
実際に実行した結果を先に書く。**

**実配備が成功した。** 作ったもの(すべてリソースグループ `rg-jgkg` の中。
`az group delete --name rg-jgkg` 1つで消せる):

| リソース | 値 |
|---|---|
| リソースグループ | `rg-jgkg`(`japaneast`) |
| ACR | `acrjgkg`(Basic) |
| Container Apps 環境 | `cae-jgkg`。**`--logs-destination none`** で作った(Log Analyticsを作らない=課金を増やさない判断。必要になれば後から `az containerapp env update` で足せる) |
| Container App | `jgkg` |

**実測した数字**(controllerが自分で測った):

| 測ったこと | 結果 |
|---|---|
| ロール割り当て後、リクエストで起きてAPIが200を返すまで | **5.2秒** |
| `scripts/smoke-test-api.py` の5経路 | **全経路が実データで通った**(パーセントエンコードのIDを含む) |
| CORS | `access-control-allow-origin: *`・preflight 200・`allow-methods: GET` |

### **予告した失敗はそのとおり起きた**(下の「1. イメージのpullが…」)

`az deployment group create` は
**`ContainerAppOperationError: Failed to provision revision for container app
'jgkg'. Error details: Operation expired.`** で失敗した。
**アプリ自身とマネージドIDは作られていた**ので、手順7の
`az role assignment create --role AcrPull` を実行し、
そのあとHTTPリクエストでレプリカを起こしたら通った。

**つまり「一度デプロイ→ロール割り当て→起こす」という手順の順序は正しい。**
**ただし手順6のコマンドは初回に必ず失敗する**ので、
**その失敗を見て手を止めないこと**——手順7へ進むのが正しい。

### **Windowsで実行するなら `MSYS_NO_PATHCONV=1` が必須**(Git Bash)

`managedEnvironmentId` と `--scope` に渡す `/subscriptions/...` が、
Git Bashのパス変換で **`C:/Program Files/Git/subscriptions/...`** に
書き換えられ、`InvalidEnvironmentId` で失敗する。**実際に踏んだ。**

```bash
MSYS_NO_PATHCONV=1 az deployment group create ...
MSYS_NO_PATHCONV=1 az role assignment create ...
```

**この罠はこのプロジェクトで3度目である**(裁定B66の
`gen-owl --enum-iri-separator /`、`docker exec` のパス、そしてここ)。
PowerShellやLinuxでは踏まない。

---

## (元の記述)この文書とテンプレートは一度も実行されていない

`deploy/aca.json` は `az` を1回も実行せずに書いた。確認したのは
**構文としてJSONとしてパースできること**(`tests/test_deploy_aca.py`)と
**プロパティ名が公式ドキュメント(Microsoft Learn)の記述と一致すること**
(このタスクの調査時点)だけである。**「動くはず」ではない。実際に
`az deployment group create` を初めて流す人が、ここに書いた手順で
最後まで通ることは確認できていない。**

このプロジェクトの再発欠陥9「実データに一度も当てていない層は緑でも
未検証」がそのまま当てはまる段——テストが緑でも、Azure実環境という
「実データ」にはまだ一度も当てていない。

**↑ この段落は2026-09-06に解消した。** 上の節を読むこと。
**予告の1(AcrPullの順序)は的中し、予告に無かった罠
(Windowsのパス変換)が1つ出た。**

### 初回の実行で失敗しうる箇所(心当たり)

1. **イメージのpullがロールの割り当て前に走る。** このテンプレートは
   Container Appの`identity`にシステム割り当てマネージドIDを使い、ACRの
   `registries[].identity`に`"system"`を指定して資格情報を一切書かない
   構成にした(下の「なぜこの形式か」参照)。**しかしこのIDは
   Container Appを作成した後にしか存在しない**——初回の
   `az deployment group create`がそのまま流れても、ACR側に`AcrPull`
   ロールがまだ無いためイメージのpullに失敗する可能性が高い
   (`ImagePullBackOff`相当の状態でレプリカが起動しない)。下の手順は
   「一度デプロイ→ロール割り当て→再起動」の順にしてあるが、この順序を
   実際に踏んで初回から動くことまでは検証していない。
2. **`cpu`をテンプレート内で`json(parameters('fusekiCpu'))`のように
   文字列パラメータから数値に変換している。** ARMテンプレートの
   パラメータ型に小数(`0.75`等)を直接持つ型が無いための標準的な
   回避策だが、`az deployment group create`に渡す`--parameters`の
   書式(単純な`key=value`か、JSONファイル経由か)によって引用符の
   扱いを間違えやすい。
3. **`resources.cpu`+`resources.memory`の合計が、Consumption環境が
   要求する組み合わせ(0.25刻み・cpu:memory=1:2)からずれていると、
   デプロイ自体がAzure側の検証で拒否される。** 既定値(fuseki
   0.75vCPU/1.5Gi + api 0.5vCPU/1Gi = 合計1.25vCPU/2.5Gi)は
   組み合わせ表に載っている値のはずだが、パラメータを変える場合は
   利用者が合計を組み合わせ表と照らして確認する必要がある。
4. **`managedEnvironmentId`が指すEnvironmentが存在しない・
   別リージョンにある等の食い違い。** このテンプレートはEnvironment
   自体を作らない(下の手順1〜3で事前に作る前提)。
5. **`imageTag`に渡すタグが、実際にACRへpushしたタグと一致しない。**
   `:latest`を既定にしない設計(下記)にした分、タグを合わせる責任は
   完全に利用者の手順側に移っている。

---

## 事前に必要なもの

- Azure CLI(`az`)がインストール済みで、`az login`済みであること
- 対象のAzureサブスクリプションへの、Container App・ACR・ロール割り当てを
  作成できる権限
- `docker`(D-6b-1のイメージをビルドする)
- このリポジトリの`uv sync --extra dev`済みの環境(`scripts/smoke-test-api.py`用)

## 変数(このセッションのシェルで設定する。値は例であり実在のIDではない)

```bash
export SUBSCRIPTION_ID="<自分のサブスクリプションID>"
export RESOURCE_GROUP="<自分のリソースグループ名>"
export LOCATION="<自分の使うAzureリージョン。例: japaneast>"
export ACR_NAME="<自分のACR名(*.azurecr.ioの*部分)>"
export ENV_NAME="<自分の付けるContainer Apps Environment名>"
export APP_NAME="jgkg"
export IMAGE_TAG="<公開リリースのタグと揃える。例: 2026-08-28-d2-recipient-category-v2>"
```

`SUBSCRIPTION_ID`・`RESOURCE_GROUP`・`LOCATION`・`ACR_NAME`は
**このテンプレート・手順が既定値を持たない4つの値**である
(タスクブリーフの要求: 既定値に実在しそうな名前を置かない)。

## 手順

### 1. サブスクリプションを選ぶ

```bash
az account set --subscription "$SUBSCRIPTION_ID"
```

### 2. リソースグループ(無ければ作る)

```bash
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
```

### 3. ACR(無ければ作る)・Container Apps Environment(無ければ作る)

```bash
# 既にACRを持っているなら省略してよい
az acr create --resource-group "$RESOURCE_GROUP" --name "$ACR_NAME" --sku Basic

# Container Apps Environment。これがdeploy/aca.jsonのmanagedEnvironmentIdの元になる
az containerapp env create \
  --name "$ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION"

ENV_ID=$(az containerapp env show \
  --name "$ENV_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
```

### 4. イメージをビルドする(D-6b-1の道具をそのまま使う。再実装しない)

**既定の`release`経路(公開リリースから索引を取る)を使うこと。**

```bash
scripts/build-serve-images.sh release "$IMAGE_TAG"
```

これで`jgkg-serve-fuseki:local`・`jgkg-api:local`(既定の`IMAGE_TAG`環境変数
は`.env`の値。ACRに積むタグ=`$IMAGE_TAG`とは別の概念であることに注意)が
ローカルに出来る。

### 5. ACRへタグ付けしてpushする(**コマンドを書くだけ。ここでは実行しない**)

```bash
az acr login --name "$ACR_NAME"

docker tag jgkg-serve-fuseki:local "$ACR_NAME.azurecr.io/jgkg-serve-fuseki:$IMAGE_TAG"
docker tag jgkg-api:local           "$ACR_NAME.azurecr.io/jgkg-api:$IMAGE_TAG"

docker push "$ACR_NAME.azurecr.io/jgkg-serve-fuseki:$IMAGE_TAG"
docker push "$ACR_NAME.azurecr.io/jgkg-api:$IMAGE_TAG"
```

### 6. 配備する

```bash
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --template-file deploy/aca.json \
  --parameters \
      location="$LOCATION" \
      managedEnvironmentId="$ENV_ID" \
      containerAppName="$APP_NAME" \
      acrName="$ACR_NAME" \
      imageTag="$IMAGE_TAG"
      # minReplicas・maxReplicas・fusekiCpu・fusekiMemory・apiCpu・apiMemoryは
      # 既定値を使うなら省略してよい(deploy/aca.jsonのparameters.*.metadata.description参照)
```

### 7. ACRへのpull権限を、Container Appのマネージドidに与える

**上の「初回の実行で失敗しうる箇所1」がここ。** 手順6の直後は
イメージのpullがまだ失敗している可能性がある。

```bash
PRINCIPAL_ID=$(az containerapp show \
  --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query identity.principalId -o tsv)

ACR_ID=$(az acr show \
  --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --query id -o tsv)

az role assignment create \
  --assignee "$PRINCIPAL_ID" --scope "$ACR_ID" --role AcrPull
```

ロール割り当てが反映されてもレプリカが古い失敗状態のままなら、
新しいリビジョンを作って再試行させる(手順6を再実行するか、
`az containerapp revision restart`を使う)。

### 8. 配備後の検証(D-6b-1の道具をそのまま使う。再実装しない)

```bash
FQDN=$(az containerapp show \
  --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)

uv run python scripts/smoke-test-api.py --base-url "https://$FQDN"
```

`scripts/smoke-test-api.py`は5経路(`/entity/{id}`の直接アドレス経路含む。
裁定B69・B73)をすべて実データで確認する。**「200が返った」で止めない
道具が既にあるので、それを本番URLに向けて流すだけでよい。**

### 9. `minReplicas`を1にする場合(常時起動・待たせない代わりに課金が続く)

**変更箇所は1つ。**

```bash
az containerapp update \
  --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" \
  --min-replicas 1
```

(このテンプレートで管理し続けたいなら、次回`az deployment group create`
実行時に`--parameters minReplicas=1`を渡す形でもよい。どちらも
`deploy/aca.json`側のコードは変えない——`minReplicas`パラメータの値を
1箇所変えるだけ。)

## 費用について

**具体的な金額は書かない。**料金は変わるため、ここに書いた性質だけを
前提にし、実際の金額はAzureの価格ページで確認すること。

- **レプリカがゼロにスケールしている間は、そのリソース消費に対する
  課金が発生しない(Azure公式)。** これが`minReplicas`の既定を0にした
  理由(deploy/aca.jsonのパラメータ説明参照)。
- **垂直スケーリングは非対応(Azure公式)。** CPU/メモリはリビジョンで
  固定され、負荷に応じて自動では増減しない——`fusekiCpu`等のパラメータを
  変えて再配備する以外に調整手段が無い。
- ゼロへの縮退はKEDAのクールダウン期間(既定300秒。Azure公式)の後に起こる
  ——直前にアクセスが無くなってから即座にゼロになるわけではない。
- 上記以外(実際の消費量・無料枠の量・時間帯・リージョンごとの単価等)は
  この文書の範囲外。デプロイ後に実際の課金を見て確認すること。

---

## なぜこの形式(ARM JSONテンプレート)を選んだか

Bicep・ARMテンプレート・`az containerapp create --yaml`の3択のうち、
**ARM JSONテンプレート**を選んだ。

- **Bicepは構文検査に`az bicep build`(または別途bicep CLI)が要る。**
  タスクブリーフが明示的に禁じているのは`az bicep build`だが、
  Bicep単体でも構文が正しいかを確認する標準的な手段は結局azか
  bicep CLIに帰着する。**「azを1回も実行しない」制約の中で、
  構文の妥当性を実際に検査できる形にしたい**という要求と相性が悪い。
- **`az containerapp create --yaml`は、そのCLIコマンド自身が
  Environment作成やACRのロール割り当てのような前後の手順を
  含まない(コンテナアプリ単体のスペックしか記述できない)上、
  パラメータ化(サブスクリプションID等を差し替え可能にする)の
  標準的な仕組みを持たない**——変数展開は利用者側のシェル置換に
  頼ることになり、タスクブリーフが要求する「パラメータにする」を
  テンプレート自身の機能で表現できない。
- **ARM JSONテンプレートは`parameters`ブロックを標準で持ち、
  Pythonの`json.load`だけで構文の妥当性を検査できる**
  (`tests/test_workflows.py`がワークフローYAMLに対してやっている
  形と同じことを、JSONに対してできる)。`az`もbicep CLIも要らない。

## Fusekiを外部に露出しない判断について

controllerの判断(面を小さくする)に**異議は無い**。加えて、
このタスクの調査で見つけた技術的な裏付けを1つ報告する:

**`fuseki/kg.ttl`はクエリのタイムアウトや結果件数の上限を一切設定していない。**
そして、このsidecar構成では**FusekiとAPIが同じレプリカのCPU/メモリを
共有する**(タスクブリーフが明示する事実)。つまり、もし`/kg/sparql`を
外部に公開すると、認証を経ない任意の複雑なSPARQLクエリ(無制限の
JOIN・OPTIONAL等)が、**同じレプリカ上で動いているAPI(`/search`等)の
応答も一緒に遅くする、または(固定されたCPU/メモリの中で)
落としうる**——「更新エンドポイントが無いから安全」という
controllerの検討済みの論点に加えて、「読み取り専用でも、
リソース制限の無いクエリはsidecar構成では隣のAPIまで含めて
危険になる」という論点がある。将来公開するとしても、クエリの
タイムアウト・結果件数上限(Fuseki側の設定、または別レプリカへの
分離)を先に用意すべきだと考える。
