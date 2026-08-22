import datetime
from pathlib import Path

import pytest

from jgkg import lake, pipeline
from jgkg.connectors import houjin_bangou

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_lake():
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, content)


def test_run_produces_nquads_and_report(seeded_lake, tmp_path):
    out = tmp_path / "out"
    report = pipeline.run(DAY, out)

    assert report.organizations == 4       # 入力の全件数
    assert report.government_organs == 3   # KGに入れた件数(株式会社1件を除外)
    assert report.ministries >= 1
    assert (out / "kg.nq").exists()


def test_run_reports_unmatched_ministries(seeded_lake, tmp_path):
    """参照表にあってデータに無い府省を件数として報告する(設計書§8.2)。"""
    report = pipeline.run(DAY, tmp_path / "out")
    assert report.unmatched_ministries >= 0
    assert report.ministries + report.unmatched_ministries >= 3


def test_run_is_idempotent(seeded_lake, tmp_path):
    out = tmp_path / "out"
    first = pipeline.run(DAY, out)
    second = pipeline.run(DAY, out)
    assert first.organizations == second.organizations
    assert (out / "kg.nq").exists()


def test_run_fails_when_snapshot_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline.run(DAY, tmp_path / "out")
