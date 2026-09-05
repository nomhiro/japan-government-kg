"""Azure Container Apps配備定義(`deploy/aca.json`)の構文検査(D-6b-2)。

**`az`もbicep CLIも使わない。** `az bicep build`はazコマンドであり、
このタスクは1回も実行しないことが条件——`tests/test_workflows.py`が
ワークフローYAMLに対してやっている形(`yaml.safe_load`で構文検査するだけで、
GitHub Actions自体は動かさない)と同じことを、ARMテンプレート(JSON)に
対して`json.load`で行う。

**この検査が確認できるのはJSONとして妥当なこと・想定するキーが
あることだけ。** `az deployment group create`が実際に受理するか
(プロパティ名・値の型がAzure Resource Manager側の検証を通るか)は
確認していない——`docs/deploy-aca.md`の「初回の実行で失敗しうる箇所」
に明記した通り、この配備定義は一度もAzureに対して実行されていない。
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
    required = {"location", "managedEnvironmentId", "acrName", "imageTag"}
    assert required <= set(params), f"必須パラメータが足りない: {required - set(params)}"
    for name in required:
        assert "defaultValue" not in params[name], (
            f"parameters.{name} に defaultValue がある(既定値を持たない設計のはず)"
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
    for var_name in ("fusekiImage", "apiImage"):
        expr = doc["variables"][var_name]
        assert "parameters('imageTag')" in expr, (
            f"variables.{var_name} が imageTag パラメータを参照していない: {expr}"
        )
        assert ":latest" not in expr


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


def test_registry_pull_uses_managed_identity_not_a_credential() -> None:
    """資格情報を一切書かない(システム割り当てマネージドIDでpullする)。"""
    app = _container_app()
    registries = app["properties"]["configuration"]["registries"]
    assert len(registries) == 1
    assert registries[0]["identity"] == "system"
    assert app["identity"]["type"] == "SystemAssigned"

    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    for forbidden in ("passwordSecretRef", "username", "clientSecret", "\"password\""):
        assert forbidden not in text, f"資格情報らしき鍵がテンプレートに含まれている: {forbidden}"
