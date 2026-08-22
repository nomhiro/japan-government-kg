"""静的配信物の整合テスト。

**このテストが守るのは「生成物が解決を要求しているURLが、配信物に必ず存在する」こと。**
要求されるパスは生成物から導出する(ハードコードしない)。モジュールを増やしたときに
検査対象から黙って抜け落ちる、という型がこのプロジェクトで3回起きているため。
"""
from pathlib import Path

import pytest

from jgkg import site
from jgkg.config import get_settings

GENERATED = Path(__file__).resolve().parent.parent / "schema" / "generated"


@pytest.fixture(autouse=True)
def _fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_required_paths_is_not_empty():
    """空集合に対する検査は常に通る(空振り)。まず対象があることを主張する。"""
    required = site.required_paths(GENERATED)
    assert len(required) >= 5, f"導出できたパスが少なすぎる: {sorted(required)}"
    # モジュール名だけのIRIと、ファイル名付きのIRIの両方が現れるはず
    assert any(p.endswith(".owl.ttl") for p in required), sorted(required)
    assert any(not p.endswith(".ttl") for p in required), sorted(required)


def test_build_covers_every_required_path(tmp_path):
    made = site.build(GENERATED, tmp_path)
    assert made, "配信物が1件も作られていない"
    missing = site.missing_paths(GENERATED, tmp_path)
    assert missing == set(), f"生成物が要求しているのに配信物に無い: {sorted(missing)}"


def test_missing_path_is_detected(tmp_path):
    """**この検査は何があれば落ちるか。** 1つ消したら検出できることを確かめる。"""
    site.build(GENERATED, tmp_path)
    required = sorted(site.required_paths(GENERATED))
    victim = tmp_path / required[0].lstrip("/")
    victim.unlink()
    missing = site.missing_paths(GENERATED, tmp_path)
    assert required[0] in missing, "ファイルを消しても検出されない(検査が空振りしている)"


def test_served_files_use_the_configured_base_uri(tmp_path):
    """配信物の中身が別のドメインを名乗っていたら公開してはならない。"""
    site.build(GENERATED, tmp_path)
    base = get_settings().base_uri.rstrip("/")
    core = (tmp_path / "def" / "core.owl.ttl").read_text(encoding="utf-8")
    assert base in core, f"配信物に {base} が現れない"
    assert "localhost" not in core, "開発用のドメインが配信物に残っている"
