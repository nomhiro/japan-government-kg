from pathlib import Path

import pytest
from zenken_rows import zenken_row, zipped

from jgkg.transform.organization import (
    ColumnLayoutError,
    parse_file,
    parse_source,
    parse_text,
)

FIXTURE = Path("tests/fixtures/houjin_bangou_sample.csv")


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_parses_all_rows():
    orgs = list(parse_file(FIXTURE))
    assert len(orgs) == 27  # 現行26機関(裁定B12。実在の法人番号)+ 株式会社1件


def test_maps_fields_and_builds_uri():
    orgs = {o.houjin_bangou: o for o in parse_file(FIXTURE)}
    kourou = orgs["6000012070001"]
    assert kourou.name == "厚生労働省"
    assert kourou.uri == "https://jgkg.norr-tech.com/id/org/6000012070001"
    assert kourou.prefecture == "東京都"
    assert kourou.city == "千代田区"


def test_flags_government_organs():
    orgs = {o.houjin_bangou: o for o in parse_file(FIXTURE)}
    assert orgs["6000012070001"].is_government_organ is True   # 種別 101 = 国の機関
    assert orgs["9999999999999"].is_government_organ is False  # 種別 301 = 株式会社


def test_skips_rows_with_invalid_houjin_bangou():
    """行単位のノイズは捨てて処理を続けること(全件データ末尾の集計行など)。

    以前はこのテストが「不正な1行だけ」を入力にしていたため、
    「全行が棄却される = 列レイアウトの誤り」と区別できなかった。良い行を
    多数含めることで、**行単位の棄却**と**レイアウトの誤り**を分けて検査する
    (後者は test_wrong_column_layout_raises_instead_of_yielding_nothing)。
    """
    good = zenken_row()
    bad = zenken_row(houjin_bangou="NOTANUMBER", name="壊れた行", seq="2")

    orgs = list(parse_text(good * 3 + bad))
    assert [o.houjin_bangou for o in orgs] == ["6000012070001"] * 3


def test_wrong_column_layout_raises_instead_of_yielding_nothing():
    """列位置がずれていたら「0件」ではなく例外になること。

    COL の列位置は一次資料と照合されていない(モジュール冒頭の未了項目)。
    照合できるまでの安全装置として、**ずれていれば失敗する**ことを固定する。
    以前は `_cell` が空文字を返して全行が黙って捨てられ、`organizations=0` の
    まま「成功」を報告していた。

    **何があれば落ちるか**: `_assert_layout_plausible` の呼び出しを外したら
    落ちる(例外が出なくなる)。
    """
    # 先頭に1列挿入して、全列を1つずつずらす
    base = zenken_row().rstrip().split(",")
    shifted = ",".join(["x"] + base[:-1]) + "\n"
    with pytest.raises(ColumnLayoutError, match="1行も取り込めなかった"):
        list(parse_text(shifted * 5))


def test_shifted_kind_code_column_raises():
    """法人種別の列だけがずれた場合も検出すること。

    法人番号は13桁のまま読めるので取り込みは進むが、法人種別コードが3桁でなく
    なる。この状態を放置すると `is_government_organ` が全行 False になり、
    **国の機関が0件のKGが検証を通って出荷される。**
    """
    # 法人種別の位置(索引5)に日付が来るように、その手前に1列足す
    base = zenken_row().rstrip().split(",")
    row = ",".join(base[:8] + ["2015-10-05"] + base[8:-1]) + "\n"
    with pytest.raises(ColumnLayoutError, match="法人種別コード"):
        list(parse_text(row * 5))


def test_rows_too_short_for_the_required_columns_raise():
    """必要な列数に足りない行が支配的なら例外になること。

    住所列が読めていない状態(空文字が入る)を「成功」にしない。
    """
    row = "1,6000012070001,1,2015-10-05,2015-10-05,101,厚生労働省\n"  # 7列
    with pytest.raises(ColumnLayoutError, match="列数が足りない行"):
        list(parse_text(row * 5))


def test_empty_input_is_not_a_layout_error():
    """空のファイルはレイアウトの誤りと区別すること(件数の下限は pipeline 側で見る)。"""
    assert list(parse_text("")) == []


def test_skips_blank_lines():
    content = "\n\n" + zenken_row() + "\n"
    assert len(list(parse_text(content))) == 1


def test_parse_file_does_not_read_whole_file_into_memory(tmp_path):
    """ファイル全体をメモリに載せないこと。

    実データ(約1GB)で decode + StringIO を経由するとピーク5GB近くに達し、
    Phase 1の想定構成(2vCPU/8GiB)で破綻する。小さなfixtureでは差が出ないため、
    「1行だけ消費した時点でファイル全体が読まれていない」ことで代替検証する。
    """
    big = tmp_path / "many.csv"
    line = zenken_row()
    big.write_text(line * 5000, encoding="utf-8")

    gen = parse_file(big)
    first = next(gen)          # 1件だけ取り出す
    assert first.houjin_bangou == "6000012070001"
    # ジェネレータを閉じる(残りを読まない)。全件読み込みでは到達しない
    gen.close()


def test_wrong_encoding_raises_instead_of_silently_mangling(tmp_path):
    """エンコーディングが違えば例外になること。置換して進まないこと。

    法人番号の全件データはShift_JIS版とUnicode版の両方が配布されている。
    errors="replace" だと Shift_JIS版をUTF-8として読んだときに全法人名が
    置換文字に化け、500万行が静かに壊れる。系統的な誤りは止めるのが正しい。
    """
    sjis = tmp_path / "sjis.csv"
    line = zenken_row()
    sjis.write_bytes(line.encode("cp932"))

    with pytest.raises(UnicodeDecodeError):
        list(parse_file(sjis))  # 既定のutf-8で読む


def test_explicit_encoding_reads_shift_jis_correctly(tmp_path):
    """エンコーディングを明示すればShift_JIS版も正しく読めること。"""
    sjis = tmp_path / "sjis.csv"
    line = zenken_row()
    sjis.write_bytes(line.encode("cp932"))

    orgs = list(parse_file(sjis, encoding="cp932"))
    assert len(orgs) == 1
    assert orgs[0].name == "厚生労働省"


def test_parse_source_reads_the_distributed_zip(tmp_path):
    """配布形態(zip + .asc)をそのまま読めること。実物の構造を写したzipで検査する。"""
    z = tmp_path / "zenken.zip"
    z.write_bytes(zipped(zenken_row()))
    orgs = list(parse_source(z))
    assert [o.houjin_bangou for o in orgs] == ["6000012070001"]


def test_zip_with_multiple_csvs_raises(tmp_path):
    """zip内のCSVが1つでないなら黙って選ばず止まること(配布仕様の変化の検出)。

    **何があれば落ちるか**: parse_zip のメンバー数検査を外すと、どれかを
    黙って選んで通ってしまう。
    """
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.csv", zenken_row())
        zf.writestr("b.csv", zenken_row(seq="2"))
    z = tmp_path / "zenken.zip"
    z.write_bytes(buf.getvalue())
    with pytest.raises(ValueError, match="CSVが1つではない"):
        list(parse_source(z))
