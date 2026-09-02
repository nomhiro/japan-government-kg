"""GitHub Actionsのワークフロー定義が壊れていないことを検査する(裁定B83)。

**このテストはローカルでしか役に立たない。** ワークフローのYAMLがパース
できないとき、GitHubはジョブを1つも起動せずにrunをfailureにする——つまり
`ci.yml` が壊れていれば、この検査自体もCIでは走らない。

だから存在意義はpush前にある: 2026-09-02、引用符なしのステップ名に
`: `(コロン+空白)が入った1行で `ci.yml` がパース不能になり、
ローカルのゲート(pytest・ruff・base_uri・build・サイト検査)はすべて緑の
まま通り、CIは**何も測らずに**失敗した。ローカルにワークフローYAMLを
読む検査が1つも無かったのが原因(再発欠陥7: 単体では真、合成で偽)。
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# ステップに書ける鍵。ここに無い鍵が現れたら、引用符の抜けで
# `name: A(1): B` が入れ子のマッピングに化けた可能性を疑う
# (ハードなパースエラーにならず、構造だけ静かに壊れる場合がある)。
ALLOWED_STEP_KEYS = frozenset(
    {
        "name",
        "id",
        "if",
        "uses",
        "with",
        "run",
        "env",
        "shell",
        "working-directory",
        "continue-on-error",
        "timeout-minutes",
    }
)


def _workflow_files() -> list[Path]:
    files = sorted(p for p in WORKFLOW_DIR.iterdir() if p.suffix in {".yml", ".yaml"})
    assert files, f"ワークフローが1つも無い: {WORKFLOW_DIR}"
    return files


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_parses_as_yaml(path: Path) -> None:
    """YAMLとしてパースできること。

    パースできないとCIはジョブを1つも起動せず、**何も測らずに**失敗する。
    """
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - 壊れたときだけ通る
        pytest.fail(f"{path.name} がYAMLとしてパースできない:\n{exc}")

    assert isinstance(doc, dict), f"{path.name} の最上位がマッピングでない"
    jobs = doc.get("jobs")
    assert isinstance(jobs, dict) and jobs, f"{path.name} に jobs が無い"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_steps_have_only_known_keys(path: Path) -> None:
    """各ステップの鍵が既知の集合に収まること。

    引用符の抜けは、ハードなパースエラーにならずに
    `name:` の値が入れ子のマッピングに化ける形で構造を静かに壊すことがある。
    そのとき未知の鍵が現れる。
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    checked = 0
    for job_name, job in doc["jobs"].items():
        for i, step in enumerate(job.get("steps") or []):
            assert isinstance(step, dict), f"{path.name} {job_name}[{i}] がマッピングでない"
            unknown = set(step) - ALLOWED_STEP_KEYS
            assert not unknown, (
                f"{path.name} の {job_name}[{i}] に未知の鍵 {sorted(unknown)}"
                f" —— 引用符の抜けを疑うこと(name: の値に ': ' が入っていないか)"
            )
            assert "uses" in step or "run" in step, (
                f"{path.name} の {job_name}[{i}] に uses も run も無い"
            )
            checked += 1
    # 空虚にしない: 実際にステップを見たことを保証する
    assert checked >= 3, f"{path.name} で検査したステップが {checked} 件しかない"
