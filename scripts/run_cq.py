"""Task 11 Step 5 / 完了条件A: CQを**実エンドポイント**で全実行する。

設計書§1.2完了条件(A)は「CQに答えられないオントロジーは不合格」である。
`tests/test_competency_questions_phase1.py` は合成fixtureに対して
rdflib のインメモリ実行で答えを確認しているが、それは
**(a) 実データで非0の答えが返ること**と
**(b) Fuseki(TDB2)でも同じクエリが動くこと**の証拠にはならない
(rdflibとJenaのSPARQL実装は別物であり、fixtureに無い値は答えられない)。
このスクリプトはその2つだけを埋める。

**0件を成功にしない。** CQが実データに答えられているかを見るのが目的なので、
1件も返らないCQがあれば非0で終了する(`--allow-empty` で明示的に緩められる。
「既定は止まる側」という設計書§6.3の作法に合わせる)。

出力: 各CQの行数と先頭N行(既定20)。**全行はJSONへ保存する**
(数万行になるCQ(cq09の法令ごとの解決状況など)は標準出力に全量を出すと
測定記録として読めなくなるため。保存先は --save-dir)。

**使い捨てにしない**(裁定B25)。標準出力は docs/measurements-phase1.md に
全量転記する。

使い方:
    uv run python scripts/run_cq.py
    uv run python scripts/run_cq.py --endpoint http://localhost:3030/kg/sparql
    uv run python scripts/run_cq.py --pattern 'cq*.rq' --head 5
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

DEFAULT_ENDPOINT = "http://localhost:3030/kg/sparql"
DEFAULT_QUERY_DIR = Path("queries/cq")
TIMEOUT = httpx.Timeout(30.0, read=300.0)


def _run_one(client: httpx.Client, endpoint: str, query: str) -> tuple[dict, float]:
    started = time.monotonic()
    resp = client.post(
        endpoint,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    elapsed = time.monotonic() - started
    resp.raise_for_status()
    return resp.json(), elapsed


def _row_text(row: dict, variables: list[str]) -> str:
    cells = []
    for v in variables:
        binding = row.get(v)
        cells.append("(未束縛)" if binding is None else binding["value"])
    return " | ".join(cells)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--query-dir", type=Path, default=DEFAULT_QUERY_DIR)
    parser.add_argument(
        "--pattern", default="cq*.rq",
        help="実行するクエリファイルのglob。既定はPhase 1のCQ10本(cq01〜cq10)",
    )
    parser.add_argument("--head", type=int, default=20, help="標準出力に出す先頭行数")
    parser.add_argument(
        "--save-dir", type=Path, default=None,
        help="全行をJSONで保存する先(既定は保存しない)",
    )
    parser.add_argument(
        "--allow-empty", action="store_true",
        help="0件のCQがあっても成功として終了する。**既定は失敗にする**",
    )
    args = parser.parse_args()

    paths = sorted(args.query_dir.glob(args.pattern))
    if not paths:
        print(f"クエリが1本も見つからない: {args.query_dir}/{args.pattern}", file=sys.stderr)
        return 2

    if args.save_dir is not None:
        args.save_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print(f"CQの実エンドポイント実行: {args.endpoint}")
    print(f"対象: {len(paths)} 本({args.query_dir}/{args.pattern})")
    print("=" * 78)

    empty: list[str] = []
    with httpx.Client(timeout=TIMEOUT) as client:
        for path in paths:
            query = path.read_text(encoding="utf-8")
            print()
            print("-" * 78)
            print(f"### {path.name}")
            try:
                result, elapsed = _run_one(client, args.endpoint, query)
            except httpx.HTTPStatusError as exc:
                print(f"**HTTPエラー**: {exc.response.status_code}")
                print(exc.response.text[:2000])
                empty.append(path.name)
                continue

            if args.save_dir is not None:
                (args.save_dir / f"{path.stem}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )

            if "boolean" in result:
                # ASKクエリ。**falseを0件と同じ扱いにする**(答えられていない)
                answer = result["boolean"]
                print(f"形式: ASK / 答え: {answer} / {elapsed:.3f} 秒")
                if not answer:
                    empty.append(path.name)
                continue

            variables = result["head"]["vars"]
            rows = result["results"]["bindings"]
            print(f"形式: SELECT / 変数: {variables}")
            print(f"行数: {len(rows)} / {elapsed:.3f} 秒")
            if not rows:
                print("**0件**")
                empty.append(path.name)
                continue
            print(" | ".join(variables))
            for row in rows[: args.head]:
                print(_row_text(row, variables))
            if len(rows) > args.head:
                print(f"... 以下 {len(rows) - args.head} 行省略"
                      + (f"(全行は {args.save_dir}/{path.stem}.json)"
                         if args.save_dir is not None else ""))

    print()
    print("=" * 78)
    if empty:
        print(f"**答えが返らなかったCQ: {len(empty)} 本** -> {empty}")
        if not args.allow_empty:
            print("完了条件A(CQに答えられること)を満たしていない")
            return 1
    else:
        print(f"全 {len(paths)} 本のCQが非0の答えを返した(完了条件A)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
