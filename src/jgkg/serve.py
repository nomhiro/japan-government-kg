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

`--jena-version` を省略した場合は環境変数 `JENA_VERSION` を使う。どちらも無ければ
**失敗する**(黙って照合を飛ばさない)。意図的に飛ばすには `--skip-jena-check` を
明示する。

**やっていないこと(設計書§6.3の未達分。レビューI7)**: 差し替えはアトミックでは
ない(symlink切り替え/blue-greenは未実装)。稼働中のFusekiが同じディレクトリを
mmapしている状態での差し替えは安全ではないので、**Fusekiを止めてから実行する。**
Dockerでの起動確認も未実施。
"""
import argparse
import os
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
    expected_jena_version: str | None,
) -> Path:
    """成果物を照合してから target に展開する。返り値は配置先。

    **照合は展開より先に行う。** 壊れた成果物やバージョンの合わない成果物で
    既存の配置を上書きしてはならない(例外を投げた時点で target は無変更)。

    `expected_jena_version` は**既定値を持たない。** `None` を渡せばJenaバージョンの
    照合を飛ばせるが、それは呼び出し側が明示的に選ぶ行為でなければならない。
    既定で飛ばせるようにすると、Ruling 35 が問題にした「記録の演技」に戻る
    (照合する経路を作っても、その照合が省略可能なら意味がない)。
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
        help="実行側のJenaバージョン(fusekiイメージのタグ)。manifestと照合する。"
        " 省略時は環境変数 JENA_VERSION を使う",
    )
    parser.add_argument(
        "--skip-jena-check",
        action="store_true",
        help="Jenaバージョンの照合を飛ばす。**TDB2のオンディスク形式はJenaの"
        "バージョンに紐づくため、通常は使わない。**",
    )
    args = parser.parse_args(argv)

    # **既定は照合する側。** 以前は `--jena-version` 省略時に何も言わず照合を飛ばして
    # いたが、それは I3 で作った照合経路を既定で無効にするのと同じである
    # (C2 で採った「既定は止まる側、緩めるには明示フラグ」と揃える)
    jena_version = args.jena_version or os.environ.get("JENA_VERSION")
    if args.skip_jena_check:
        if args.jena_version:
            parser.error("--jena-version と --skip-jena-check は同時に指定できない")
        jena_version = None
        print(
            "警告: Jenaバージョンの照合を飛ばす。TDB2のオンディスク形式は"
            "Jenaのバージョンに紐づくため、版がずれるとFusekiがデータを読めない"
        )
    elif not jena_version:
        parser.error(
            "Jenaバージョンが分からない。--jena-version を渡すか、環境変数"
            " JENA_VERSION を設定する(fusekiイメージのタグと同じ値)。"
            " 照合しないなら --skip-jena-check を明示する"
        )

    placed = stage_release(
        args.artifact_dir, args.target, expected_jena_version=jena_version
    )
    print(f"照合して配置した: {placed}(Jena照合: {jena_version or 'スキップ'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
