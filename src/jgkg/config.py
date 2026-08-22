"""設定の単一の入口。ベースURIのドメイン文字列はここにしか存在しない。"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JGKG_", env_file=".env", extra="ignore")

    # ドメイン未確定のため既定は開発用。確定したら .env で上書きする(設計書§4.2)
    base_uri: str = "http://localhost:8080/kg"
    lake_dir: str = "data/lake"
    artifact_dir: str = "data/artifact"
    quarantine_dir: str = "data/quarantine"

    @field_validator("base_uri")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
