"""Task 11 Step 4「経路1」+ 必須項目9・10 の実測。

e-Gov法令API v2 の全法令メタデータ(実データ)に対して、§7.3 経路1
(法令番号から所管府省を導出する)の**現存府省に解決できた割合**を出す。
`pipeline.run` は延べ件数(`law_jurisdiction_resolved` / `_unresolved` /
`_extraction_failed`)しか報告しないため、内訳(OLD_MINISTRY /
OBSOLETE_ORGANIZATION / NO_CANDIDATE / AMBIGUOUS)と、
`EXTRACTION_FAILED` の**法形式ごとの内訳**はここで出す。

出す数字(いずれもブリーフの要求項目):
  1. 経路1の対象(=法令番号が「(元号)年○○令第n号」の形をしている)件数
  2. そのうち現存府省に解決できた法令の件数と割合
  3. 未解決の内訳(法令単位・名称単位の両方)
  4. `EXTRACTION_FAILED` の件数を **law_type / law_num_type ごとの内訳**で
     (必須項目9: 皇室令など非府省令もここに拾われるため、総数を「経路1の
     欠陥」と読むと過大評価になる)
  5. 「内閣官房令」が実データに存在するか(必須項目10。Task 4 観察3)

**使い捨てにしない**(裁定B25)。出力は docs/measurements-phase1.md に全量転記する。

使い方:
    uv run python scripts/measure_jurisdiction_resolution.py
    uv run python scripts/measure_jurisdiction_resolution.py --egov-date 2026-08-24
"""
import argparse
import collections
import datetime
from pathlib import Path

from jgkg import lake
from jgkg.connectors import egov_law, houjin_bangou
from jgkg.transform import law as law_mod
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import old_ministries
from jgkg.transform import organization as org_mod

MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")
DEFAULT_EGOV_DATE = datetime.date(2026, 8, 24)
DEFAULT_HOUJIN_DATE = datetime.date(2026, 8, 23)

# 必須項目10(Task 4 観察3): 「内閣官房令」が実在するかを実データで確認する。
# `law.extract_ministry_names` は法令番号から「○○令」の○○を取るため、
# 実在しない法形式を参照表に足す判断をしていないかを確かめる
CABINET_SECRETARIAT_ORDINANCE = "内閣官房令"


def _ministry_reference_by_name(houjin_date: datetime.date):
    """`pipeline.run` と同じ経路で参照表を突合し、名称→府省の索引を作る。

    **府省名簿(40行)だけを読む近道をしない。** 経路1が解決に使うのは
    「法人番号の実データと突合できた府省」であり、参照表に名前があっても
    実データに無い府省では解決しない(`ministry.build` の unmatched)。
    `pipeline.run` が使うのと同じ関数を同じ順で呼ぶ。
    """
    snapshot_path = lake.path_of("houjin-bangou", houjin_date, houjin_bangou.FILENAME)
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"houjin-bangouの実データが無い: {snapshot_path}。"
            " このスクリプトは実データでの確定値を出すためのものである"
        )
    orgs = [o for o in org_mod.parse_source(snapshot_path) if o.is_government_organ]
    reference = ministry_mod.load_reference(MINISTRY_REFERENCE)
    ministries, unmatched = ministry_mod.build(orgs, reference)
    return (
        law_mod.to_ministry_reference(ministries),
        len(orgs),
        len(ministries),
        len(unmatched),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--egov-date", type=datetime.date.fromisoformat,
                        default=DEFAULT_EGOV_DATE)
    parser.add_argument("--houjin-date", type=datetime.date.fromisoformat,
                        default=DEFAULT_HOUJIN_DATE)
    args = parser.parse_args()

    laws_path = lake.path_of("egov-law", args.egov_date, egov_law.FILENAME)
    if not laws_path.exists():
        raise FileNotFoundError(f"egov-lawの実データが無い: {laws_path}")

    ref_by_name, gov_organs, ministries, unmatched = _ministry_reference_by_name(
        args.houjin_date
    )
    old_names = old_ministries.load_old_ministries()

    print("=" * 78)
    print("経路1(法令番号 → 所管府省)の解決率 — 実データ")
    print("=" * 78)
    print(f"egov-law スナップショット : {laws_path}")
    print(f"houjin-bangou スナップショット: 取得日 {args.houjin_date.isoformat()}")
    print(f"国の機関(法人種別101)     : {gov_organs} 件")
    print(f"参照表と突合できた府省       : {ministries} 件(未突合 {unmatched} 件)")
    print()

    total = 0
    # 経路1の対象外(法令番号が「○○令第n号」の形をしていない。政令・法律など)
    not_applicable = 0
    extraction_failed = 0
    extraction_failed_by_law_type: collections.Counter[str] = collections.Counter()
    extraction_failed_by_num_type: collections.Counter[str] = collections.Counter()
    extraction_failed_examples: list[tuple[str, str, str]] = []

    # 法令単位: 抽出した名称が**すべて**解決した / 一部だけ / 1件も解決しない
    fully_resolved = 0
    partially_resolved = 0
    none_resolved = 0

    # 名称単位(延べ)
    names_resolved = 0
    reason_counts: collections.Counter[str] = collections.Counter()
    unresolved_names: collections.Counter[tuple[str, str]] = collections.Counter()

    joint_ordinances = 0  # 共同省令(抽出名称が2件以上)
    cabinet_secretariat_hits: list[tuple[str, str, str]] = []

    for record in law_mod.parse_laws(laws_path):
        total += 1
        if CABINET_SECRETARIAT_ORDINANCE in record.law_num:
            cabinet_secretariat_hits.append(
                (record.law_id, record.law_num, record.law_title)
            )

        jr = law_mod.derive_jurisdiction(record, ref_by_name, old_names)
        if jr is law_mod.EXTRACTION_FAILED:
            extraction_failed += 1
            extraction_failed_by_law_type[record.law_type] += 1
            extraction_failed_by_num_type[record.law_num_type] += 1
            if len(extraction_failed_examples) < 20:
                extraction_failed_examples.append(
                    (record.law_id, record.law_num, record.law_type)
                )
            continue
        if jr is None:
            not_applicable += 1
            continue

        if len(jr.ministry_names) >= 2:
            joint_ordinances += 1
        names_resolved += len(jr.resolved)
        for u in jr.unresolved:
            reason_counts[u.reason] += 1
            unresolved_names[(u.name, u.reason)] += 1

        if jr.resolved and not jr.unresolved:
            fully_resolved += 1
        elif jr.resolved:
            partially_resolved += 1
        else:
            none_resolved += 1

    in_scope = fully_resolved + partially_resolved + none_resolved
    print(f"法令の総数(laws.jsonl の行数)      : {total}")
    print(f"経路1の対象外(「○○令第n号」でない): {not_applicable}")
    print(f"EXTRACTION_FAILED(形はしているが抽出不能): {extraction_failed}")
    print(f"経路1の対象(名称を抽出できた法令)  : {in_scope}")
    print()
    print("--- 法令単位の解決 ---")
    if in_scope:
        print(f"全名称が解決     : {fully_resolved} ({fully_resolved / in_scope:.1%})")
        print(f"一部だけ解決     : {partially_resolved} ({partially_resolved / in_scope:.1%})")
        print(f"1件も解決しない  : {none_resolved} ({none_resolved / in_scope:.1%})")
        resolved_any = fully_resolved + partially_resolved
        print(f"少なくとも1件解決: {resolved_any} ({resolved_any / in_scope:.1%})")
    print(f"共同省令(抽出名称が2件以上): {joint_ordinances}")
    print()
    print("--- 名称単位(延べ。pipeline-report.json の law_jurisdiction_* と一致する ---")
    print(f"resolved   : {names_resolved}")
    print(f"unresolved : {sum(reason_counts.values())}")
    for reason, count in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<24}: {count}")
    print()
    print("--- 未解決の名称(全件。理由つき) ---")
    for (name, reason), count in sorted(
        unresolved_names.items(), key=lambda kv: (-kv[1], kv[0])
    ):
        print(f"  {count:>6}  {reason:<24} {name}")
    print()
    print("--- 必須項目9: EXTRACTION_FAILED の法形式ごとの内訳 ---")
    print("(皇室令など非府省令もここに拾われるため、総数を「経路1の欠陥」と")
    print(" 読むと過大評価になる。task-4-report.md の申し送り)")
    print("law_type 別:")
    for law_type, count in sorted(extraction_failed_by_law_type.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6}  {law_type}")
    print("law_num_type 別:")
    for num_type, count in sorted(extraction_failed_by_num_type.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6}  {num_type}")
    print("例(最大20件):")
    for law_id, law_num, law_type in extraction_failed_examples:
        print(f"  {law_id}  {law_type:<24} {law_num}")
    print()
    print("--- 必須項目10: 「内閣官房令」は実データに存在するか ---")
    if cabinet_secretariat_hits:
        print(f"存在する: {len(cabinet_secretariat_hits)} 件")
        for law_id, law_num, title in cabinet_secretariat_hits[:20]:
            print(f"  {law_id}  {law_num}  {title}")
    else:
        print("**存在しない**(法令番号に「内閣官房令」を含む法令は0件)")


if __name__ == "__main__":
    main()
