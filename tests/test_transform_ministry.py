from pathlib import Path

import pytest

from jgkg.transform.ministry import UnmatchedMinistry, build, load_reference
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
    assert any(name == "厚生労働省" for _, name in ref), "参照表に厚生労働省が無い"
    # code は任意(裁定B12)なので None もあり得る。コメント行を data として
    # 取り込んでいないことの確認なので、値がある場合だけ形を検査すればよい
    assert all(code is None or not code.startswith("#") for code, _ in ref)


def test_load_reference_keeps_a_row_whose_ministry_code_is_blank(tmp_path):
    """name必須・ministry_code任意(裁定B12)。コード列が空でも行を捨てない。

    以前は `if code and name` で、名称だけの行がコードの有無で消えていた。
    それは「主キーは名称」という設計と矛盾する欠陥だった
    """
    path = tmp_path / "ministry-codes.csv"
    path.write_text("ministry_code,name\n,人事院\n020,厚生労働省\n", encoding="utf-8")

    ref = load_reference(path)

    assert (None, "人事院") in ref, f"コード無しの行が消えている: {ref}"
    assert ("020", "厚生労働省") in ref


def test_build_matches_by_name():
    orgs = [_org("6000012070001", "厚生労働省"), _org("2000012020001", "総務省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省"), ("013", "総務省")])

    by_code = {m.ministry_code: m for m in ministries}
    assert by_code["020"].houjin_bangou == "6000012070001"
    assert by_code["020"].uri == "https://jgkg.norr-tech.com/id/org/6000012070001"
    assert unmatched == []


def test_build_reports_unmatched_instead_of_dropping():
    """突合できなかった府省を沈黙させない(設計書§8.2)。"""
    orgs = [_org("6000012070001", "厚生労働省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省"), ("999", "存在しない省")])

    assert len(ministries) == 1
    assert len(unmatched) == 1
    assert unmatched[0].ministry_code == "999"
    assert unmatched[0].reason == "NO_CANDIDATE"


def test_build_ignores_non_government_organizations():
    orgs = [_org("9999999999999", "厚生労働省", kind="301")]  # 同名だが株式会社
    ministries, unmatched = build(orgs, [("020", "厚生労働省")])

    assert ministries == []
    assert len(unmatched) == 1


def test_build_reports_ambiguous_matches():
    orgs = [_org("6000012070001", "厚生労働省"), _org("8000012070002", "厚生労働省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省")])

    assert ministries == []
    assert unmatched[0].reason == "AMBIGUOUS"


def test_build_matches_by_name_when_reference_has_no_code():
    """名称だけの参照表行(ministry_code無し)でも名称一致で解決できること(裁定B12)。

    主キーは名称であり、コードは分かる場合にのみ持つ任意の値。コードが無い
    行を突合できないよう扱ってしまうと、B12が変えた設計と矛盾する
    """
    orgs = [_org("6000012070001", "厚生労働省")]
    ministries, unmatched = build(orgs, [(None, "厚生労働省")])

    assert unmatched == []
    assert len(ministries) == 1
    assert ministries[0].ministry_code is None
    assert ministries[0].houjin_bangou == "6000012070001"


def test_build_reports_unmatched_with_no_code_when_reference_has_none():
    orgs: list[Organization] = []
    ministries, unmatched = build(orgs, [(None, "存在しない省")])

    assert ministries == []
    assert unmatched == [
        UnmatchedMinistry(name="存在しない省", reason="NO_CANDIDATE", ministry_code=None)
    ]
