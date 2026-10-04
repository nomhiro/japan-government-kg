"""継続収集の台帳。取得や公開は行わず、検証済みの手順を出力する。

python -m jgkg.collection list
python -m jgkg.collection show rs-project-details
python -m jgkg.collection validate
"""
import argparse
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from jgkg.sources import SOURCES

REGISTRY_PATH = Path(__file__).with_name("collection_registry.json")


class CollectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    title: str = Field(min_length=1)
    priority: int = Field(ge=1)
    publisher: str = Field(min_length=1)
    source_id: str | None
    entrypoints: list[HttpUrl] = Field(min_length=1)
    evidence_urls: list[HttpUrl] = Field(min_length=1)
    researched_on: date
    evidence_level: Literal["http_sample", "official_document", "needs_confirmation"]
    access: Literal["api", "bulk", "html", "pdf", "mixed"]
    auth: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    identity: list[str] = Field(min_length=1)
    discover: str = Field(min_length=1)
    retrieve: str = Field(min_length=1)
    refresh: str = Field(min_length=1)
    check_interval_days: int = Field(ge=1)
    interval_basis: str = Field(min_length=1)
    completeness: str = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    terms_status: Literal["registered_source", "needs_review"]
    implementation: Literal["existing_connector", "local_snapshot", "planned"]
    implementation_scope: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    kg_mapping: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_source(self):
        if self.source_id is not None and self.source_id not in SOURCES:
            raise ValueError(f"未登録の出典ID: {self.source_id}")
        if self.terms_status == "registered_source" and self.source_id is None:
            raise ValueError("規約確認済みソースへの参照が必要")
        if self.implementation != "planned" and self.source_id is None:
            raise ValueError("既存の取得経路には出典IDが必要")
        return self


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    collections: list[CollectionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [item.id for item in self.collections]
        if len(ids) != len(set(ids)):
            raise ValueError("収集IDが重複している")
        return self


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    return Registry.model_validate_json(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="継続収集の台帳と実装順序")
    parser.add_argument("action", choices=["list", "show", "validate"])
    parser.add_argument("collection_id", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        registry = load_registry()
    except (ValueError, OSError) as exc:
        parser.exit(1, f"収集台帳エラー: {exc}\n")
    items = sorted(registry.collections, key=lambda item: (item.priority, item.id))
    if args.action == "show":
        selected = [item for item in items if item.id == args.collection_id]
        if not selected:
            parser.error("showには登録済み収集IDを指定する")
        print(selected[0].model_dump_json(indent=2))
    elif args.collection_id:
        parser.error("収集IDはshowのみで指定できる")
    elif args.action == "validate":
        print(f"収集台帳: {len(items)}件、構造・出典参照・ID重複の検査に適合")
    elif args.json:
        print(json.dumps([item.model_dump(mode="json") for item in items],
                         ensure_ascii=False, indent=2))
    else:
        print("確認間隔は運用設計値。定期実行は未設定。")
        for item in items:
            print(f"{item.priority:02d} {item.id}: {item.title}"
                  f" / {item.implementation} / 確認{item.check_interval_days}日ごと")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
