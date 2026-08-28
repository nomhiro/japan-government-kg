"""設定の単一の入口。

**ベースURIだけは「実行時の設定」ではない。** 詳細は `base_uri` のコメントを読むこと。
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JGKG_", env_file=".env", extra="ignore")

    # ドメイン未確定のため既定は開発用(設計書§4.2)。
    #
    # **この既定値がオントロジーの同一性そのものである。`.env` で上書きしても
    # 生成物は追随しない。** ベースURIは `schema/*.yaml` の `id:`/`prefixes:`、
    # 公理オーバーレイ、CQクエリの `PREFIX`、そしてそれらから生成した
    # `schema/generated/**` に文字列として焼き込まれる。`.env` だけを変えると
    # `emit` は新しい名前空間で書き、SHACLの `sh:targetClass` は旧名前空間を
    # 指すため、**シェイプが1ノードも対象にせず全グラフが合格する**(検証ゲートが
    # 沈黙する)。
    #
    # ドメインを確定したときの手順は次の2つで、`.env` での上書きではない:
    #
    #     uv run python -m jgkg.base_uri https://<確定したドメイン>/kg
    #     ./scripts/generate-schema.sh
    #
    # 整合しているかは `uv run python -m jgkg.base_uri --check`(CIも実行する)。
    # 上書きしたまま古い生成物で走らせた場合は `validate.validate_dataset` が例外にする。
    base_uri: str = "https://jgkg.norr-tech.com"
    lake_dir: str = "data/lake"
    artifact_dir: str = "data/artifact"
    quarantine_dir: str = "data/quarantine"
    # 法人番号 全件データのURL。月次で変わる selDlFileNo を含むため、
    # ソースコードには書けない(.env.example のコメントに取得手順がある)。
    # 空文字列も「未設定」として扱う(.env.example が `JGKG_HOUJIN_BANGOU_URL=`
    # という空値をコミットしており、.env にそのままコピーされると
    # pydantic-settings は None ではなく "" を読む——jgkg.fetch のガードは
    # 両方を弾く必要がある)
    houjin_bangou_url: str = ""

    # D-3: API層(src/jgkg/api/)がクエリを投げるFusekiのSPARQLエンドポイント。
    # **これは`base_uri`とは違い、本当の「実行時の設定」である**——オントロジーの
    # 同一性(ベースURI)とは無関係に、デプロイ先ごとに変わってよい値なので
    # `.env`での上書きが正しい経路(base_uri.pyのSOURCE_GLOBSにも入れない)。
    # 既定値はscripts/run_cq.pyのDEFAULT_ENDPOINTと同じ
    # (ローカルのFuseki。base_uri.pyのALLOWED_EXTERNAL_HOSTSが
    # "localhost:3030"を既に許可済み)
    sparql_endpoint: str = "http://localhost:3030/kg/sparql"

    @field_validator("base_uri")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
