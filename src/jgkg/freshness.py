"""ソースの鮮度監視(設計書§1.2(C)「更新の一巡」の一部)。

`sources.py` の `expected_cadence_days`(そのソースが「これくらいの周期で
更新されるはず」という機械可読な期待値)と、レイクに実際に残っている
最終取得日(`lake.latest`)を突き合わせ、超過しているソースを一覧で返す。

**判定に使うのは「レイクに記録された事実」だけ**(推測しない)。取得を試みて
失敗したことはここでは分からない(コネクタ・呼び出し側の責務)。ここが
答えるのは「最後に成功した取得はいつで、それは想定周期を超えているか」
だけである。

CLI(Task 11 / B28。**呼び出し元を持たない記録を作らない**——I3(照合しない
manifest)・F-5(ゲートを通らない出典グラフ)と同型の欠陥を避けるため、
`report()`には実際の消費者が要る。`scripts/build.sh` がリリースを作る前に
これを呼び、陳腐化しているソースを必ず標準出力に出す):

    uv run python -m jgkg.freshness                      # 今日基準で人が読む形
    uv run python -m jgkg.freshness --today 2026-08-24   # 基準日を明示する
    uv run python -m jgkg.freshness --json               # 機械可読
    uv run python -m jgkg.freshness --fail-on-stale      # 1件でもあれば exit 1
"""
import argparse
import datetime
import json
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


def _format_human(stale: list[StaleSource], today: datetime.date) -> list[str]:
    """人が読む形。**「何も出ない」を成功と誤読させない**ため、陳腐化0件でも
    「何件を見て何件が陳腐化だったか」を必ず1行出す。"""
    tracked = [
        s for s in sources.SOURCES.values() if s.expected_cadence_days is not None
    ]
    lines = [
        (
            f"鮮度監視({today.isoformat()} 基準): 追跡対象 {len(tracked)} ソース"
            f" / 陳腐化 {len(stale)} 件"
        )
    ]
    for s in stale:
        if s.last_fetched_on is None:
            lines.append(
                f"  [未取得] {s.source_id}: レイクに記録が無い"
                f"(期待周期 {s.expected_cadence_days} 日)"
            )
        else:
            lines.append(
                f"  [陳腐化] {s.source_id}: 最終取得 {s.last_fetched_on.isoformat()}"
                f" / {s.days_since_last_fetch} 日経過"
                f"(期待周期 {s.expected_cadence_days} 日)"
            )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="レイクの最終取得日と期待周期を突き合わせ、陳腐化したソースを出す"
    )
    parser.add_argument(
        "--today",
        type=datetime.date.fromisoformat,
        default=None,
        help="判定の基準日(YYYY-MM-DD)。既定は実行日。テストや再現のために明示できる",
    )
    parser.add_argument("--json", action="store_true", help="機械可読なJSONで出す")
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="陳腐化が1件でもあれば exit 1。**既定は exit 0**"
        "(リリースを止めるかどうかは呼び出し側の判断であり、"
        "鮮度そのものは成果物の正しさの条件ではない)",
    )
    args = parser.parse_args(argv)

    # CLIの既定値としての「今日」。--today で明示できるようにしてあり、
    # テストは常に明示値を渡す(ローカル日付でよい。鮮度は日単位の運用指標)
    today = args.today or datetime.date.today()  # noqa: DTZ011
    stale = report(today)

    if args.json:
        print(
            json.dumps(
                {
                    "today": today.isoformat(),
                    "stale": [
                        {
                            "source_id": s.source_id,
                            "last_fetched_on": (
                                s.last_fetched_on.isoformat()
                                if s.last_fetched_on is not None
                                else None
                            ),
                            "expected_cadence_days": s.expected_cadence_days,
                            "days_since_last_fetch": s.days_since_last_fetch,
                        }
                        for s in stale
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for line in _format_human(stale, today):
            print(line)

    return 1 if (stale and args.fail_on_stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
