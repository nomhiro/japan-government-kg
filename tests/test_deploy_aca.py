"""Azure Container Apps配備定義(`deploy/aca.json`)の構文検査(D-6b-2)。

**`az`もbicep CLIも使わない。** `az bicep build`はazコマンドであり、
このタスクは1回も実行しないことが条件——`tests/test_workflows.py`が
ワークフローYAMLに対してやっている形(`yaml.safe_load`で構文検査するだけで、
GitHub Actions自体は動かさない)と同じことを、ARMテンプレート(JSON)に
対して`json.load`で行う。

**この検査が確認できるのはJSONとして妥当なこと・想定するキーが
あることだけ。** `az deployment group create`が実際に受理するか
(プロパティ名・値の型がAzure Resource Manager側の検証を通るか)は
ここでは確認していない。

**2026-09-10追記**: かつてここには「この配備定義は一度もAzureに対して
実行されていない」と書いてあったが、**それは偽になった。**
2026-09-06に初回実行(裁定B90)、2026-09-10に `Succeeded` で再配備している
(裁定B91)。**この検査の役割は「azを実行する前に構文と構造の誤りで
気づくこと」であり、それは変わらない。**
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "deploy" / "aca.json"


def _load() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def test_template_parses_as_json() -> None:
    """壊れたJSON(引用符抜け等)なら`az`を実行する前にここで気づける。"""
    doc = _load()
    assert isinstance(doc, dict)
    assert "$schema" in doc and isinstance(doc["$schema"], str) and doc["$schema"]


def test_exactly_one_container_app_resource() -> None:
    doc = _load()
    resources = doc["resources"]
    assert isinstance(resources, list) and resources
    container_apps = [r for r in resources if r.get("type") == "Microsoft.App/containerApps"]
    assert len(container_apps) == 1, (
        f"Microsoft.App/containerApps が {len(container_apps)} 件(1件のはず)"
    )


def _container_app() -> dict:
    doc = _load()
    return next(r for r in doc["resources"] if r["type"] == "Microsoft.App/containerApps")


def test_required_parameters_have_no_default_value() -> None:
    """既定値に実在しそうな名前を置かない(タスクブリーフの要求)。

    ARMテンプレートで `defaultValue` を持たない = デプロイ時に利用者が
    明示的に値を渡さない限り失敗する、という設計にした。
    """
    doc = _load()
    params = doc["parameters"]
    # **環境ごとに違う値**(利用者のサブスクリプションに固有のもの)。
    # ここに実在しそうな既定値を置くと、他人の環境を指したまま
    # デプロイが通ってしまう
    required = {
        "location",
        "managedEnvironmentId",
        "acrName",
        "imageTag",
        "acrPullIdentityId",  # 裁定B91でユーザー割り当てIDに変えたときに増えた
        "chatManagedIdentityClientId",  # E-2(裁定B92)。チャットのマネージドID(クライアントID)
    }
    assert required <= set(params), f"必須パラメータが足りない: {required - set(params)}"

    # **両方向で縛る**: 既定値を持たないパラメータの集合が、上とちょうど一致すること。
    # 片方向(`required` に既定値が無い)だけだと、**新しい必須パラメータが
    # 増えたときに検査対象から漏れる** —— 実際に `acrPullIdentityId` を
    # 足したとき、手書きの集合に入れ忘れて漏れた(再発欠陥1)。
    without_default = {n for n, spec in params.items() if "defaultValue" not in spec}
    assert without_default == required, (
        f"既定値を持たないパラメータの集合がずれている: "
        f"余分={without_default - required} 不足={required - without_default}"
    )


def test_min_replicas_defaults_to_zero() -> None:
    """裁定: 資金の無い公開財なのでスケールゼロを既定にする。"""
    doc = _load()
    assert doc["parameters"]["minReplicas"]["defaultValue"] == 0


def test_image_tag_is_not_hardcoded_to_latest() -> None:
    """`:latest`を既定にしない(D-6b-1のOCIラベルによる追跡可能性を壊さない)。

    ファイル全体を素朴に文字列検索すると2重に誤検出する:
    (1) `deploymentTemplate.json`(ARMの`$schema`)を小文字化すると
    "latest" が部分文字列として現れる。(2) `imageTag`パラメータの
    説明文自身が「:latestを既定にしない」と書いており、その説明文の
    中の ":latest" を検出してしまう。**実際に配備されるイメージ参照
    (`variables.fusekiImage`/`variables.apiImage`とそれが使う
    `parameters.imageTag`)だけ**を見る。
    """
    doc = _load()
    assert "defaultValue" not in doc["parameters"]["imageTag"]
    # **どのタグパラメータを参照するかは変数ごとに違う(裁定B102)。**
    # `apiImageTag` を足して、KGを作り直さずにAPIだけ差し替えられるように
    # した。守るべき性質は「タグがパラメータ由来であること」なので、
    # 変数ごとに**期待するパラメータ名**を明示して固定する
    # (どれでもよい、にすると `latest` 固定を見逃す余地が戻る)。
    expected_tag_parameter = {
        "fusekiImage": "imageTag",
        "apiImage": "apiImageTag",
    }
    assert set(expected_tag_parameter) == {"fusekiImage", "apiImage"}, (
        "イメージ変数が増減したら、この期待表も直すこと"
    )
    for var_name, tag_parameter in expected_tag_parameter.items():
        expr = doc["variables"][var_name]
        assert f"parameters('{tag_parameter}')" in expr, (
            f"variables.{var_name} が {tag_parameter} パラメータを参照していない: {expr}"
        )
        assert ":latest" not in expr
    # `apiImageTag` の既定値は**タグの literal ではなく imageTag からの導出**で
    # あること(既定で今までと同じ挙動になり、かつ特定のタグに固定されない)
    api_tag_default = doc["parameters"]["apiImageTag"]["defaultValue"]
    assert api_tag_default == "[parameters('imageTag')]", (
        f"apiImageTag の既定値が imageTag からの導出になっていない: {api_tag_default}"
    )


def test_fuseki_is_not_reachable_from_ingress() -> None:
    """APIの4経路だけを外に出す。Fuseki(3030)はingressのtargetPortにしない。"""
    app = _container_app()
    ingress = app["properties"]["configuration"]["ingress"]
    assert ingress["external"] is True
    assert ingress["targetPort"] == 8000, "ingressのtargetPortがAPI(8000)を指していない"
    assert ingress["targetPort"] != 3030, "ingressがFuseki(3030)に直接繋がっている"


def test_sidecar_has_exactly_two_containers() -> None:
    app = _container_app()
    containers = app["properties"]["template"]["containers"]
    names = {c["name"] for c in containers}
    assert names == {"fuseki", "api"}, f"想定外のコンテナ構成: {names}"


def test_api_container_points_at_localhost_fuseki() -> None:
    """同一アプリ内はサービス名DNSではなくlocalhost共有(タスクブリーフの前提)。"""
    app = _container_app()
    containers = app["properties"]["template"]["containers"]
    api = next(c for c in containers if c["name"] == "api")
    env = {e["name"]: e["value"] for e in api.get("env", []) if "value" in e}
    assert env.get("JGKG_SPARQL_ENDPOINT") == "http://localhost:3030/kg/sparql"


def test_api_container_has_chat_env_vars_wired_from_the_parameter() -> None:
    """E-2(裁定B92)。`AZURE_CLIENT_ID`はパラメータ参照(直書きの実IDにしない)。

    `docker-compose.serve.yml`にも同名の環境変数を足している——
    片方だけだと部分適用(再発欠陥3。task-E2-brief.md)。
    """
    app = _container_app()
    containers = app["properties"]["template"]["containers"]
    api = next(c for c in containers if c["name"] == "api")
    env = {e["name"]: e.get("value") for e in api.get("env", [])}
    assert env.get("AZURE_CLIENT_ID") == "[parameters('chatManagedIdentityClientId')]", (
        "AZURE_CLIENT_IDが実在しそうな値を直書きしている、またはパラメータ参照になっていない"
    )
    assert env.get("JGKG_AOAI_ENDPOINT") == "https://aif-jgkg.cognitiveservices.azure.com"
    assert env.get("JGKG_AOAI_DEPLOYMENT") == "gpt-5.6-luna"
    assert env.get("JGKG_AOAI_API_VERSION")

    # **資格情報ではないことの直接確認**: このパラメータの説明文にGUID自体
    # (実在するクライアントID)を書いていないこと。値は`az`で都度取得する運用
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "d1fa2256-34a4-4682-ab91-3428d025dafe" not in text, (
        "実在するクライアントIDをテンプレートに直書きしている"
    )


def test_registry_pull_uses_managed_identity_not_a_credential() -> None:
    """資格情報を一切書かない(マネージドIDでpullする)。

    **`UserAssigned` であること(裁定B91)。** かつて `SystemAssigned` だったが、
    **システム割り当てIDはContainer Appを作成した後にしか存在しない**ため、
    同じARM操作の中で走るイメージのpullがAcrPull無しで必ず失敗する
    ——2026-09-06に実際にそうなった。**IDを先に作ってAcrPullを付けてから
    配備すれば1回で成功する。** 資格情報を書かないという本質は変えていない。
    """
    app = _container_app()
    registries = app["properties"]["configuration"]["registries"]
    assert len(registries) == 1
    identity = app["identity"]
    assert identity["type"] == "UserAssigned", identity
    # 参照先はパラメータであること(実在のリソースIDを埋め込まない)
    assert list(identity["userAssignedIdentities"]) == ["[parameters('acrPullIdentityId')]"]
    assert registries[0]["identity"] == "[parameters('acrPullIdentityId')]"

    # **`SystemAssigned` へ戻さないこと**(初回デプロイが必ず失敗する形に戻る)
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "SystemAssigned" not in text, "システム割り当てIDに戻すと初回デプロイが必ず失敗する(裁定B91)"

    for forbidden in ("passwordSecretRef", "username", "clientSecret", "\"password\""):
        assert forbidden not in text, f"資格情報らしき鍵がテンプレートに含まれている: {forbidden}"


def test_max_replicas_defaults_to_one_while_chat_is_unauthenticated() -> None:
    """**レプリカ上限は1(裁定B92)。**

    チャット経路は認証を持たない公開エンドポイントで、LLMの費用は
    他人に発生させられる。1リクエストの道具呼び出し回数・IPごとの
    レート制限・1日のトークン上限は**プロセス内のカウンタ**で数えるため、
    **レプリカが複数だと上限がレプリカ数倍に緩む。**

    月400〜480訪問規模(裁定B89の算術)のデモに複数レプリカは要らないので、
    **上限を正確にする方を採る。** 認証を入れたらこの判断を見直す
    ——そのときはこのテストも一緒に直すこと。
    """
    doc = _load()
    assert doc["parameters"]["maxReplicas"]["defaultValue"] == 1
    # 理由が書かれていること(値だけ変えて理由を失わせない)
    desc = doc["parameters"]["maxReplicas"]["metadata"]["description"]
    assert "裁定B92" in desc, desc
