"""Task 11 Step 4「TDB2実サイズと1トリプルあたりバイト数」の実測。

設計書§6.3 は成果物(TDB2インデックス)を Azure Container Apps の一時
ディスク上に置くことを前提にしており、**その上限が 8GiB** である。全法人
(約3,500万トリプル)を含むリリースがそこに収まるかどうかは、この計画の
ホスティング選択そのものに関わる数字なので、推定ではなく実測する。

出す数字(ブリーフの要求項目):
  - kg.nq の行数(=N-Quadsのステートメント数)とバイト数
  - TDB2 ディレクトリの実サイズ(ファイル単位の内訳つき)
  - **1トリプルあたりバイト数**: (TDB2実サイズ − 固定オーバーヘッド) ÷ トリプル数
    固定オーバーヘッドは「同じJenaバージョンで作った、ほぼ空のTDB2」の実サイズを
    別のリリースから取って引く(--baseline-tdb2 で渡す。既定は
    data/artifact/2026-08-23/tdb2 = houjin-bangou のみ・5,143トリプル)。
    **「約192MiB」という既存の見積りをそのまま引き算に使わない** — 実測した
    値で引く(裁定B25の趣旨: 再導出できない数値を作らない)
  - 8GiB(ACAの一時ディスク上限)に収まるかの判定
  - tdb2.tar.gz(配布形態)のサイズ

**使い捨てにしない**(裁定B25)。出力は docs/measurements-phase1.md に全量転記する。

使い方:
    uv run python scripts/measure_release_size.py data/artifact/2026-08-24
    uv run python scripts/measure_release_size.py data/artifact/2026-08-24 \
        --baseline-tdb2 data/artifact/2026-08-23/tdb2
"""
import argparse
import json
from pathlib import Path

from jgkg import build

MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024
# Azure Container Apps の一時ディスク上限(設計書§6.3)
ACA_EPHEMERAL_LIMIT = 8 * GIB


def _dir_size(path: Path) -> tuple[int, list[tuple[str, int]]]:
    """ディレクトリの実バイト数と、ファイルごとの内訳(降順)。"""
    entries: list[tuple[str, int]] = []
    total = 0
    for p in sorted(path.rglob("*")):
        if p.is_file():
            size = p.stat().st_size
            total += size
            entries.append((str(p.relative_to(path)), size))
    entries.sort(key=lambda kv: -kv[1])
    return total, entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path, help="例: data/artifact/2026-08-24")
    parser.add_argument(
        "--baseline-tdb2",
        type=Path,
        default=Path("data/artifact/2026-08-23/tdb2"),
        help="固定オーバーヘッドを測るための、ほぼ空のTDB2ディレクトリ",
    )
    args = parser.parse_args()

    art = args.artifact_dir
    kg_nq = art / "kg.nq"
    tdb2 = art / "tdb2"
    tarball = art / "tdb2.tar.gz"
    for p in (kg_nq, tdb2):
        if not p.exists():
            raise FileNotFoundError(f"成果物が無い: {p}。先に scripts/build.sh を実行する")

    print("=" * 78)
    print(f"成果物サイズの実測: {art}")
    print("=" * 78)

    manifest_path = art / build.MANIFEST_NAME
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"release          : {m['release']}")
        print(f"jena_version     : {m['jena_version']}")
        print(f"manifest triple_count: {m['triple_count']}")
        print(f"sources          : {m['sources']}")

    nq_bytes = kg_nq.stat().st_size
    # manifest の triple_count と同じ関数で数える(別の数え方を持ち込まない)
    nq_lines = build._count_triples(kg_nq)
    print()
    print(f"kg.nq            : {nq_lines:,} 行 / {nq_bytes:,} バイト "
          f"({nq_bytes / MIB:.1f} MiB)")
    print(f"kg.nq 1行あたり  : {nq_bytes / nq_lines:.1f} バイト" if nq_lines else "")

    tdb2_bytes, entries = _dir_size(tdb2)
    print()
    print(f"TDB2 実サイズ    : {tdb2_bytes:,} バイト "
          f"({tdb2_bytes / MIB:.1f} MiB / {tdb2_bytes / GIB:.3f} GiB)")
    print("TDB2 ファイル内訳(降順・全件):")
    for name, size in entries:
        print(f"  {size:>14,}  {size / MIB:>9.2f} MiB  {name}")

    if tarball.exists():
        tar_bytes = tarball.stat().st_size
        print()
        print(f"tdb2.tar.gz      : {tar_bytes:,} バイト ({tar_bytes / MIB:.1f} MiB)"
              f" / 圧縮率 {tar_bytes / tdb2_bytes:.3f}")

    print()
    print("--- 1トリプルあたりバイト数 ---")
    if args.baseline_tdb2.exists():
        base_bytes, _ = _dir_size(args.baseline_tdb2)
        base_kg = args.baseline_tdb2.parent / "kg.nq"
        base_lines = build._count_triples(base_kg) if base_kg.exists() else 0
        print(f"固定オーバーヘッドの実測元: {args.baseline_tdb2}"
              f"({base_lines:,} 行)")
        print(f"  その実サイズ           : {base_bytes:,} バイト "
              f"({base_bytes / MIB:.1f} MiB)")
        delta_bytes = tdb2_bytes - base_bytes
        delta_lines = nq_lines - base_lines
        print(f"  差分(このリリース − 基準): {delta_bytes:,} バイト / "
              f"{delta_lines:,} 行")
        if delta_lines > 0:
            print(f"  **1トリプルあたり {delta_bytes / delta_lines:.2f} バイト**")
        # 引き算をしない素の値も出す(どちらの数字を引用しているかを
        # 読み手が取り違えないように、両方を並べて書く)
        print(f"  (参考)引き算なしの単純平均: {tdb2_bytes / nq_lines:.2f} バイト/行")
    else:
        print(f"基準のTDB2が無い({args.baseline_tdb2})ので引き算はしない。")
        print(f"  引き算なしの単純平均: {tdb2_bytes / nq_lines:.2f} バイト/行")

    print()
    print("--- 8GiB(Azure Container Apps 一時ディスク上限。§6.3)判定 ---")
    print(f"TDB2 実サイズ / 8GiB = {tdb2_bytes / ACA_EPHEMERAL_LIMIT:.1%}")
    verdict = "収まる" if tdb2_bytes <= ACA_EPHEMERAL_LIMIT else "**収まらない**"
    print(f"判定: {verdict}(余裕 {(ACA_EPHEMERAL_LIMIT - tdb2_bytes) / GIB:+.3f} GiB)")
    # **展開に必要な一時容量も見る。** ACAの一時ディスクには tar.gz と展開後の
    # TDB2 が同時に載る瞬間がある(serve.py は tar.gz を展開してから
    # ディレクトリを差し替える)ので、上限判定は「両方の合計」で見ないと甘くなる
    if tarball.exists():
        peak = tdb2_bytes + tarball.stat().st_size
        print(f"展開中のピーク(tar.gz + 展開後TDB2) = {peak:,} バイト "
              f"({peak / GIB:.3f} GiB) → 8GiB の {peak / ACA_EPHEMERAL_LIMIT:.1%}")
        print("判定(ピーク基準): "
              + ("収まる" if peak <= ACA_EPHEMERAL_LIMIT else "**収まらない**"))


if __name__ == "__main__":
    main()
