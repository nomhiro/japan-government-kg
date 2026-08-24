"""ソースの鮮度監視(設計書§1.2(C)「更新の一巡」の一部)。

`sources.py` の `expected_cadence_days`(そのソースが「これくらいの周期で
更新されるはず」という機械可読な期待値)と、レイクに実際に残っている
最終取得日(`lake.latest`)を突き合わせ、超過しているソースを一覧で返す。

**判定に使うのは「レイクに記録された事実」だけ**(推測しない)。取得を試みて
失敗したことはここでは分からない(コネクタ・呼び出し側の責務)。ここが
答えるのは「最後に成功した取得はいつで、それは想定周期を超えているか」
だけである。
"""
import datetime
from collections.abc import Mapping
from dataclasses import dataclass

from jgkg import lake, sources


@dataclass(frozen=True)
class StaleSource:
    """陳腐化していると判定されたソース1件。"""

    source_id: str
    # レイクに一度も記録が無い場合は None。「まだ一度も取得していない」ことと
    # 「取得したが古い」ことを型で区別する(§8.2「未解決を沈黙させない」と
    # 同じ形 — 0件目のOrganizationを空文字ではなくNoneで表す既存の作法と揃える)
    last_fetched_on: datetime.date | None
    expected_cadence_days: int
    # last_fetched_on が None のときも None(「何日超過か」を計算する基準が
    # そもそも無い)。0 と混同しない — 0は「ちょうど期限」ではなく「不明」を表す
    days_since_last_fetch: int | None


def report(
    today: datetime.date,
    registry: Mapping[str, sources.Source] | None = None,
) -> list[StaleSource]:
    """`today` 時点で陳腐化しているソースの一覧を返す(source_id順にソート済み)。

    **cadenceを持たないソース(参照表など。`expected_cadence_days=None`が既定)
    は対象外**(無期限。`sources.Source.expected_cadence_days` のdocstring
    参照 — ministry-codesのような手動更新のみの参照表に「陳腐化」を適用すると、
    誰も更新していないだけの安定運用を誤って警報にする)。

    **「対象0件で合格」に退化させない**(task-10-brief.md「このタスクで踏み
    やすい欠陥の型」4番: 「ソースが1つも登録されていない状態で『全部新鮮』を
    返さないこと」)。`registry`(既定は`sources.SOURCES`)が1件も持たない
    状態は、`report(today) == []`(全ソース新鮮の場合と同じ形)を返すと
    区別できなくなるため、明示的に例外にする。

    **「非空だがcadenceを持つソースが1件も無い」場合は例外にしない**
    (`[]`を返す)。これは「無期限のソースだけを見たい」という呼び出し側の
    意図的な絞り込みでもあり得る、上記の罠とは別の状態である。
    """
    reg = sources.SOURCES if registry is None else registry
    if not reg:
        raise ValueError(
            "鮮度監視の対象ソースが1つも登録されていない。"
            "sources.py の設定漏れ、またはregistryの絞り込みが行き過ぎている"
            "疑いがある(対象0件で合格に退化させない。"
            "task-10-brief.md「踏みやすい欠陥の型」4番)"
        )
    tracked = {
        source_id: src
        for source_id, src in reg.items()
        if src.expected_cadence_days is not None
    }

    stale: list[StaleSource] = []
    for source_id, src in tracked.items():
        last = lake.latest(source_id)
        if last is None:
            # **一度も取得していないことを「新鮮」として黙って通さない。**
            # cadence追跡対象なのにレイクに記録が無いのは、鮮度以前の欠落
            # そのものであり、「まだ間に合っている」より重大な状態である
            stale.append(
                StaleSource(
                    source_id=source_id,
                    last_fetched_on=None,
                    expected_cadence_days=src.expected_cadence_days,
                    days_since_last_fetch=None,
                )
            )
            continue
        days_since = (today - last).days
        # **境界は「超過」のみを陳腐化とする(`>`。`>=`ではない)。**
        # ちょうど周期日数が経過した時点はまだ「期限内」であり、翌日から
        # 「超過」になる、という素直な解釈を採る
        if days_since > src.expected_cadence_days:
            stale.append(
                StaleSource(
                    source_id=source_id,
                    last_fetched_on=last,
                    expected_cadence_days=src.expected_cadence_days,
                    days_since_last_fetch=days_since,
                )
            )
    return sorted(stale, key=lambda s: s.source_id)
