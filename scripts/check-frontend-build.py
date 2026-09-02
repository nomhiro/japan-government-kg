"""フロントエンド(`frontend/`)のビルドがバイト単位で再現可能であることを検査する(裁定B81)。

    uv run python scripts/check-frontend-build.py

**なぜ必要か。** `site-check.yml`は毎日mainからビルドし直して本番と比較する
(裁定B63)。ビルドがバイト単位で再現しないなら、その比較は毎日赤くなり、
裁定B63自身が警告した「たまに赤くなるので無視される検査」に退化する。
`schema_lang.py`が「入力が同じなら常にバイト単位で同一の出力」を要求
されているのと同じ規律を、フロントエンドのビルドにも適用する:
**2回続けてビルドして全ファイルのsha256が一致することを検査する。**

**ネットワークは使わない。** `npm ci`は別途(手元またはCIの専用ステップ)で
済ませておく前提——ここで呼ぶのは`npm run build`(既存の`node_modules`と
ソースだけで完結し、ネットワークに出ない)だけである。`tests/conftest.py`
のネットワーク遮断はPythonの`socket`層だけを塞ぐため`subprocess`には
適用されない(同モジュールのdocstring項3参照)——ここでの`npm run build`が
オフラインで完結することは、この検査自身が両方の実行で成功することで
確かめている。

**`uv run pytest`には含めない。** Node/npmへの依存を持つ検査をテスト
スイートの外に置く判断は、`scripts/check-site-build.py`/`verify-site.py`
と同じ——このリポジトリは「検査」を必ずしもpytestに入れず、CIの専用
ステップとして走らせる独立スクリプトにする前例が既にある。
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _npm_command() -> list[str]:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm が見つからない。Node.jsをインストールすること")
    return [npm, "run", "build"]


def _build() -> dict[str, str]:
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    subprocess.run(_npm_command(), cwd=FRONTEND_DIR, check=True)
    if not DIST_DIR.is_dir():
        raise SystemExit(f"ビルドが {DIST_DIR} を作らなかった")
    tree = _hash_tree(DIST_DIR)
    if not tree:
        # 裁定B75と同じ考え方: 「0件」を静かに合格させない。ビルドが空の
        # distを作った場合、以降の比較は「空同士で一致」という空虚な合格になる。
        raise SystemExit(f"{DIST_DIR} が空。ビルドが何も作っていない(空虚な検査を避けるため停止)")
    return tree


def main() -> int:
    if not (FRONTEND_DIR / "node_modules").is_dir():
        print(
            f"{FRONTEND_DIR / 'node_modules'} が無い。先に `npm ci`(frontend/内)を実行すること",
            file=sys.stderr,
        )
        return 1

    print("1回目のビルド...")
    first = _build()
    print(f"  {len(first)} ファイル")

    print("2回目のビルド...")
    second = _build()
    print(f"  {len(second)} ファイル")

    if first == second:
        print(f"OK 2回のビルドが完全に一致した({len(first)}ファイル)")
        return 0

    only_first = sorted(set(first) - set(second))
    only_second = sorted(set(second) - set(first))
    diff_hash = sorted(k for k in set(first) & set(second) if first[k] != second[k])
    print("NG 2回のビルドが一致しない", file=sys.stderr)
    if only_first:
        print(f"  1回目だけに存在: {only_first}", file=sys.stderr)
    if only_second:
        print(f"  2回目だけに存在: {only_second}", file=sys.stderr)
    if diff_hash:
        print(f"  内容が違う: {diff_hash}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
