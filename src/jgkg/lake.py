"""取得時点のスナップショットを不変で保持する。

コネクタは「取得してここに保存する」だけを行う。パースの失敗と取得の失敗を
分離し、パーサ修正時に再取得を不要にするため(設計書§6.1)。
"""
import datetime
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from jgkg._io import atomic_write
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
    atomic_write(target, content)
    atomic_write(meta_path, meta_json.encode("utf-8"))
    return snap


def load(source_id: str, fetched_on: datetime.date, filename: str) -> bytes:
    return (_dir(source_id, fetched_on) / filename).read_bytes()


def path_of(source_id: str, fetched_on: datetime.date, filename: str) -> Path:
    """スナップショットのファイルパスを返す。

    大きなファイルを bytes で読まずにストリームで処理したい呼び出し側のために、
    パスだけを渡す。存在確認はしない(呼び出し側が open で判断する)。
    """
    return _dir(source_id, fetched_on) / filename


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


def latest_before(source_id: str, before: datetime.date) -> Snapshot | None:
    """`before` 以前(**閉区間。`fetched_on <= before` を含む**)の最新スナップショットを返す。

    Task 10の差分検出(更新の一巡)が「前リリース時点でこのソースはどの版
    だったか」を調べるために使う。**閉区間にする理由**: `previous_release`
    (前リリースの日付)そのものと同じ日に取得されたスナップショットは、
    その前リリースで実際に使われた版である可能性が高い(単一ソースの
    リリースでは`release`は`fetched_on`と一致する)。厳密未満(`<`)にすると、
    「前リリースの当日に取得した版」を1つ古い版だと取り違え、まだ存在しない
    中間スナップショットを引き継ごうとして縁に落ちる。

    ソース1件が複数ファイルに分かれる場合(rs-systemの事業年度ごと15本)は、
    `list_snapshots` が返す複数件のうち**どれか1件**を返す(全件が同じ日付
    ディレクトリに属するため、`fetched_on` を知るには十分だが、ファイル集合
    全体の比較が必要な呼び出し側は、この関数が返す `.fetched_on` で
    `list_snapshots` を絞り込んで全件を取り直すこと)。
    """
    candidates = [s for s in list_snapshots(source_id) if s.fetched_on <= before]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.fetched_on, s.path.name))
