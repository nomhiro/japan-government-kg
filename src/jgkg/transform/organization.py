"""法人番号 全件CSV → Organization。

全件CSVはヘッダなしで列位置が仕様で決まっている。列位置はここに集約し、
仕様変更時の修正点を1箇所に限定する。
"""
import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from jgkg.uris import HOUJIN_BANGOU_RE, org_uri

# =============================================================================
# **未了: 下の COL は一次資料と照合されていない。実データ投入前の必須手順。**
#
# リポジトリのどこにも国税庁の資源定義書(全件データのレイアウト仕様)への参照も
# 引用も無い。唯一の検証手段である `tests/fixtures/houjin_bangou_sample.csv` は
# COL に合わせて書かれているため、**テストは構造上 COL の誤りに反対できない**
# (円環の内側を検証している)。全件データの実際の列数は15列より多い。
#
# 実データを投入する前に、次を人が確認して結果をここに書くこと:
#
#   1. 国税庁 法人番号公表サイトの「資源定義書」を取得し、そのURL・版・公開日を
#      このコメントに追記する
#   2. 総列数を確認して EXPECTED_COLUMNS に書く(今は必要な列の下限しか見ていない)
#   3. 各列の索引を照合する: 法人番号 / 法人種別 / 商号又は名称 /
#      本店所在地(都道府県・市区町村・丁目番地等)
#   4. 実データの先頭1行を docs/ に引用し、列番号との対応を残す
#   5. fixture を実データの列数に合わせて作り直す。列数が一致していれば COL の
#      誤りを fixture 側から独立に検出できるようになる
#
# それまでの間の安全装置として、**列レイアウトが想定と違えば「0件」ではなく例外に
# する**(`_parse_reader` の収量チェック)。0件を正常終了として返してはならない。
# =============================================================================

# 全件CSVの列位置(0起点)。仕様変更時はここだけを直す。
COL = {
    "houjin_bangou": 1,
    "kind_code": 5,
    "name": 6,
    "prefecture": 12,
    "city": 13,
    "street": 14,
}

# COL が要求する最小の列数。一次資料で総列数を確定したら
# EXPECTED_COLUMNS として厳密な等値検査に格上げする(上の1〜5を参照)
MIN_COLUMNS = max(COL.values()) + 1

# 法人種別コードは3桁(101 国の機関 / 201 地方公共団体 / 301 株式会社 など)。
# 列がずれると日付や名称がここに入るので、形の検査が索引のずれを検出する
KIND_CODE_RE = re.compile(r"^\d{3}$")

# 法人種別コード 101 = 国の機関
GOVERNMENT_ORGAN_KIND = "101"

# 収量チェックの下限。行単位のノイズ(全件データ末尾の集計行など)は許容しつつ、
# **列レイアウトの誤りは必ず捕まえる**ための境界。索引がずれれば棄却率は
# ほぼ100%になるので、半分という緩い境界でも検出できる。逆に、この値を
# 厳しくすると実データの想定外のノイズで止まる
MIN_ACCEPT_RATIO = 0.5


@dataclass
class ParseStats:
    """解析の内訳。**判定に使って捨てるのではなく、呼び出し側に返す。**

    しきい値(`MIN_ACCEPT_RATIO`)を超えなければ `ColumnLayoutError` は出ないが、
    その下では最大49.9%の行が黙って捨てられる。500万行なら約249万行である。
    設計書§11.1の観測性は「各段の件数を出す」ことを求めているのに、
    **最も知りたい数字(捨てた数)がどこにも出ていなかった。**
    """

    rows_seen: int = 0        # 空行以外の行数
    rows_accepted: int = 0    # Organization にした行数
    rows_short: int = 0       # COL が要求する列数に足りなかった行数
    rows_valid_kind: int = 0  # 法人種別コードが3桁だった行数(rows_accepted のうち)

    @property
    def rows_rejected(self) -> int:
        return self.rows_seen - self.rows_accepted


class ColumnLayoutError(ValueError):
    """CSVの列レイアウトが COL の想定と合っていない。

    **0件を正常終了として返さないために存在する。** 索引がずれていると
    `_cell` は空文字を返し、法人番号が13桁でない行は黙って捨てられるため、
    以前は `organizations=0` / `government_organs=0` で「成功」を報告し、
    空のKGがそのまま出荷された。
    """


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


def parse_file(
    path: Path, encoding: str = "utf-8", stats: ParseStats | None = None
) -> Iterator[Organization]:
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

    `stats` に `ParseStats` を渡すと、解析の内訳(非空行数・取り込み数・列数不足数)が
    そこに書き込まれる。**捨てた行数を知る唯一の手段**なので、パイプラインは必ず渡す。
    """
    with path.open("r", encoding=encoding, errors="strict", newline="") as f:
        yield from _parse_reader(csv.reader(f), stats)


def parse_text(text: str, stats: ParseStats | None = None) -> Iterator[Organization]:
    """文字列からパースする。小さなテスト入力用。

    実データには使わない(メモリに全載せするため)。実データは parse_file を使う。
    """
    yield from _parse_reader(csv.reader(io.StringIO(text)), stats)


def _parse_reader(
    reader: Iterator[list[str]], stats: ParseStats | None = None
) -> Iterator[Organization]:
    """1行ずつ Organization にしつつ、**列レイアウトの誤りを最後に例外にする。**

    行単位の棄却は続ける(末尾の集計行などで処理を止めないため)が、棄却が
    支配的なら索引がずれているので例外にする。**ここが無いと、列位置が違う
    ときに0件を返して「成功」になる。**

    検査は列挙を最後まで消費したときに走る。途中で `close()` する呼び出し側
    (ストリーム性の確認など)には適用されない。
    """
    # 呼び出し側が渡した ParseStats をそのまま埋める(渡されなければ内部で持つ)。
    # **集計を判定に使って捨ててはならない。** しきい値の下では最大49.9%の行が
    # 黙って消えるので、捨てた行数は観測性の中心である
    st = stats if stats is not None else ParseStats()

    for row in reader:
        if not row or not any(c.strip() for c in row):
            continue
        st.rows_seen += 1
        if len(row) < MIN_COLUMNS:
            st.rows_short += 1
        bangou = _cell(row, "houjin_bangou")
        if not HOUJIN_BANGOU_RE.match(bangou):
            continue
        kind = _cell(row, "kind_code")
        st.rows_accepted += 1
        if KIND_CODE_RE.match(kind):
            st.rows_valid_kind += 1
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

    _assert_layout_plausible(st)


def _assert_layout_plausible(st: ParseStats) -> None:
    """棄却の分布から列レイアウトの妥当性を判定する。"""
    seen, accepted = st.rows_seen, st.rows_accepted
    short, valid_kind = st.rows_short, st.rows_valid_kind
    if seen == 0:
        # 空のファイルは「レイアウトの誤り」とは区別する。件数の下限は
        # pipeline.run 側で見る(そこでソースごとの意味を持たせられる)
        return

    counts = (
        f"(非空行={seen} 取り込み={accepted} 列数不足={short}"
        f" 法人種別3桁={valid_kind} 必要列数={MIN_COLUMNS})"
    )
    hint = (
        " COL の列位置が一次資料と合っているかを確認する"
        "(transform/organization.py 冒頭の未了項目)"
    )

    if accepted == 0:
        raise ColumnLayoutError(
            f"1行も取り込めなかった。法人番号の列({COL['houjin_bangou']})が"
            f"13桁の数字になっていない。{counts}{hint}"
        )
    if accepted < seen * MIN_ACCEPT_RATIO:
        raise ColumnLayoutError(
            f"棄却された行が多すぎる。{counts}{hint}"
        )
    if short > seen * MIN_ACCEPT_RATIO:
        raise ColumnLayoutError(
            f"列数が足りない行が多すぎる。住所などの列が読めていない。{counts}{hint}"
        )
    if valid_kind < accepted * MIN_ACCEPT_RATIO:
        raise ColumnLayoutError(
            f"法人種別コードが3桁でない行が多すぎる。法人種別の列"
            f"({COL['kind_code']})がずれている疑いがある。{counts}{hint}"
        )
