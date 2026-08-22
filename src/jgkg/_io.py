"""ファイル入出力の共通処理。

アトミック書き込みは lake(スナップショット)と build(manifest)の両方で必要で、
同一のロジックが重複していたため切り出した。片方だけ直すと壊れる類の重複だった。
"""
import os
from pathlib import Path


def atomic_write(path: Path, data: bytes) -> None:
    """同一ディレクトリの一時ファイルに書いてから rename する。

    os.replace は同一ファイルシステム上でアトミックで、Windowsでも既存ファイルを
    置き換えられる。一時ファイル名を隠しファイルにしているのは、スナップショットの
    メタデータを glob で探す処理に拾われないようにするため。
    """
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
