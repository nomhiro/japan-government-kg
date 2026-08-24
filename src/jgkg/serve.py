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

**Task 10: アトミック切替。** `data/artifact/current/` をディレクトリごと
入れ替える(以前は `tdb2/` だけを入れ替えていたが、切替の単位を「現在
配信中の世代」全体に揃えた)。**稼働中のmmapディレクトリを上書きしない**
(TDB2はメモリマップドファイルを使うため)— `scripts/serve.sh` がこの関数を
呼ぶ**前に**Fusekiを止める(先に停止→退避→配置→起動の順を維持する。この
関数自身はファイルシステム側の退避・配置だけを担う)。前世代は必ず
`data/artifact/previous/` に残す(§6.3の「過去N世代を保持」の最低限。
N=1)。

**中断時の復旧(task-10-review.md観察7)**: `current_dir.replace(previous_dir)`と
`incoming_dir.replace(current_dir)`の間でプロセスが落ちると、`current/`が
一時的に存在しない状態になる。`docker-compose.yml`は`./data/artifact/current/tdb2`
をbind mountするため、Dockerがホスト側の空ディレクトリを自動作成し、Fusekiが
空のKGを配信しうる。窓は極小(rename2回の間のみ)だが、復旧手順は前世代を
戻すだけでよい: `data/artifact/previous`を`data/artifact/current`へ戻し
(`mv`または`Path.replace`)、`docker compose up -d fuseki`で再起動する。
"""
import argparse
import os
import shutil
import tarfile
from pathlib import Path

from jgkg import build

# serve.MANIFEST_NAME として再公開する(既存呼び出し元・テスト向け。build.py側が
# 単一の出典になったため、ここでは再importするだけにする)
from jgkg.build import MANIFEST_NAME

TARBALL_NAME = "tdb2.tar.gz"
# tar の中身のトップディレクトリ(build.sh の `tar -C "$OUT" tdb2`)
DB_DIRNAME = "tdb2"
# アトミック切替の単位そのもの(target.parent がこの名前であることを
# stage_release が検査する。要修正3参照)
CURRENT_DIRNAME = "current"
# docker-compose.yml が読み取り専用でマウントする場所(Task 10:
# `data/artifact/current/` がアトミック切替の単位そのもの)
DEFAULT_TARGET = Path("data/artifact") / CURRENT_DIRNAME / DB_DIRNAME


def stage_release(
    artifact_dir: Path,
    target: Path = DEFAULT_TARGET,
    *,
    expected_jena_version: str | None,
) -> Path:
    """成果物を照合してから target に展開する。返り値は配置先(`target`そのもの)。

    **照合は展開より先に行う。** 壊れた成果物やバージョンの合わない成果物で
    既存の配置を上書きしてはならない(例外を投げた時点で target は無変更)。

    `expected_jena_version` は**既定値を持たない。** `None` を渡せばJenaバージョンの
    照合を飛ばせるが、それは呼び出し側が明示的に選ぶ行為でなければならない。
    既定で飛ばせるようにすると、Ruling 35 が問題にした「記録の演技」に戻る
    (照合する経路を作っても、その照合が省略可能なら意味がない)。

    **Task 10: 切替の単位は`target.parent`(「現在配信中の世代」ディレクトリ
    全体。既定では`data/artifact/current/`)。** `tdb2/`だけを入れ替える
    従来の実装では、`current/`直下に将来manifest等の付随ファイルを置いても
    切替の対象外になってしまう(半端な入れ替え)。展開先(`incoming`)・
    退避先(`previous`)はいずれも`target.parent`の**兄弟ディレクトリ**
    (`target.parent.parent`直下)に置く — `target.parent`自身をリネームで
    退避するため、退避先が`target.parent`の**内側**にあってはならない。

    **修正ラウンド1(要修正3): `target`の形を検査する。** `target`は
    `--target`で外部から渡せるため、`target.parent`全体を無検証で改名する
    設計と組み合わさると破壊的になる——`python -m jgkg.serve <dir>
    --target data/artifact/tdb2`(旧レイアウトの形そのもの。
    `docs/superpowers/plans/2026-08-22-phase0-data-layer-foundation.md:3087`に
    文書として残っており、このリポジトリに実際に残存物`data/artifact/tdb2`が
    存在する)を渡すと`current_dir = data/artifact`になり、**全リリース・
    全manifest・全tarballを含むディレクトリ全体**が`data/previous`へ
    改名されてしまう(task-10-review.md要修正3)。`scripts/serve.sh`は
    `--target`を渡さないので既定経路は安全だが、「既定は止まる側」を
    貫くコードベースとして、破壊的な既定を外部入力に無検査で委ねてはならない。
    """
    if target.name != DB_DIRNAME or target.parent.name != CURRENT_DIRNAME:
        raise ValueError(
            f"target の形が想定と違う: {target}。"
            f" target.name は {DB_DIRNAME!r}、target.parent.name は"
            f" {CURRENT_DIRNAME!r} である必要がある(例: data/artifact/current/tdb2)。"
            " 切替の単位は target.parent 全体なので、この検査が無いと"
            " 想定外のディレクトリ全体を丸ごと改名してしまう"
        )

    manifest_path = artifact_dir / MANIFEST_NAME
    tarball = artifact_dir / TARBALL_NAME
    for p in (manifest_path, tarball):
        if not p.exists():
            raise FileNotFoundError(f"成果物が見つからない: {p}")

    # ここが I3 の本体。壊れていたら例外が出て、以降の展開に進まない
    build.verify_manifest(
        manifest_path, tarball, expected_jena_version=expected_jena_version
    )

    current_dir = target.parent
    incoming_dir = current_dir.with_name("incoming")
    previous_dir = current_dir.with_name("previous")

    if incoming_dir.exists():
        shutil.rmtree(incoming_dir)
    incoming_dir.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as tf:
        # filter="data" は Python 3.12 の既定に合わせた明示。tar内の絶対パスや
        # `..` による外部への書き出しを拒否する
        tf.extractall(incoming_dir, filter="data")

    extracted = incoming_dir / DB_DIRNAME
    if not extracted.is_dir():
        shutil.rmtree(incoming_dir)
        raise ValueError(
            f"成果物の中に {DB_DIRNAME}/ が無い: {tarball}。"
            " scripts/build.sh が作ったtarballか確認する"
        )

    # 前世代を残す(切り戻しの最低限。§6.3の「過去N世代を保持」は未実装。N=1)。
    # **退避(current→previous)→配置(incoming→current)の順を守る**
    # (このスクリプトが呼ばれる時点でFusekiは既に停止済みという前提 —
    # scripts/serve.sh参照。停止済みなら、稼働中のmmapディレクトリを
    # 上書きする心配はここには無い)
    if previous_dir.exists():
        shutil.rmtree(previous_dir)
    if current_dir.exists():
        current_dir.replace(previous_dir)
    incoming_dir.replace(current_dir)
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
