"""ビルドされた公開物(site/)の内容を、サーバを立てずに検査する(A-2)。

    uv run python scripts/check-site-build.py

**`scripts/verify-site.py`との違い。** verify-site.pyはHTTP越しに配信済みの
サイトを検査する(Content-Type・CORSなど、配信時の性質)。このスクリプトは
ビルド成果物をファイルシステムから直接検査するので、サーバもnode/wranglerも
要らず、コミット毎のCIに乗せられる(このセッションで実際に踏んだ欠陥――
law/budgetモジュールがビルド成果物に無かった・sitemapが9件で期待15件――は、
どちらも配信を再現しなくても捕まえられる)。

**循環検証にしない。** 3つの検査はいずれも、`_headers`/`sitemap.txt`の
実際のテキストと、`out_dir/def/`の実際のディレクトリ一覧という**2つの
独立した観測**(`src/jgkg/site.py`の`built_def_paths`/`headers_declared_paths`/
`sitemap_declared_paths`)を突き合わせるだけで、`build()`や`build_headers()`の
内部計算を検査の中で再利用しない――再利用すると「`build()`のバグを
`build()`自身の式で検査する」形になり、そのバグを原理的に見逃す。
`missing_paths()`は例外で、生成物(schema/generated/)という**別の入力**から
導出するので同じ懸念は無い(それでも`build-site.sh`が既にビルド時に
同じ検査を1回行っている――ここでの再検査は「ビルド後に改めて確認する」
独立した層として意図的に重複させている)。

**それぞれの検査が捕まえるもの/捕まえないもの**:

1. `missing_paths` — 生成物(OWL/SHACLの主語IRI)が要求するパスが
   ビルド成果物に無い(例: モジュールを追加したのにコピーが漏れた)。
   **捕まえないもの**: パスは揃っているが内容が壊れている場合
   (内容の正しさは`tests/test_site.py`の別のテストが見る)。
2. `_headers`の`/def/`パス集合とビルド成果物の実際のパス集合の不一致 —
   `_headers`が実在しないパスにturtleを名乗らせている(欠落パスへの
   誤ったContent-Type被せ)、または実在するパスに`_headers`のブロックが
   無い(そのパスがCloudflareの既定`text/html`に落ちる)。
3. sitemapの`/def/`パス集合とビルド成果物の実際のパス集合の不一致 —
   このセッションの実際の欠陥(sitemapがモジュール追加に追従せず9件の
   まま)そのもの。**件数の一致だけでなく集合そのものの一致を見る**
   (ブリーフは件数一致のみを求めていたが、`_headers`側で明示的に
   要求されている「件数一致は同数の別集合を通す」という同じ穴が
   sitemap側にも当然開くため、同じ基準に揃えた)。
"""
import argparse
import sys
from pathlib import Path

from jgkg import site

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", type=Path, default=Path("schema/generated"))
    parser.add_argument("--out-dir", type=Path, default=Path("site"))
    args = parser.parse_args(argv)

    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(("OK " if cond else "NG ") + label + (f"  ({detail})" if detail else ""))
        if not cond:
            failures.append(label)

    missing = site.missing_paths(args.generated_dir, args.out_dir)
    check(
        "生成物が要求するパスがすべてビルド成果物に存在する(missing_paths)",
        not missing,
        f"欠落: {sorted(missing)}" if missing else "",
    )

    built = site.built_def_paths(args.out_dir)
    check("ビルド成果物の/def/配下が空でない", bool(built), f"{len(built)} 件")

    headers = site.headers_declared_paths(args.out_dir)
    extra_in_headers = sorted(headers - built)
    missing_in_headers = sorted(built - headers)
    check(
        "_headers がturtleを与えるパスの集合が、ビルド成果物の実際のパス集合と一致する",
        headers == built,
        f"_headers 側のみ={extra_in_headers} / 実在のみ={missing_in_headers}"
        if headers != built
        else f"{len(headers)} 件",
    )

    sitemap = site.sitemap_declared_paths(args.out_dir)
    extra_in_sitemap = sorted(sitemap - built)
    missing_in_sitemap = sorted(built - sitemap)
    check(
        "sitemap が列挙する/def/パスの集合が、ビルド成果物の実際のパス集合と一致する",
        sitemap == built,
        f"sitemap 側のみ={extra_in_sitemap} / 実在のみ={missing_in_sitemap}"
        if sitemap != built
        else f"{len(sitemap)} 件",
    )

    print()
    if failures:
        print(f"失敗 {len(failures)} 件:")
        for f in failures:
            print("  -", f)
        return 1
    print("すべて合格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
