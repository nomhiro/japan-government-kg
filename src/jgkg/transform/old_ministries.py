"""旧省庁名の判定集合(**2001年の中央省庁等改革で廃止された名称に限る**)。

設計書§7.2 / 本計画のB-5は、旧省庁名→現存府省の**継承マッピングを作らない**
ことを明示的にPhase 2へ送っている(「厚生省と労働省のどちらが厚生労働省の
何を継承したか」のような対応は、複数対複数になり得て、決定的な経路1の
範囲を超える判断を持ち込む)。

ここで持つのは対応関係ではなく、**「もう存在しない」という判定のための集合**
だけである。ただし**2001年再編分だけ**(裁定B7でenumの定義文をこう狭めた —
それ以前に廃止された省庁は明治以来無数にあり、列挙する道を採ると§7.2が
継承マッピングをPhase 2へ送ったのと同じ罠を踏む)。`transform/law.py` の
`derive_jurisdiction` は、この集合に名称が載っていれば `OLD_MINISTRY`、
載っていなくても政府機関の形(省/府/庁/院/委員会等)をしていれば
`OBSOLETE_ORGANIZATION`(列挙せず形から導出。2001年より前に廃止された省庁や、
未収録だが現存する機関がここに入る)、どちらでもなければ `NO_CANDIDATE`
として未解決を分類する(§8.2「未解決を沈黙させない」。理由の分類そのものが
目的なので、この集合を削って理由が化けることを確認するテストが
`tests/test_transform_law.py` にある)。
"""
import csv
from pathlib import Path

DEFAULT_PATH = Path("data/reference/old-ministries.csv")


def load_old_ministries(path: Path = DEFAULT_PATH) -> set[str]:
    """旧省庁名の集合を読む。`#` で始まる行はコメントとして飛ばす(`ministry.load_reference` と同じ規約)。"""
    with path.open(encoding="utf-8") as f:
        rows = [line for line in f if not line.lstrip().startswith("#")]
    reader = csv.DictReader(rows)
    names: set[str] = set()
    for row in reader:
        name = (row.get("name") or "").strip()
        if name:
            names.add(name)
    return names
