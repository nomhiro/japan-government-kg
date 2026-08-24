"""Task 11修正ラウンド2 裁定B34の裏付け確認: budget_summaryの会計区分別明細を集計する。

`queries/cq/cq02-ministry-budget-by-year.rq`のbudgetAmount(RSの「当初予算
(合計)」)が**一般会計＋特別会計の合計**であることを、RSの生データから
自分で再現して確かめる(レビュアの主張する数字を転記しない——各項目に
ついて自分で再導出することが裁定B32/B25の要求)。

列25=会計区分・列28=当初予算(明細行。列14の「当初予算(合計)」とは別。
`rs_columns.py`のRS_COL["budget_summary"]で確認済み)。
会計区分が空の行=集計行(列14を持つ)、非空の行=会計区分ごとの明細行
(列28を持つ)。集計行の合計と明細行の合計が一致すれば、「当初予算(合計)」
が実際に会計区分をまたいだ合計であることの実測による裏付けになる。

**使い捨てにしない**(裁定B25)。出力は docs/measurements-phase1.md に転記する。

使い方:
    uv run python scripts/verify_cq2_scope.py \
        --rs-system 2026-08-23 --ministry 厚生労働省 --fiscal-year 2025
"""
import argparse
import datetime

from jgkg import pipeline
from jgkg.transform import rs as rs_mod
from jgkg.transform import rs_columns


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rs-system", type=datetime.date.fromisoformat, required=True)
    parser.add_argument("--ministry", default="厚生労働省")
    parser.add_argument("--fiscal-year", default="2025")
    args = parser.parse_args()

    rs_paths = pipeline._rs_group_paths(args.rs_system)
    spec = rs_columns.RS_FILES["budget_summary"]
    idx_ministry = spec.col["ministry_name"]  # 列5(政策所管府省庁。列6=府省庁ではない)
    idx_fy = spec.col["fiscal_year"]  # 列1(レビューシート自体の事業年度)
    idx_byear = spec.col["budget_fiscal_year"]  # 列13(予算年度。budget_summaryは複数年度を束ねて持つ)
    idx_amount_agg = spec.col["budget_amount"]  # 列14: 当初予算(合計)。会計区分が空の集計行が持つ
    idx_account_kind = spec.full_header.index("会計区分")  # 列25
    idx_amount_detail = spec.full_header.index("当初予算")  # 列28(合計ではない、会計区分ごとの明細行)

    agg_total = 0
    agg_rows = 0
    detail_by_kind: dict[str, int] = {}
    detail_rows = 0
    for row in rs_mod._group_rows("budget_summary", rs_paths["budget_summary"]):
        if row[idx_ministry] != args.ministry:
            continue
        if row[idx_fy] != args.fiscal_year or row[idx_byear] != args.fiscal_year:
            continue
        kind = row[idx_account_kind]
        if not kind:
            # 会計区分が空 = 集計行(列14の当初予算(合計)を持つ)
            amt = row[idx_amount_agg]
            if amt:
                agg_total += int(amt)
                agg_rows += 1
            continue
        # 会計区分が非空 = 明細行(列28の当初予算を持つ)
        amt = row[idx_amount_detail]
        if amt:
            detail_by_kind[kind] = detail_by_kind.get(kind, 0) + int(amt)
            detail_rows += 1

    print("=" * 78)
    print(f"B34裏付け確認: {args.ministry} FY{args.fiscal_year} budget_summaryの会計区分別明細")
    print("=" * 78)
    print(f"集計行(会計区分が空): {agg_rows} 行 / 合計 {agg_total:,} 円")
    print(f"明細行(会計区分が非空): {detail_rows} 行")
    for kind, amt in sorted(detail_by_kind.items(), key=lambda kv: -kv[1]):
        pct = amt / agg_total * 100 if agg_total else 0
        print(f"  {kind}: {amt:,} 円 ({pct:.1f}%)")
    detail_total = sum(detail_by_kind.values())
    print(f"明細行の合計: {detail_total:,} 円")
    print(f"集計行の合計と明細行の合計が一致するか: {agg_total == detail_total}")
    if agg_total != detail_total:
        print("**不一致: 「当初予算(合計)」が会計区分別の明細の単純合計ではない**")


if __name__ == "__main__":
    main()
