"""原本とチェックポイントを持つ収集実行。失敗しても取得済み原本を再利用する。"""
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from jgkg._io import atomic_write


def now() -> str:
    return datetime.now(UTC).isoformat()


class CollectionRun:
    def __init__(self, root: Path, collection_id: str, run_id: str, scope: dict):
        for value in (collection_id, run_id):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", value):
                raise ValueError("実行IDには英数字・ハイフン・下線のみ使用できる")
        self.directory = root / collection_id / run_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "run.json"
        self.scope = scope
        self.collection_id = collection_id
        self.run_id = run_id

    @contextmanager
    def locked(self):
        lock = self.directory / ".lock"
        # 強制終了後のロックは自動削除しない。稼働プロセスの確認後に回復する。
        with lock.open("x", encoding="utf-8") as stream:
            import os
            stream.write(str(os.getpid()))
        try:
            if self.path.exists():
                self.state = json.loads(self.path.read_text(encoding="utf-8"))
                if self.state["scope"] != self.scope:
                    raise ValueError("同じrun_idを異なる対象範囲には再利用できない")
            else:
                self.state = {"collection_id": self.collection_id, "run_id": self.run_id,
                                  "scope": self.scope, "started_at": now(), "snapshots": {}, "attempts": []}
            self.state["attempts"].append({"started_at": now()})
            self.state.update(status="running", errors=[], finished_at=None)
            self.save()
            try:
                yield self
            except BaseException as exc:
                self.state.update(status="failed", errors=[str(exc)], finished_at=now())
                self.state["attempts"][-1].update(status="failed", finished_at=now(),
                                                  error=str(exc))
                self.save()
                raise
        finally:
            lock.unlink()

    def save(self):
        atomic_write(self.path, json.dumps(self.state, ensure_ascii=False,
                                          indent=2).encode("utf-8"))

    def cached(self, key: str) -> bytes | None:
        record = self.state["snapshots"].get(key)
        if record is None:
            return None
        path = self.directory / record["filename"]
        if not path.is_file():
            return None
        data = path.read_bytes()
        return data if hashlib.sha256(data).hexdigest() == record["sha256"] else None

    def store(self, key: str, url: str, data: bytes, content_type: str):
        digest = hashlib.sha256(data).hexdigest()
        # 内容アドレスで同日更新や再試行時にも原本を上書きしない。
        name = f"{digest}.json"
        atomic_write(self.directory / name, data)
        previous = self.state["snapshots"].get(key)
        if previous is not None:
            self.state.setdefault("snapshot_history", []).append({"key": key, **previous})
        self.state["snapshots"][key] = {"filename": name, "url": url, "fetched_at": now(),
                                           "sha256": digest, "bytes": len(data),
                                           "content_type": content_type, "status_code": 200}
        self.save()

    def finish(self, complete: bool, **counts):
        self.state.update(status="complete" if complete else "partial",
                          finished_at=now(), **counts)
        if complete:
            self.state["last_complete_at"] = self.state["finished_at"]
        self.state["attempts"][-1].update(status=self.state["status"], finished_at=now())
        self.save()
