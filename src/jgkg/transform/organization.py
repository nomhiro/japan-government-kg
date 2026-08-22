"""法人番号 全件CSV → Organization。

全件CSVはヘッダなしで列位置が仕様で決まっている。列位置はここに集約し、
仕様変更時の修正点を1箇所に限定する。
"""
import csv
import io
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel

from jgkg.uris import HOUJIN_BANGOU_RE, org_uri

# 全件CSVの列位置(0起点)。仕様変更時はここだけを直す。
COL = {
    "houjin_bangou": 1,
    "kind_code": 5,
    "name": 6,
    "prefecture": 12,
    "city": 13,
    "street": 14,
}

# 法人種別コード 101 = 国の機関
GOVERNMENT_ORGAN_KIND = "101"


class Organization(BaseModel):
    uri: str
    houjin_bangou: str
    name: str
    kind_code: str
    prefecture: str = ""
    city: str = ""
    street: str = ""
    is_government_organ: bool = False


def _cell(row: list[str], key: str) -> str:
    idx = COL[key]
    return row[idx].strip() if idx < len(row) else ""


def parse_file(path: Path, encoding: str = "utf-8") -> Iterator[Organization]:
    """CSVファイルを1行ずつ Organization にする。

    **ファイル全体をメモリに載せない。** 法人番号の全件データは約500万行(約1GB)で、
    bytes で読んで `decode()` すると、日本語を含む str はCPythonでUCS-2(2バイト/文字)
    になるため約2GB、さらに StringIO のコピーでピーク5GB近くに達する。Phase 1の
    想定構成(2vCPU/8GiB)で破綻し、設計書§11.1の「誰の環境でも同じKGが再構築できる」
    を満たせない。ファイルハンドルを csv.reader に直接渡して1行ずつ流す。

    不正な行は黙って捨てず、単に生成しない。法人番号が13桁でない行は取り込まない。
    ここで例外にしないのは、全件データの末尾に集計行などが混じっても処理を
    止めないため。

    エンコーディングの誤りは行単位のノイズではなく全行に及ぶ系統的な誤りなので、
    errors="strict" にして UnicodeDecodeError で止める。置換して進むと500万行の
    法人名すべてが静かに壊れる(設計書の「沈黙させない」原則に反する)。
    """
    with path.open("r", encoding=encoding, errors="strict", newline="") as f:
        yield from _parse_reader(csv.reader(f))


def parse_text(text: str) -> Iterator[Organization]:
    """文字列からパースする。小さなテスト入力用。

    実データには使わない(メモリに全載せするため)。実データは parse_file を使う。
    """
    yield from _parse_reader(csv.reader(io.StringIO(text)))


def _parse_reader(reader: Iterator[list[str]]) -> Iterator[Organization]:
    for row in reader:
        if not row or not any(c.strip() for c in row):
            continue
        bangou = _cell(row, "houjin_bangou")
        if not HOUJIN_BANGOU_RE.match(bangou):
            continue
        kind = _cell(row, "kind_code")
        yield Organization(
            uri=org_uri(bangou),
            houjin_bangou=bangou,
            name=_cell(row, "name"),
            kind_code=kind,
            prefecture=_cell(row, "prefecture"),
            city=_cell(row, "city"),
            street=_cell(row, "street"),
            is_government_organ=(kind == GOVERNMENT_ORGAN_KIND),
        )
