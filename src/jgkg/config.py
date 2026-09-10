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

    # =========================================================================
    # E-2(裁定B92): オントロジーをAgenticに調査するチャット。
    # =========================================================================
    #
    # **エンドポイント・配備名・API版は資格情報ではない**(公開リポジトリに
    # 書いてよい識別子。キー自体は無く、認証はazure-identityの
    # `DefaultAzureCredential`がマネージドID/`az login`セッションから取る)。
    # controllerが実測済みの値(task-E2-brief.md)をそのまま既定にする——
    # `base_uri`と同じ「実行時の設定というより、この資源の同一性」という位置づけ
    # ではあるが、こちらはデプロイ先ごとに差し替えても生成物に焼き込まれる
    # 値ではないため、`.env`での上書きを禁じる理由は無い。
    aoai_endpoint: str = "https://aif-jgkg.cognitiveservices.azure.com"
    aoai_deployment: str = "gpt-5.6-luna"
    #: 2026-09-11実測(このタスク自身): Chat Completions + `tools` + このモデルは
    #: このAPI版でHTTP 200・`finish_reason="tool_calls"`が返る(公式ドキュメントは
    #: 「gpt-5.6系はChat Completions+関数ツールを`reasoning_effort=none`無しでは
    #: 拒否する」と書いているが、この配備・このAPI版では実測がそれと異なった——
    #: 実測を優先する。E-2報告に検証の詳細を書く)。
    aoai_api_version: str = "2024-10-21"

    # **裁定B92裁定3: 費用の上限を構造で縛る。値は全てここから読む(直書きしない)。**
    #: 1リクエストあたりの道具呼び出し回数の上限(既定6回程度、の「程度」は
    #: ブリーフの言葉であり、6をそのまま既定にした——法令→府省→事業→支出→法人の
    #: 縦スライス(4ホップ)を辿るのに`get_neighborhood`/`find_path`を数回、
    #: `get_ontology`で語彙を1〜2回引く、という想定の調査に足りる回数として)。
    chat_tool_call_limit: int = 6
    #: 1回のChat Completions呼び出りに許す`max_completion_tokens`(推論トークン込み)。
    #: 2026-09-11実測: 5文字の応答に`reasoning_tokens: 6`(トリビアルな道具呼び出し1件)。
    #: 実際のオントロジー調査(このタスクの手動確認)では発話の長さに応じて
    #: 増える——安全マージンを取った値(実測はE-2報告に書く。ここに転記しない)。
    chat_max_completion_tokens: int = 8000
    #: IPごとの分あたりレート制限。**根拠が無い**(実測に基づく値ではない)——
    #: 人間が1分に叩けるであろう回数の常識的な上限として置いた構造的な判断
    #: (`deploy/aca.json`のfusekiCpu等と同じ「実測していないことを明記する」作法)。
    chat_rate_limit_per_minute: int = 5
    #: 1日あたりのトークン上限(プロセス内カウンタ。**`maxReplicas=1`前提**
    #: ——裁定B92裁定3(4)。レプリカが増えるとこの上限はレプリカ数倍に緩む)。
    #: **根拠が無い**。月400〜480訪問規模のデモに対する構造的な当て推量であり、
    #: 実測して調整すること。
    chat_daily_token_budget: int = 500_000

    @field_validator("base_uri")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
