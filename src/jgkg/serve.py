"""成果物を実行側に配置する経路。**配置の前に manifest と照合する。**

`verify_manifest` には実行時の呼び出し元が存在せず、呼ぶのは `tests/test_build.py`
だけだった(レビューI3)。設計書§6.3は「Jenaのバージョンをmanifestに記録し、
**実行側で照合する**」と書いているが、照合する場所が運用のどの手順にも無かった。
**照合されない記録は記録の演技である。** ここがその照合場所になる。

照合する2つ:

1. `sha256` — 成果物が転送・保管中に壊れていないか(Neptuneのsegment自動修復に
   相当する能力をチェックサムで安価に得る、という§6.3の規約)
2. `jena_version` — 実行側のJenaが成果物を作ったものと同じか。TDB2のオンディスク
   形式はJenaのバージョンに紐づく。**渡す値は fuseki イメージのタグを決めている
   `JENA_VERSION` そのもの**なので、上げて古い成果物を配ろうとすると止まる

使い方:

    uv run python -m jgkg.serve data/artifact/2026-08-01 --jena-version 6.2.0

**やっていないこと(設計書§6.3の未達分。レビューI7)**: 差し替えはアトミックでは
ない(symlink切り替え/blue-greenは未実装)。稼働中のFusekiが同じディレクトリを
mmapしている状態での差し替えは安全ではないので、**Fusekiを止めてから実行する。**
Dockerでの起動確認も未実施。
"""
import argparse
import shutil
import tarfile
from pathlib import Path

from jgkg import build

MANIFEST_NAME = "manifest.json"
TARBALL_NAME = "tdb2.tar.gz"
# tar の中身のトップディレクトリ(build.sh の `tar -C "$OUT" tdb2`)
DB_DIRNAME = "tdb2"
# docker-compose.yml が :ro でマウントする場所
DEFAULT_TARGET = Path("data/artifact") / DB_DIRNAME


def stage_release(
    artifact_dir: Path,
    target: Path = DEFAULT_TARGET,
    *,
    expected_jena_version: str | None = None,
) -> Path:
    """成果物を照合してから target に展開する。返り値は配置先。

    **照合は展開より先に行う。** 壊れた成果物やバージョンの合わない成果物で
    既存の配置を上書きしてはならない(例外を投げた時点で target は無変更)。
    """
    manifest_path = artifact_dir / MANIFEST_NAME
    tarball = artifact_dir / TARBALL_NAME
    for p in (manifest_path, tarball):
        if not p.exists():
            raise FileNotFoundError(f"成果物が見つからない: {p}")

    # ここが I3 の本体。壊れていたら例外が出て、以降の展開に進まない
    build.verify_manifest(
        manifest_path, tarball, expected_jena_version=expected_jena_version
    )

    incoming = target.with_name(f"{target.name}.incoming")
    if incoming.exists():
        shutil.rmtree(incoming)
    incoming.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as tf:
        # filter="data" は Python 3.12 の既定に合わせた明示。tar内の絶対パスや
        # `..` による外部への書き出しを拒否する
        tf.extractall(incoming, filter="data")

    extracted = incoming / DB_DIRNAME
    if not extracted.is_dir():
        shutil.rmtree(incoming)
        raise ValueError(
            f"成果物の中に {DB_DIRNAME}/ が無い: {tarball}。"
            " scripts/build.sh が作ったtarballか確認する"
        )

    # 前世代を残す(切り戻しの最低限。§6.3の「過去N世代を保持」は未実装)
    previous = target.with_name(f"{target.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if target.exists():
        target.replace(previous)
    extracted.replace(target)
    shutil.rmtree(incoming)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="成果物を照合して配置する")
    parser.add_argument("artifact_dir", type=Path, help="例: data/artifact/2026-08-01")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument(
        "--jena-version",
        default=None,
        help="実行側のJenaバージョン(fusekiイメージのタグ)。manifestと照合する",
    )
    args = parser.parse_args(argv)

    placed = stage_release(
        args.artifact_dir, args.target, expected_jena_version=args.jena_version
    )
    print(f"照合して配置した: {placed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
