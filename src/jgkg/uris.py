"""URIの構築。設計書§4.2で固定したパターンをここだけで表現する。"""
import datetime
import re
from urllib.parse import quote

from jgkg.config import get_settings

HOUJIN_BANGOU_RE = re.compile(r"^\d{13}$")


def _base() -> str:
    return get_settings().base_uri


def org_uri(houjin_bangou: str) -> str:
    if not HOUJIN_BANGOU_RE.match(houjin_bangou):
        raise ValueError(f"法人番号は13桁の数字である必要がある: {houjin_bangou!r}")
    return f"{_base()}/id/org/{houjin_bangou}"


def law_uri(law_id: str) -> str:
    if not law_id:
        raise ValueError("法令IDが空である")
    return f"{_base()}/id/law/{quote(law_id, safe='')}"


def law_version_uri(
    law_id: str, date: datetime.date, amendment_law_num: str | None = None
) -> str:
    """`law:LawRevision` のURI。

    施行日だけを鍵にすると、同一施行日の改正が2件あれば1つのURIに合流し、
    `amendmentLawNum` が2値になって閉じたシェイプの `sh:maxCount 1` に違反する
    (レビュー指摘10。隔離の単位はグラフなので、その取得日の全法令が丸ごと
    落ちる)。改正法令番号を追加の鍵にして区別する。`None`(改正法令番号が
    無い行。現状のコネクタでは起こらないが型としてはあり得る)の場合は、
    従来どおり日付のみのURIにする(鍵の材料が無いところへ無理に材料を作らない)。
    """
    if amendment_law_num:
        return f"{law_uri(law_id)}/{date:%Y%m%d}_{quote(amendment_law_num, safe='')}"
    return f"{law_uri(law_id)}/{date:%Y%m%d}"


def unresolved_jurisdiction_uri(law_id: str, name: str) -> str:
    """経路1(法令番号→府省)で解決できなかった名称の `core:UnresolvedReference` ノードのURI。

    `name` だけを鍵にしない。複数の法令が同じ旧省庁名(例: 大蔵省令が数百件)を
    指すたびに1つのノードへ収束すると、UnresolvedReference の件数が法令ごとの
    ミス件数(CQ9が数えたいもの)ではなく「名称の種類数」に潰れてしまう
    """
    if not law_id or not name:
        raise ValueError("law_id と name はいずれも空であってはならない")
    return f"{_base()}/id/unresolved/jurisdiction/{quote(law_id, safe='')}/{quote(name, safe='')}"


def graph_uri(source_id: str, fetched_on: datetime.date) -> str:
    if not source_id:
        raise ValueError("ソースIDが空である")
    return f"{_base()}/graph/{quote(source_id, safe='')}/{fetched_on:%Y-%m-%d}"


def term_uri(module: str, term: str) -> str:
    return f"{_base()}/def/{quote(module, safe='')}#{term}"
