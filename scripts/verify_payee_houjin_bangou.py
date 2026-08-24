"""Task 11修正ラウンド2 要修正4の再検証: payee_houjin_bangou を実際に構築して数える。

`docs/measurements-phase1.md` §2の「恒等式」は、レビュアが指摘した通り、
足し算(corporations_all + nonexistentのdistinct数)で作った数値を
`payee_houjin_bangou`(名指しした集合そのもの)の件数だと report していた。
`pipeline.py`が`payee_houjin_bangou`を構築する規則
(`{int(v) for row in rows for line in row.expenditures if (v :=
line.recipient_houjin_bangou) and v.isdigit()}`)をそのまま再現し、
実際に集合を作って数える(裁定B25: 測定は使い捨てにしない)。

**使い捨てにしない**。出力は docs/measurements-phase1.md に転記する。

使い方:
    uv run python scripts/verify_payee_houjin_bangou.py \
        --houjin-bangou 2026-08-23 --rs-system 2026-08-23
"""
import argparse
import datetime

from jgkg import lake, pipeline
from jgkg.transform import organization as org_mod
from jgkg.transform import rs as rs_mod

SENTINEL = "9999999999999"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--houjin-bangou", type=datetime.date.fromisoformat, required=True)
    parser.add_argument("--rs-system", type=datetime.date.fromisoformat, required=True)
    args = parser.parse_args()

    rs_paths = pipeline._rs_group_paths(args.rs_system)
    stats = rs_mod.RsParseStats()
    rows = list(rs_mod.parse_rs(rs_paths, stats=stats))

    # pipeline.py の payee_houjin_bangou 構築規則をそのまま再現する
    # (`pipeline.py`内の同名の集合構築式と一致させること)
    payee_houjin_bangou = {
        int(v)
        for row in rows
        for line in row.expenditures
        if (v := line.recipient_houjin_bangou) and v.isdigit()
    }

    print("=" * 78)
    print("payee_houjin_bangou の再構築(要修正4)")
    print("=" * 78)
    print(f"houjin-bangouスナップショット: {args.houjin_bangou.isoformat()}")
    print(f"rs-systemスナップショット    : {args.rs_system.isoformat()}")
    print(f"payee_houjin_bangou の distinct 件数: {len(payee_houjin_bangou)}")
    sentinel_in = int(SENTINEL) in payee_houjin_bangou
    print(f"センチネル({SENTINEL})がこの集合に入っているか: {sentinel_in}")

    snapshot_path = lake.path_of("houjin-bangou", args.houjin_bangou, "zenken.zip")
    existing = {
        int(o.houjin_bangou)
        for o in org_mod.parse_source(snapshot_path)
        if int(o.houjin_bangou) in payee_houjin_bangou
    }
    nonexistent = payee_houjin_bangou - existing - ({int(SENTINEL)} if sentinel_in else set())
    print(f"実在する(corporations_all相当)  : {len(existing)}")
    print(f"実在しない(センチネル除く。distinct): {len(nonexistent)}")
    total = len(existing) + len(nonexistent) + (1 if sentinel_in else 0)
    print(f"内訳の合計: {len(existing)} + {len(nonexistent)} + "
          f"{1 if sentinel_in else 0}(センチネル) = {total}")
    if total != len(payee_houjin_bangou):
        print(f"**不一致: 内訳の合計({total})がpayee_houjin_bangouの件数"
              f"({len(payee_houjin_bangou)})と一致しない**")
    else:
        print("内訳の合計とpayee_houjin_bangouの件数が一致した(恒等式が成立)")


if __name__ == "__main__":
    main()
