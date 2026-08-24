"""Task 11 必須項目6(Task 6 懸念12・13)の実測: RSの年度をまたいだ整合。

Task 6 は2025年度分1本しか取得していないため、次の2つを「観察・未検証」の
まま申し送っていた:

  懸念12: **建制順(kensei_jun)の年度をまたいだ安定性**。省庁再編(新設・
    統合・改称)を挟むと番号が変わる可能性があり、確認していない。
    裁定B15により識別子には使わないので実害は無いが、参考値としての
    安定性は測れる。
  懸念13: **budget_summary の (project_id, 予算年度) 複合キーと、project_id
    単独が主キーであるべき他ファイルを突合する際の年度整合**。例えば
    budget_summary の2021年度の行を、同じproject_idのproject_summary
    (常に事業年度=そのファイルの年度)の事業名に結び付けてよいか。
    これは懸念11「project_idの年度をまたいだ安定性」と地続きである。

このスクリプトは2つの事業年度のスナップショットを突き合わせて、次を出す:
  1. 各年度の行数・事業数・府省数(まず土台の規模を並べる)
  2. 府省名 → 建制順 の対応が年度間で変わっていないか(懸念12)
  3. budget_summary に現れる予算年度の分布と、(project_id, 予算年度) の一意性
     (懸念13の前半)
  4. **同じ project_id が両年度に現れたとき、事業名が一致するか**
     (懸念13/11の核心。一致しないなら project_id は年度をまたぐ識別子として
     使えない、という決定的な事実になる)

**使い捨てにしない**(裁定B25)。出力は docs/measurements-phase1.md に全量転記する。

使い方:
    uv run python scripts/measure_rs_cross_year.py \
        --snapshot 2026-08-23 --snapshot 2026-08-24
"""
import argparse
import collections
import datetime

from jgkg.transform import rs as rs_mod
from jgkg.transform import rs_columns

# 突合に使うグループ。**必須4本に限らない** — 建制順は5本すべてに存在する
# (task-6-report.md 照合記録)ので、代表として project_summary を使う
GROUPS = ("project_summary", "budget_summary", "payee_payment_information")


def _paths_for(fetched_on: datetime.date) -> dict[str, object]:
    """その取得日のスナップショット群を group_key へ逆引きする。

    `pipeline._rs_group_paths` と同じ規則(ファイル名テンプレートの照合。
    年をファイル名から推測しない)を使いたいが、あちらは必須4本が揃って
    いないと例外にするため、ここでは同じ実装を呼ぶ(必須4本は実データに
    必ず揃っている)。
    """
    from jgkg import pipeline

    return pipeline._rs_group_paths(fetched_on)


def _fiscal_years_in(group: str, path) -> collections.Counter:
    spec = rs_columns.RS_FILES[group]
    idx = spec.col["fiscal_year"]
    counter: collections.Counter[str] = collections.Counter()
    for row in rs_mod._group_rows(group, path):
        counter[row[idx]] += 1
    return counter


def _snapshot_summary(fetched_on: datetime.date) -> dict:
    paths = _paths_for(fetched_on)
    spec = rs_columns.RS_FILES["project_summary"]
    idx_pid = spec.col["project_id"]
    idx_name = spec.col["project_name"]
    idx_ministry = spec.col["ministry_name"]
    idx_fy = spec.col["fiscal_year"]
    idx_kensei = spec.col["kensei_jun"]

    projects: dict[str, str] = {}         # project_id -> project_name(先頭行)
    ministry_of: dict[str, str] = {}      # project_id -> ministry_name
    kensei: dict[str, set[str]] = {}      # ministry_name -> {建制順}
    fiscal_years: collections.Counter[str] = collections.Counter()
    rows = 0
    for row in rs_mod._group_rows("project_summary", paths["project_summary"]):
        rows += 1
        pid = row[idx_pid]
        fiscal_years[row[idx_fy]] += 1
        kensei.setdefault(row[idx_ministry], set()).add(row[idx_kensei])
        if pid not in projects:
            projects[pid] = row[idx_name]
            ministry_of[pid] = row[idx_ministry]

    # budget_summary: (project_id, 予算年度) の一意性と年度分布
    bspec = rs_columns.RS_FILES["budget_summary"]
    b_pid = bspec.col["project_id"]
    b_byear = bspec.col["budget_fiscal_year"]
    b_fy = bspec.col["fiscal_year"]
    budget_keys: collections.Counter[tuple[str, str]] = collections.Counter()
    budget_years: collections.Counter[str] = collections.Counter()
    budget_sheet_fy: collections.Counter[str] = collections.Counter()
    budget_rows = 0
    for row in rs_mod._group_rows("budget_summary", paths["budget_summary"]):
        budget_rows += 1
        budget_keys[(row[b_pid], row[b_byear])] += 1
        budget_years[row[b_byear]] += 1
        budget_sheet_fy[row[b_fy]] += 1

    return {
        "fetched_on": fetched_on,
        "paths": {g: str(p) for g, p in paths.items()},
        "project_summary_rows": rows,
        "projects": projects,
        "ministry_of": ministry_of,
        "kensei": kensei,
        "fiscal_years": fiscal_years,
        "budget_rows": budget_rows,
        "budget_keys": budget_keys,
        "budget_years": budget_years,
        "budget_sheet_fy": budget_sheet_fy,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot", action="append", type=datetime.date.fromisoformat, required=True,
        help="突合するrs-systemスナップショットの取得日。2回以上指定する",
    )
    args = parser.parse_args()
    if len(args.snapshot) < 2:
        parser.error("--snapshot を2つ以上渡す(年度をまたいだ突合が目的)")

    summaries = [_snapshot_summary(d) for d in args.snapshot]

    print("=" * 78)
    print("RSの年度をまたいだ整合(Task 6 懸念12・13)")
    print("=" * 78)
    for s in summaries:
        print(f"--- 取得日 {s['fetched_on'].isoformat()} ---")
        for g in sorted(s["paths"]):
            print(f"  {g:<40} {s['paths'][g]}")
        print(f"  project_summary の行数 : {s['project_summary_rows']:,}")
        print(f"  事業数(distinct pid)  : {len(s['projects']):,}")
        print(f"  府省数(distinct 府省庁): {len(s['kensei']):,}")
        print(f"  事業年度の分布         : {dict(s['fiscal_years'])}")
        print(f"  budget_summary の行数  : {s['budget_rows']:,}")
        print(f"  budget_summary の事業年度列: {dict(s['budget_sheet_fy'])}")
        print()

    print("### 懸念12: 建制順(kensei_jun)の年度をまたいだ安定性")
    a, b = summaries[0], summaries[1]
    print(f"比較: {a['fetched_on'].isoformat()} vs {b['fetched_on'].isoformat()}")
    # まず年度内での1対1性(Task 6 がfixtureで固定した性質)を実データで確認する
    for s in summaries:
        multi = {k: v for k, v in s["kensei"].items() if len(v) > 1}
        print(f"  {s['fetched_on'].isoformat()}: 府省名1件に建制順が2つ以上 = "
              f"{len(multi)} 件 {multi if multi else ''}")
    common = sorted(set(a["kensei"]) & set(b["kensei"]))
    only_a = sorted(set(a["kensei"]) - set(b["kensei"]))
    only_b = sorted(set(b["kensei"]) - set(a["kensei"]))
    changed = [
        (name, sorted(a["kensei"][name]), sorted(b["kensei"][name]))
        for name in common
        if a["kensei"][name] != b["kensei"][name]
    ]
    print(f"  両年度に現れる府省名 : {len(common)}")
    print(f"  片方だけ({a['fetched_on'].isoformat()}のみ): {only_a}")
    print(f"  片方だけ({b['fetched_on'].isoformat()}のみ): {only_b}")
    print(f"  **建制順が変わった府省: {len(changed)} 件**")
    for name, va, vb in changed:
        print(f"    {name}: {va} -> {vb}")
    if not changed:
        print("    (両年度に現れる府省の建制順はすべて一致した)")
    print()
    print("  両年度の建制順の対応(全件):")
    for name in common:
        print(f"    {name:<24} {sorted(a['kensei'][name])} / {sorted(b['kensei'][name])}")
    print()

    print("### 懸念13(前半): budget_summary の (project_id, 予算年度) 複合キー")
    for s in summaries:
        dupes = {k: v for k, v in s["budget_keys"].items() if v > 1}
        print(f"  {s['fetched_on'].isoformat()}: キー数 {len(s['budget_keys']):,} / "
              f"重複キー {len(dupes):,} 件")
        for k, v in sorted(dupes.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {v} 行  project_id={k[0]} 予算年度={k[1]}")
        print(f"    予算年度の分布: "
              f"{dict(sorted(s['budget_years'].items()))}")
    print()

    print("### 懸念13(核心): 同じ project_id が両年度で同じ事業を指すか")
    shared = sorted(set(a["projects"]) & set(b["projects"]), key=lambda p: (len(p), p))
    print(f"  両年度に現れる project_id : {len(shared):,}")
    print(f"  {a['fetched_on'].isoformat()} のみ: {len(set(a['projects']) - set(b['projects'])):,}")
    print(f"  {b['fetched_on'].isoformat()} のみ: {len(set(b['projects']) - set(a['projects'])):,}")
    same_name = [p for p in shared if a["projects"][p] == b["projects"][p]]
    diff_name = [p for p in shared if a["projects"][p] != b["projects"][p]]
    if shared:
        print(f"  事業名が一致   : {len(same_name):,} ({len(same_name) / len(shared):.1%})")
        print(f"  **事業名が不一致: {len(diff_name):,} ({len(diff_name) / len(shared):.1%})**")
    same_ministry = [p for p in shared if a["ministry_of"][p] == b["ministry_of"][p]]
    if shared:
        print(f"  所管府省が一致 : {len(same_ministry):,} "
              f"({len(same_ministry) / len(shared):.1%})")
    print("  不一致の例(最大30件。project_id / 事業名A / 事業名B):")
    for p in diff_name[:30]:
        print(f"    {p:<8} {a['projects'][p][:40]:<42} {b['projects'][p][:40]}")


if __name__ == "__main__":
    main()
