"""成果物ビルドとmanifest。

インデックスをCIが生成する成果物として扱い、実行環境から切り離す
(設計書§6.3)。content-addressed にして破損を検出し、Jenaバージョンを
記録して実行側と照合できるようにする。
"""
import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel


class Manifest(BaseModel):
    release: str
    created_on: str
    jena_version: str
    sha256: str
    byte_size: int
    triple_count: int
    graphs: list[str]
    sources: dict[str, str]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan_nquads(path: Path) -> tuple[int, list[str]]:
    """N-Quadsを1行ずつ数え、登場するグラフURIを集める。

    全体をメモリに載せないのは、全件データで数千万行になるため。
    """
    count = 0
    graphs: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            count += 1
            if line.endswith("."):
                parts = line[:-1].strip().rsplit("<", 1)
                if len(parts) == 2 and parts[1].endswith(">"):
                    graphs.add(parts[1][:-1])
    return count, sorted(graphs)


def build_manifest(
    nquads: Path,
    tarball: Path,
    jena_version: str,
    release: str,
    sources: dict[str, str],
) -> Manifest:
    if not jena_version:
        raise ValueError(
            "Jenaバージョンが空である。TDB2のオンディスク形式はJenaのバージョンに"
            "紐づくため、記録を省略できない(設計書§6.3)"
        )
    triple_count, graphs = _scan_nquads(nquads)
    return Manifest(
        release=release,
        created_on=release,
        jena_version=jena_version,
        sha256=_sha256(tarball),
        byte_size=tarball.stat().st_size,
        triple_count=triple_count,
        graphs=graphs,
        sources=sources,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    """同一ディレクトリの一時ファイルに書いてから rename する。

    os.replace は同一ファイルシステム上でアトミックで、Windowsでも既存ファイルを
    置き換えられる(jgkg.lake._atomic_write と同じ理由)。manifestは成果物の整合性
    を保証する唯一の記録なので、書き込み途中で落ちて壊れた状態を残してはならない。
    """
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_manifest(m: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(m.model_dump(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, data)


def verify_manifest(manifest_path: Path, tarball: Path) -> None:
    """成果物のsha256がmanifestと一致することを確かめる。

    実行側が起動時にこれを呼ぶことで、Neptuneのsegment自動修復に相当する
    「壊れたデータを検出する」能力をチェックサムで安価に得る。
    """
    m = Manifest(**json.loads(manifest_path.read_text(encoding="utf-8")))
    actual = _sha256(tarball)
    if actual != m.sha256:
        raise ValueError(
            f"成果物のsha256が一致しない。manifest={m.sha256} actual={actual}"
        )
