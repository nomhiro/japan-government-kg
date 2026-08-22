"""テスト用: 法人番号 全件CSVの行を実レイアウト(30列)で組み立てる。

**テストが行を手書きすると、列位置の変更のたびに全テストが壊れる。**
実際に2026-08-23の照合(COLの誤り発見)で、旧15列を手書きした8テストが
一斉に壊れた。組み立てをここに集約し、レイアウトの知識を
`transform/organization.py` の照合記録と対にして1箇所ずつにする。

列対応は organization.py 冒頭の照合記録を正とする。
"""
import io
import zipfile

from jgkg.transform.organization import EXPECTED_COLUMNS


def zipped(csv_text: str, member: str = "00_zenkoku_all_20260731.csv") -> bytes:
    """CSVテキストを配布形態(zip + .asc署名)に包む。実物の構造を写す。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, csv_text)
        z.writestr(member + ".asc", "-----BEGIN PGP SIGNATURE-----(test)")
    return buf.getvalue()


def zenken_row(
    houjin_bangou: str = "8000012070001",
    name: str = "厚生労働省",
    kind: str = "101",
    prefecture: str = "東京都",
    city: str = "千代田区",
    street: str = "霞が関1-2-2",
    seq: str = "1",
) -> str:
    r = [""] * EXPECTED_COLUMNS
    r[0] = seq
    r[1] = houjin_bangou
    r[2] = "01"
    r[3] = "1"
    r[4] = "2018-04-02"  # 更新年月日
    r[5] = "2015-10-05"  # 変更年月日
    r[6] = name
    r[8] = kind
    r[9] = prefecture
    r[10] = city
    r[11] = street
    r[13] = "13"
    r[15] = "1008916"
    r[22] = "2015-10-05"
    r[23] = "1"
    r[29] = "0"
    return ",".join(r) + "\n"
