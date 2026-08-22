"""コネクタの共通処理。取得してレイクに保存するだけを行う。

パース・変換は一切しない。設計書§6.1の[1]をこの責務に限定するのは、
パースの失敗と取得の失敗を分離するため。
"""
import datetime
from collections.abc import Callable
from dataclasses import dataclass

from jgkg import lake
from jgkg.lake import Snapshot


@dataclass(frozen=True)
class FetchResult:
    snapshot: Snapshot
    skipped: bool


def _existing(source_id: str, fetched_on: datetime.date, filename: str) -> Snapshot | None:
    for snap in lake.list_snapshots(source_id):
        if snap.fetched_on == fetched_on and snap.path.name == filename:
            return snap
    return None


def fetch_to_lake(
    source_id: str,
    fetched_on: datetime.date,
    filename: str,
    fetcher: Callable[[], bytes],
) -> FetchResult:
    """冪等な取得。既にスナップショットがあれば取得せずスキップする。"""
    existing = _existing(source_id, fetched_on, filename)
    if existing is not None:
        return FetchResult(snapshot=existing, skipped=True)

    content = fetcher()
    snap = lake.save(source_id, fetched_on, filename, content)
    return FetchResult(snapshot=snap, skipped=False)
