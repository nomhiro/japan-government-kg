"""`scripts/check-site-build.py` 自身の回帰テスト(A-2残件2)。

このファイル名はハイフンを含むため`import`できず、`scripts/*.py`は
`verify-site.py`と同じくCLIとして起動するだけでテストからimportしない
設計(`tests/test_fetch.py`のように`src/jgkg/`配下をimportするのとは違う)。
そのため`subprocess`で実際にプロセスを起動して終了コードを見る
(このリポジトリで初めてsubprocessを使うテスト)。

**`tests/conftest.py`のネットワーク遮断は子プロセスには適用されない**
(`socket`をこのプロセス内でmonkeypatchするだけのため)。実害は無い——
`check-site-build.py`自体はファイル読み取りのみで、ネットワークに一切
触らない(モジュールdocstring参照)。

このプロジェクトは同型の欠陥を1度阻害扱いにしている(`compare_releases.py`
のテストが変異試験で「内容の異なる2リリースを一致と判定しても通る」と
判明した件。最終レビュー要修正7)。`check-site-build.py`自体にテストが
無ければ同じことが起こり得る、というのがこのテストを書く理由。
"""
import subprocess
import sys
from pathlib import Path

from jgkg import site

GENERATED = Path(__file__).resolve().parent.parent / "schema" / "generated"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-site-build.py"


def _run(out_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--generated-dir", str(GENERATED),
            "--out-dir", str(out_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_check_site_build_exits_nonzero_exactly_when_the_build_is_broken(tmp_path):
    """空虚にしない: 壊す前が0終了であることも、この中で確認する。

    何があれば落ちるか: `check-site-build.py`のどの検査(missing_paths /
    `_headers`一致 / sitemap一致)が壊れても、終了コードの配線
    (failuresがあれば1を返す)が壊れても、以下の2回の実行のどちらかが
    期待と異なる終了コードになる。controllerが手で行った壊し確認
    (`site/def/law.owl.ttl`を消す)と同じ形をpytestに固定する。
    """
    made = site.build(GENERATED, tmp_path)
    site.write_headers(made, tmp_path)

    healthy = _run(tmp_path)
    assert healthy.returncode == 0, (
        f"壊す前から失敗している(空虚な検査の疑い)。stdout:\n{healthy.stdout}"
    )
    assert "すべて合格" in healthy.stdout

    victim = min(site.built_def_paths(tmp_path))
    (tmp_path / victim.lstrip("/")).unlink()

    broken = _run(tmp_path)
    assert broken.returncode == 1, f"壊した後も成功終了している。stdout:\n{broken.stdout}"
    assert "失敗" in broken.stdout
