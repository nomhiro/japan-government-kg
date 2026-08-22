"""取得時点のスナップショットを不変で保持する。

コネクタは「取得してここに保存する」だけを行う。パースの失敗と取得の失敗を
分離し、パーサ修正時に再取得を不要にするため(設計書§6.1)。
"""
import datetime
import hashlib
import json
import os
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
    """スナップショットを保存する。

    メタデータファイルの存在を「コミット済み」の印として使う。データ本体だけが
    残った中途半端な状態は未コミットとみなし、再保存を許す。これにより
    「一度の失敗が恒久的な再取得不能を生む」ことを避ける(設計書§11.1の冪等性)。
    """
    get_source(source_id)  # 未登録のソースを弾く
    d = _dir(source_id, fetched_on)
    d.mkdir(parents=True, exist_ok=True)
    target = d / filename
    meta_path = d / f"{filename}.meta.json"

    if meta_path.exists():
        raise FileExistsError(
            f"スナップショットは不変である。既にコミット済み: {target}"
        )

    snap = Snapshot(
        source_id=source_id,
        fetched_on=fetched_on,
        path=target,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
    )
    meta_json = json.dumps(
        {**asdict(snap), "path": str(snap.path), "fetched_on": fetched_on.isoformat()},
        ensure_ascii=False,
        indent=2,
    )

    # データ本体 → メタデータ の順に、それぞれアトミックに置く。
    # 途中で落ちてもメタデータが無いので未コミットと判定され、再実行できる
    _atomic_write(target, content)
    _atomic_write(meta_path, meta_json.encode("utf-8"))
    return snap


def _atomic_write(path: Path, data: bytes) -> None:
    """同一ディレクトリの一時ファイルに書いてから rename する。

    os.replace は同一ファイルシステム上でアトミックで、Windowsでも既存ファイルを
    置き換えられる。一時ファイル名を隠しファイルにしているのは、list_snapshots の
    glob に拾われないようにするため。
    """
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


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
