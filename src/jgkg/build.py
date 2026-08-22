"""成果物ビルドとmanifest。

インデックスをCIが生成する成果物として扱い、実行環境から切り離す
(設計書§6.3)。content-addressed にして破損を検出し、Jenaバージョンを
記録して実行側と照合できるようにする。
"""
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from jgkg._io import atomic_write


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


def _count_triples(path: Path) -> int:
    """N-Quadsの行数を数える。

    全体をメモリに載せない(実データでは数千万行になる)。
    **グラフURIはここで推測しない。** リテラルには空白も `>` も含まれうるため、
    テキストからグラフ項を判別するには本物の字句解析が必要で、素朴な文字列操作では
    3項トリプル行のオブジェクトIRIをグラフURIと誤認する。グラフ一覧は Dataset を
    持つ呼び出し側から受け取る。
    """
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            count += 1
    return count


def build_manifest(
    nquads: Path,
    tarball: Path,
    jena_version: str,
    release: str,
    sources: dict[str, str],
    graphs: list[str],
) -> Manifest:
    if not jena_version:
        raise ValueError(
            "Jenaバージョンが空である。TDB2のオンディスク形式はJenaのバージョンに"
            "紐づくため、記録を省略できない(設計書§6.3)"
        )
    return Manifest(
        release=release,
        created_on=release,
        jena_version=jena_version,
        sha256=_sha256(tarball),
        byte_size=tarball.stat().st_size,
        triple_count=_count_triples(nquads),
        graphs=sorted(graphs),
        sources=sources,
    )


def write_manifest(m: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(m.model_dump(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write(path, data)


def verify_manifest(
    manifest_path: Path,
    tarball: Path,
    expected_jena_version: str | None = None,
) -> None:
    """成果物のsha256と、任意でJenaバージョンが一致することを確かめる。

    実行側が起動時にこれを呼ぶことで、Neptuneのsegment自動修復に相当する
    「壊れたデータを検出する」能力をチェックサムで安価に得る。

    `expected_jena_version` を渡すと、実行側のJenaバージョンが成果物を作った
    ものと一致するかも確かめる。**TDB2のオンディスク形式はJenaのバージョンに
    紐づく**ため、記録しただけで照合しなければ意味がない。
    """
    m = Manifest(**json.loads(manifest_path.read_text(encoding="utf-8")))
    actual = _sha256(tarball)
    if actual != m.sha256:
        raise ValueError(
            f"成果物のsha256が一致しない。manifest={m.sha256} actual={actual}"
        )
    if expected_jena_version is not None and expected_jena_version != m.jena_version:
        raise ValueError(
            "Jenaバージョンが一致しない。TDB2のオンディスク形式はバージョンに紐づくため"
            f"読めない可能性がある。manifest={m.jena_version} runtime={expected_jena_version}"
        )
