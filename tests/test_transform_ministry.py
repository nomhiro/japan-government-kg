from pathlib import Path

import pytest

from jgkg.transform.ministry import build, load_reference
from jgkg.transform.organization import Organization


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _org(bangou: str, name: str, kind: str = "101") -> Organization:
    return Organization(
        uri=f"https://jgkg.norr-tech.com/id/org/{bangou}",
        houjin_bangou=bangou,
        name=name,
        kind_code=kind,
        is_government_organ=(kind == "101"),
    )


def test_load_reference_skips_comments():
    ref = load_reference(Path("data/reference/ministry-codes.csv"))
    assert ("020", "厚生労働省") in ref
    assert all(not code.startswith("#") for code, _ in ref)


def test_build_matches_by_name():
    orgs = [_org("8000012070001", "厚生労働省"), _org("8000012020001", "総務省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省"), ("013", "総務省")])

    by_code = {m.ministry_code: m for m in ministries}
    assert by_code["020"].houjin_bangou == "8000012070001"
    assert by_code["020"].uri == "https://jgkg.norr-tech.com/id/org/8000012070001"
    assert unmatched == []


def test_build_reports_unmatched_instead_of_dropping():
    """突合できなかった府省を沈黙させない(設計書§8.2)。"""
    orgs = [_org("8000012070001", "厚生労働省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省"), ("999", "存在しない省")])

    assert len(ministries) == 1
    assert len(unmatched) == 1
    assert unmatched[0].ministry_code == "999"
    assert unmatched[0].reason == "NO_CANDIDATE"


def test_build_ignores_non_government_organizations():
    orgs = [_org("3010001008683", "厚生労働省", kind="301")]  # 同名だが株式会社
    ministries, unmatched = build(orgs, [("020", "厚生労働省")])

    assert ministries == []
    assert len(unmatched) == 1


def test_build_reports_ambiguous_matches():
    orgs = [_org("8000012070001", "厚生労働省"), _org("8000012070002", "厚生労働省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省")])

    assert ministries == []
    assert unmatched[0].reason == "AMBIGUOUS"
