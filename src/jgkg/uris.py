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


def law_version_uri(law_id: str, date: datetime.date) -> str:
    return f"{law_uri(law_id)}/{date:%Y%m%d}"


def graph_uri(source_id: str, fetched_on: datetime.date) -> str:
    if not source_id:
        raise ValueError("ソースIDが空である")
    return f"{_base()}/graph/{quote(source_id, safe='')}/{fetched_on:%Y-%m-%d}"


def term_uri(module: str, term: str) -> str:
    return f"{_base()}/def/{quote(module, safe='')}#{term}"
