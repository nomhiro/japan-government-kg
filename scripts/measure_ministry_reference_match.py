"""Task 11 Step 4「府省参照表の突合」+ 必須項目6の一部の実測。

`data/reference/ministry-codes.csv`(裁定B15で40行)の**全行が、法人番号
公表サイトの実データ(国の機関848件)に一意一致するか**を行ごとに出す。
`pipeline.run` は `ministries` / `unmatched_ministries` の2つの件数しか
報告しないため、「どの行が」「なぜ」一致しなかったかはここで出す。

参照表の3行(人事院・会計検査院・国家公安委員会)はRSの年度更新に追従しない
と `sources.py` の note が明記しており、「継続的な整合性はTask 11等の実データ
再検証で別途確認すること」と申し送られている。ここがその再検証にあたる。

さらに、国の機関側に**同名が複数ある**(AMBIGUOUSの原因)ケースと、
**参照表に無いが国の機関として実在する名称**(参照表の網羅性の逆向きの確認)も
出す。片方向だけ見ると「40行が一致した」で満足してしまう。

**使い捨てにしない**(裁定B25)。出力は docs/measurements-phase1.md に全量転記する。

使い方:
    uv run python scripts/measure_ministry_reference_match.py
    uv run python scripts/measure_ministry_reference_match.py --houjin-date 2026-08-23
"""
import argparse
import collections
import datetime
from pathlib import Path

from jgkg import lake, sources
from jgkg.connectors import houjin_bangou
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import organization as org_mod

MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")
DEFAULT_HOUJIN_DATE = datetime.date(2026, 8, 23)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--houjin-date", type=datetime.date.fromisoformat,
                        default=DEFAULT_HOUJIN_DATE)
    args = parser.parse_args()

    snapshot_path = lake.path_of("houjin-bangou", args.houjin_date, houjin_bangou.FILENAME)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"houjin-bangouの実データが無い: {snapshot_path}")

    stats = org_mod.ParseStats()
    orgs = [
        o for o in org_mod.parse_source(snapshot_path, stats=stats)
        if o.is_government_organ
    ]
    reference = ministry_mod.load_reference(MINISTRY_REFERENCE)
    ministries, unmatched = ministry_mod.build(orgs, reference)

    by_name: dict[str, list[org_mod.Organization]] = {}
    for o in orgs:
        by_name.setdefault(o.name, []).append(o)

    print("=" * 78)
    print("府省参照表(ministry-codes.csv)と実データ(国の機関)の突合")
    print("=" * 78)
    print(f"スナップショット   : {snapshot_path}")
    print(f"参照表             : {MINISTRY_REFERENCE}")
    print(f"参照表の内容ハッシュ: {sources.content_digest(MINISTRY_REFERENCE.read_bytes())}")
    print(f"sources.py の記録  : {sources.get_source('ministry-codes').sha256}")
    print(f"入力の非空行数     : {stats.rows_seen:,}")
    print(f"国の機関(法人種別{org_mod.GOVERNMENT_ORGAN_KIND}): {len(orgs)} 件")
    print(f"参照表の行数       : {len(reference)}")
    print(f"一意一致           : {len(ministries)} 件")
    print(f"未突合             : {len(unmatched)} 件")
    print()

    print("--- 参照表の全行(一致した法人番号 / 一致しなかった理由) ---")
    resolved_by_name = {m.name: m for m in ministries}
    unmatched_by_name = {u.name: u for u in unmatched}
    for code, name, *rest in reference:
        kensei = rest[0] if rest else None
        n_candidates = len(by_name.get(name, []))
        if name in resolved_by_name:
            m = resolved_by_name[name]
            print(f"  OK        {name:<20} 法人番号={m.houjin_bangou} "
                  f"候補数={n_candidates} 建制順={kensei or '-'} code={code or '-'}")
        else:
            u = unmatched_by_name[name]
            print(f"  **NG**    {name:<20} 理由={u.reason} "
                  f"候補数={n_candidates} 建制順={kensei or '-'} code={code or '-'}")
    print()

    print("--- 国の機関側で同名が複数ある名称(AMBIGUOUSの原因になりうる) ---")
    dupes = {n: v for n, v in by_name.items() if len(v) > 1}
    if not dupes:
        print("  なし(848件の名称はすべて一意)")
    for name, group in sorted(dupes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        in_ref = "参照表にある" if name in {r.name for r in reference} else "参照表に無い"
        print(f"  {len(group)} 件  {name}  ({in_ref})  "
              f"法人番号={[o.houjin_bangou for o in group]}")
    print()

    print("--- 参照表に無いが国の機関として実在する名称(逆向きの網羅性) ---")
    ref_names = {r.name for r in reference}
    extra = sorted(n for n in by_name if n not in ref_names)
    print(f"  {len(extra)} 件(848件のうち参照表が拾っていない名称)")
    print("  先頭50件:")
    for name in extra[:50]:
        print(f"    {name}")
    print()

    print("--- 名称の分布(参照表の網羅範囲を読むための補助) ---")
    suffix_counts: collections.Counter[str] = collections.Counter()
    for name in by_name:
        # 末尾1文字で粗く分類する。**分類そのものを結論にしない**(観測のみ)
        suffix_counts[name[-1] if name else ""] += 1
    for suffix, count in suffix_counts.most_common(20):
        print(f"  {count:>5}  末尾「{suffix}」")


if __name__ == "__main__":
    main()
