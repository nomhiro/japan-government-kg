"""府省マスターの構築。

正準IDは法人番号(設計書§4.1)。府省コードは識別子プロパティとして持つ。
突合できなかったものは捨てずに返し、件数を報告できるようにする(§8.2)。
"""
import csv
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from jgkg.transform.organization import Organization


class Ministry(BaseModel):
    uri: str
    houjin_bangou: str
    ministry_code: str
    name: str


class UnmatchedMinistry(BaseModel):
    ministry_code: str
    name: str
    reason: str  # NO_CANDIDATE / AMBIGUOUS


def load_reference(path: Path) -> list[tuple[str, str]]:
    """府省コード参照表を読む。# で始まる行はコメントとして飛ばす。"""
    out: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as f:
        rows = [line for line in f if not line.lstrip().startswith("#")]
    reader = csv.DictReader(rows)
    for row in reader:
        code = (row.get("ministry_code") or "").strip()
        name = (row.get("name") or "").strip()
        if code and name:
            out.append((code, name))
    return out


def build(
    orgs: Iterable[Organization],
    reference: list[tuple[str, str]],
) -> tuple[list[Ministry], list[UnmatchedMinistry]]:
    """国の機関のみを対象に、名称で府省コードと突合する。

    同名が複数ある場合は AMBIGUOUS として未解決にする。誤って1つを選ぶより、
    未解決として可視化する方が公共財として正しい。
    """
    candidates: dict[str, list[Organization]] = {}
    for org in orgs:
        if not org.is_government_organ:
            continue
        candidates.setdefault(org.name, []).append(org)

    ministries: list[Ministry] = []
    unmatched: list[UnmatchedMinistry] = []

    for code, name in reference:
        matches = candidates.get(name, [])
        if len(matches) == 1:
            org = matches[0]
            ministries.append(
                Ministry(
                    uri=org.uri,
                    houjin_bangou=org.houjin_bangou,
                    ministry_code=code,
                    name=name,
                )
            )
        else:
            unmatched.append(
                UnmatchedMinistry(
                    ministry_code=code,
                    name=name,
                    reason="AMBIGUOUS" if len(matches) > 1 else "NO_CANDIDATE",
                )
            )

    return ministries, unmatched
