"""配信されたオントロジーを、RDFの利用者の立場から検証する。

    uv run python scripts/verify-site.py                       # ローカル再現(wrangler)
    uv run python scripts/verify-site.py https://jgkg.norr-tech.com   # 公開先
    uv run python scripts/verify-site.py https://jgkg.norr-tech.com --attempts 6 --delay-seconds 10

**「ファイルが置けたか」ではなく「利用者が解釈できるか」、かつ「配信物が
いま手元でビルドした内容と同じか」を検査する。** 比較ロジックの本体は
`jgkg.site_verify`にある(このファイルはCLIの薄い皮でしかない——理由は
そのモジュールのdocstring参照)。

**リトライ(`--attempts`)は既定で無効(1回)。** ローカルでの実行は
壊れていれば即座に赤くなってほしいため。CIが直前のpushの配信伝播待ちを
吸収したいときは明示的に`--attempts 6 --delay-seconds 10`のように渡す
(`.github/workflows/site-check.yml`参照)。

デプロイ前(ローカル再現)とデプロイ後(公開先)で同じものを流せるようにしてある。
"""
import argparse
import sys
from pathlib import Path

import httpx

from jgkg import site_verify

# **出力を環境非依存にする。** Windowsでこのスクリプトの出力をパイプすると、
# Pythonがロケールのコードページ(cp932)で書くため日本語が文字化けする。
# 実際に利用者の手元で読めない出力が出た(2026-08-23)。設計書§5.7が
# 生成物について定めた「生成は環境非依存にする」を、出力にも適用する。
# 呼び出し側に PYTHONUTF8=1 を要求せず、スクリプト側で閉じる。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_ORIGIN = "http://localhost:8788"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", nargs="?", default=DEFAULT_ORIGIN)
    parser.add_argument("--out-dir", type=Path, default=Path("site"))
    parser.add_argument("--generated-dir", type=Path, default=Path("schema/generated"))
    parser.add_argument(
        "--attempts", type=int, default=1,
        help="配信伝播待ちの偽陽性を吸収するための試行回数(既定1=リトライ無し)",
    )
    parser.add_argument(
        "--delay-seconds", type=float, default=10.0,
        help="リトライ間隔(秒。--attemptsが1のときは使われない)",
    )
    args = parser.parse_args(argv[1:])
    origin = args.origin.rstrip("/")
    print(f"検証先: {origin}\n")

    def on_retry(attempt: int, attempts: int) -> None:
        print(f"検査が通らない。{args.delay_seconds:.0f}秒待って再試行する({attempt}/{attempts})")

    with httpx.Client(timeout=20.0) as client:
        report = site_verify.run_all_checks_with_retries(
            origin, args.out_dir, args.generated_dir, client,
            attempts=args.attempts, delay_seconds=args.delay_seconds, on_retry=on_retry,
        )

    for r in report.results:
        print(("OK " if r.ok else "NG ") + r.label + (f"  ({r.detail})" if r.detail else ""))

    print()
    if not report.ok:
        failures = report.failures
        print(f"失敗 {len(failures)} 件:")
        for f in failures:
            print("  -", f.label)
        return 1
    print("すべて合格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
