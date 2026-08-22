from pathlib import Path

import pytest

from jgkg.transform.organization import parse_file, parse_text

FIXTURE = Path("tests/fixtures/houjin_bangou_sample.csv")


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_parses_all_rows():
    orgs = list(parse_file(FIXTURE))
    assert len(orgs) == 4


def test_maps_fields_and_builds_uri():
    orgs = {o.houjin_bangou: o for o in parse_file(FIXTURE)}
    kourou = orgs["8000012070001"]
    assert kourou.name == "厚生労働省"
    assert kourou.uri == "http://localhost:8080/kg/id/org/8000012070001"
    assert kourou.prefecture == "東京都"
    assert kourou.city == "千代田区"


def test_flags_government_organs():
    orgs = {o.houjin_bangou: o for o in parse_file(FIXTURE)}
    assert orgs["8000012070001"].is_government_organ is True   # 種別 101 = 国の機関
    assert orgs["3010001008683"].is_government_organ is False  # 種別 301 = 株式会社


def test_skips_rows_with_invalid_houjin_bangou():
    bad = "1,NOTANUMBER,1,2015-10-05,2015-10-05,101,壊れた行,,,,100,0001,東京都,千代田区,x\n"
    assert list(parse_text(bad)) == []


def test_skips_blank_lines():
    content = "\n\n1,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省,,,,1,1,東京都,千代田区,x\n\n"
    assert len(list(parse_text(content))) == 1


def test_parse_file_does_not_read_whole_file_into_memory(tmp_path):
    """ファイル全体をメモリに載せないこと。

    実データ(約1GB)で decode + StringIO を経由するとピーク5GB近くに達し、
    Phase 1の想定構成(2vCPU/8GiB)で破綻する。小さなfixtureでは差が出ないため、
    「1行だけ消費した時点でファイル全体が読まれていない」ことで代替検証する。
    """
    big = tmp_path / "many.csv"
    line = "1,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省,,,,1,1,東京都,千代田区,x\n"
    big.write_text(line * 5000, encoding="utf-8")

    gen = parse_file(big)
    first = next(gen)          # 1件だけ取り出す
    assert first.houjin_bangou == "8000012070001"
    # ジェネレータを閉じる(残りを読まない)。全件読み込みでは到達しない
    gen.close()


def test_wrong_encoding_raises_instead_of_silently_mangling(tmp_path):
    """エンコーディングが違えば例外になること。置換して進まないこと。

    法人番号の全件データはShift_JIS版とUnicode版の両方が配布されている。
    errors="replace" だと Shift_JIS版をUTF-8として読んだときに全法人名が
    置換文字に化け、500万行が静かに壊れる。系統的な誤りは止めるのが正しい。
    """
    sjis = tmp_path / "sjis.csv"
    line = "1,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省,,,,1,1,東京都,千代田区,x\n"
    sjis.write_bytes(line.encode("cp932"))

    with pytest.raises(UnicodeDecodeError):
        list(parse_file(sjis))  # 既定のutf-8で読む


def test_explicit_encoding_reads_shift_jis_correctly(tmp_path):
    """エンコーディングを明示すればShift_JIS版も正しく読めること。"""
    sjis = tmp_path / "sjis.csv"
    line = "1,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省,,,,1,1,東京都,千代田区,x\n"
    sjis.write_bytes(line.encode("cp932"))

    orgs = list(parse_file(sjis, encoding="cp932"))
    assert len(orgs) == 1
    assert orgs[0].name == "厚生労働省"
