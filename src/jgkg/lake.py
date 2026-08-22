"""取得時点のスナップショットを不変で保持する。

コネクタは「取得してここに保存する」だけを行う。パースの失敗と取得の失敗を
分離し、パーサ修正時に再取得を不要にするため(設計書§6.1)。
"""
import datetime
import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from jgkg.config import get_settings
from jgkg.sources import get_source


@dataclass(frozen=True)
class Snapshot:
    source_id: str
    fetched_on: datetime.date
    path: Path
    sha256: str
    byte_size: int


def _dir(source_id: str, fetched_on: datetime.date) -> Path:
    root = Path(get_settings().lake_dir)
    return root / source_id / fetched_on.isoformat()


def save(source_id: str, fetched_on: datetime.date, filename: str, content: bytes) -> Snapshot:
    """スナップショットを保存する。既に存在する場合は上書きせず例外を投げる。"""
    get_source(source_id)  # 未登録のソースを弾く
    d = _dir(source_id, fetched_on)
    d.mkdir(parents=True, exist_ok=True)
    target = d / filename
    if target.exists():
        raise FileExistsError(
            f"スナップショットは不変である。既に存在する: {target}"
        )
    target.write_bytes(content)

    snap = Snapshot(
        source_id=source_id,
        fetched_on=fetched_on,
        path=target,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
    )
    meta = d / f"{filename}.meta.json"
    meta.write_text(
        json.dumps(
            {**asdict(snap), "path": str(snap.path), "fetched_on": fetched_on.isoformat()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return snap


def load(source_id: str, fetched_on: datetime.date, filename: str) -> bytes:
    return (_dir(source_id, fetched_on) / filename).read_bytes()


def list_snapshots(source_id: str) -> list[Snapshot]:
    root = Path(get_settings().lake_dir) / source_id
    if not root.exists():
        return []
    out: list[Snapshot] = []
    for meta in sorted(root.glob("*/*.meta.json")):
        data = json.loads(meta.read_text(encoding="utf-8"))
        out.append(
            Snapshot(
                source_id=data["source_id"],
                fetched_on=datetime.date.fromisoformat(data["fetched_on"]),
                path=Path(data["path"]),
                sha256=data["sha256"],
                byte_size=data["byte_size"],
            )
        )
    return out


def latest(source_id: str) -> datetime.date | None:
    snaps = list_snapshots(source_id)
    return max((s.fetched_on for s in snaps), default=None)
