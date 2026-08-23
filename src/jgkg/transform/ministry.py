"""府省マスターの構築。

正準IDは法人番号(設計書§4.1)。**主キーは名称**(裁定B12): 結合キーとして
`ministry_code` を実際に消費する経路が無いと判明した(Task 6検証0。RS実データの
所管府省庁列は名称のみで、コード列は存在しない)ため、`ministry_code` は
「分かる場合にのみ持つ」任意の識別子プロパティに位置づけを変えた。突合できな
かったものは捨てずに返し、件数を報告できるようにする(§8.2)。
"""
import csv
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel

from jgkg.transform.organization import Organization


class Ministry(BaseModel):
    uri: str
    houjin_bangou: str
    name: str
    # 現行コードの一次資料が見つかっていないため既定はNone(裁定B12)。
    # 将来出典が確定した府省だけ値を持つ、という非対称を型で表す
    ministry_code: str | None = None


class UnmatchedMinistry(BaseModel):
    name: str
    reason: str  # NO_CANDIDATE / AMBIGUOUS
    ministry_code: str | None = None


class MinistryReferenceRow(NamedTuple):
    """参照表(CSV)の1行。`load_reference` の戻り値の要素。

    ミニストリーコード・名称の2要素はTask 5(裁定B12)以来。`kensei_jun`は
    レビュー指摘2(裁定B15の実装漏れ)で追加した第3要素で、既定値Noneを
    持つため、既存コードが2要素タプル `(code, name)` を渡す/受け取る箇所
    (テスト内の手組みreference等)を書き換えずに済む(タプルの構造的な
    互換性。`build()` 側は `*_` で吸収する)。**kensei_junはCSVの列としてのみ
    存在し、Ministry/emit_ministriesへは伝播しない**(裁定B15: 建制順は
    儀典上の序列でministry_codeの意味論と違うため、オントロジーのプロパティ
    にもしない)。
    """

    ministry_code: str | None
    name: str
    kensei_jun: str | None = None


def load_reference(path: Path) -> list[MinistryReferenceRow]:
    """府省コード参照表を読む。# で始まる行はコメントとして飛ばす。

    **name は必須、ministry_code は任意**(裁定B12)。コード列が空の行を
    黙って捨てない — 以前は `if code and name` で名称だけの行ごと消えていたが、
    それは「主キーは名称」という今の設計と矛盾する。

    **kensei_jun(建制順)列も読む**(裁定B15、レビュー指摘2)。列が無い/値が
    空のCSVでもNoneになるので、v2形式(kensei_jun列無し)のCSVを渡す既存の
    呼び出し・テストは変更なしに動く
    """
    out: list[MinistryReferenceRow] = []
    with path.open(encoding="utf-8") as f:
        rows = [line for line in f if not line.lstrip().startswith("#")]
    reader = csv.DictReader(rows)
    for row in reader:
        code = (row.get("ministry_code") or "").strip() or None
        name = (row.get("name") or "").strip()
        kensei_jun = (row.get("kensei_jun") or "").strip() or None
        if name:
            out.append(MinistryReferenceRow(code, name, kensei_jun))
    return out


def build(
    orgs: Iterable[Organization],
    reference: Iterable[tuple[str | None, str] | MinistryReferenceRow],
) -> tuple[list[Ministry], list[UnmatchedMinistry]]:
    """国の機関のみを対象に、名称で府省コードと突合する。

    同名が複数ある場合は AMBIGUOUS として未解決にする。誤って1つを選ぶより、
    未解決として可視化する方が公共財として正しい。

    `reference` の各行は2要素`(code, name)`・3要素(`MinistryReferenceRow`
    互換、`kensei_jun`付き)のいずれでもよい(`*_`で余剰要素を吸収する)。
    kensei_junは突合には使わず、Ministry/UnmatchedMinistryへも伝播しない
    (裁定B15。上記`MinistryReferenceRow`のdocstring参照)
    """
    candidates: dict[str, list[Organization]] = {}
    for org in orgs:
        if not org.is_government_organ:
            continue
        candidates.setdefault(org.name, []).append(org)

    ministries: list[Ministry] = []
    unmatched: list[UnmatchedMinistry] = []

    for code, name, *_ in reference:
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
