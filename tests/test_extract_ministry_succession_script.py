"""`scripts/extract_ministry_succession.py` 自身の回帰テスト。

`scripts/*.py` はCLIとして起動するだけでテストからimportしない設計
(`tests/test_check_site_build.py` と同じ理由・同じ手法)。`ministry_succession`
モジュール自体のロジックは `tests/test_transform_ministry_succession.py` が
網羅するので、ここでは「スクリプトがレイクを読んでCSVを書き出し、
18名称の網羅を正しく報告する」という配線そのものだけを確認する。

このスクリプトはネットワークに触れない(既にコミット済みのレイク
スナップショットとold-ministries.csvしか読まない)ため、
`tests/conftest.py`のネットワーク遮断(親プロセス内のみ)は無関係。
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "extract_ministry_succession.py"
REAL_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "egov_law_data_412CO0000000315.json"
LAW_ID = "412CO0000000315"


def _run(tmp_path: Path, cwd: Path) -> subprocess.CompletedProcess:
    lake_dir = tmp_path / "lake"
    snap_dir = lake_dir / "egov-law" / "2026-08-26"
    snap_dir.mkdir(parents=True)
    content = REAL_FIXTURE.read_bytes()
    (snap_dir / f"law_data_{LAW_ID}.json").write_bytes(content)
    (snap_dir / f"law_data_{LAW_ID}.json.meta.json").write_text(
        json.dumps(
            {
                "source_id": "egov-law",
                "fetched_on": "2026-08-26",
                "path": str(snap_dir / f"law_data_{LAW_ID}.json"),
                "sha256": "irrelevant-for-this-test",
                "byte_size": len(content),
            }
        ),
        encoding="utf-8",
    )
    env = {**__import__("os").environ, "JGKG_LAKE_DIR": str(lake_dir)}
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8",
        check=False, cwd=cwd, env=env,
    )


def test_script_runs_end_to_end_against_the_real_fixture_and_reports_18_of_18(tmp_path):
    out_dir = tmp_path / "workdir"
    (out_dir / "data" / "reference").mkdir(parents=True)
    # old-ministries.csvはリポジトリ実物をそのまま使う(このスクリプトの
    # load_old_ministriesはcwd非依存の_REPO_ROOT基点で読むため、
    # ここでは作業ディレクトリではなく実物のパスがそのまま使われる)
    out_csv = out_dir / "data" / "reference" / "ministry-succession.csv"

    result = _run(tmp_path, cwd=out_dir)

    assert result.returncode == 0, result.stderr
    assert "18/18" in result.stdout
    assert "未解決" not in result.stdout.replace("未解決なし", "")
    assert out_csv.exists()
    written = out_csv.read_text(encoding="utf-8")
    data_lines = [line for line in written.splitlines() if line and not line.startswith("#")]
    # ヘッダ1行 + データ58行
    assert len(data_lines) == 59
    assert data_lines[0] == "old_text,new_text,old_name,new_name,source_law_id,row_index"


def test_script_gives_an_actionable_error_when_no_snapshot_exists(tmp_path):
    lake_dir = tmp_path / "lake"
    lake_dir.mkdir()
    env = {**__import__("os").environ, "JGKG_LAKE_DIR": str(lake_dir)}
    out_dir = tmp_path / "workdir"
    (out_dir / "data" / "reference").mkdir(parents=True)

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8",
        check=False, cwd=out_dir, env=env,
    )

    assert result.returncode != 0
    assert "jgkg.fetch --law-id" in result.stderr
