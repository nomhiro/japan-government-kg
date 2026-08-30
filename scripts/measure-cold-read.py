"""配備先の構成での索引の初回読みを測る(裁定B71)。

**裁定B55・B61・B62が3回繰り越した数字を出すためのスクリプト。**

なぜ開発機で測れなかったか: 真のコールドキャッシュが必要で、
開発機では `wsl --shutdown` かVM内の `drop_caches` を要し、他の並行ジョブを
巻き込む。`docker restart` では足りない(VMのページキャッシュが残る)。

**GitHub Actions のランナーは真にコールドである**: 毎回新しい仮想マシンで、
ダウンロードしたばかりのファイルに対してページキャッシュが空であり、
**実Linuxファイルシステム(ext4。バインドマウントではない)**である。

**測るものを4段に分ける(裁定B55の「1回で結論しない」に従い各3回)**:

1. **Fusekiが応答を返すまで** —— D-1の「コールドスタート14秒」がこれで、
   **索引のページインを含んでいなかった**(裁定B55)。同じ誤りを繰り返さない
   ために、ここを独立に測る
2. **ラベル領域**(`warm_up()` = `search_entities`。裁定B60が示したAPIの
   実際の初回コスト)
3. **支出領域**(`legacy-cq06-optional-inference.rq`。§19.3が175.250秒を
   測った領域。**公開リリースは`recipientMatchCategory`を持たないため
   新cq06ではなく旧クエリを使う** —— 裁定B68)
4. **エンティティ詳細**(1エンティティ分。属性と関係の索引に触る)

**この測定の限界を出力に明記する**: ランナーのディスクはSSDであり、
配備先が同等かは別の問題である。言えるのは
「**このランナーのFSで、この索引に対して、初回読みはN秒だった**」まで。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from jgkg.api.kgclient import RemoteKGClient
from jgkg.api.queries import get_entity_detail, search_entities
from jgkg.api.warmup import warm_up
from jgkg.config import get_settings

#: 支出領域を触るクエリ。**手書きしない**——リポジトリにある独立オラクルを読む
#: (裁定B68: 公開リリースは`recipientMatchCategory`を持たないので新cq06は
#: 0件で短絡しうる。旧クエリはOPTIONAL推論で支出領域を実際に走る)
LEGACY_CQ06 = REPO_ROOT / "queries" / "cq" / "legacy-cq06-optional-inference.rq"


def _wait_until_ready(base_url: str, timeout_s: float) -> float | None:
    """Fusekiが応答を返すまでの秒数。**索引のページインは含まない。**"""
    started = time.monotonic()
    deadline = started + timeout_s
    while time.monotonic() < deadline:
        # 起動待ちなので理由を問わず再試行する(接続拒否・タイムアウト・
        # 起動途中の500 —— どれも「まだ起動していない」の現れ方に過ぎない)
        with contextlib.suppress(Exception):
            r = httpx.get(f"{base_url}/$/ping", timeout=5)
            if r.status_code == 200:
                return time.monotonic() - started
        time.sleep(0.5)
    return None


def _timed(label: str, fn, repeats: int) -> list[tuple[float, str]]:
    """同じ処理を`repeats`回測る(裁定B55: 1回で結論してはいけない)。"""
    out: list[tuple[float, str]] = []
    for i in range(repeats):
        t0 = time.monotonic()
        try:
            note = fn() or ""
        except Exception as exc:  # noqa: BLE001 - 失敗も測定結果として記録する
            note = f"**失敗**: {type(exc).__name__}: {exc}"
        out.append((time.monotonic() - t0, str(note)))
        print(f"  {label} {i + 1}回目: {out[-1][0]:8.3f} 秒  {out[-1][1]}", flush=True)
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", default="http://localhost:3030/kg/sparql")
    ap.add_argument("--base-url", default="http://localhost:3030")
    # **ベースURIを直書きしない**(`config.py`経由。base_uri --check の対象)
    ap.add_argument("--base-uri", default=None)
    ap.add_argument(
        "--manifest",
        default=None,
        help="配備した成果物の manifest.json。**データセットの同一性を検査する**"
        "(観察O16。渡さないと検査せず警告だけ出す)",
    )
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--startup-timeout", type=float, default=300.0)
    args = ap.parse_args(argv)
    base_uri = args.base_uri or get_settings().base_uri

    print("=== 1. Fusekiが応答を返すまで(索引のページインを含まない)===", flush=True)
    ready = _wait_until_ready(args.base_url, args.startup_timeout)
    if ready is None:
        print(f"Fusekiが{args.startup_timeout}秒で応答しなかった", file=sys.stderr)
        return 2
    print(f"  {ready:8.3f} 秒", flush=True)

    client = RemoteKGClient(args.endpoint)

    # **データセットの同一性を確認する(観察O16の統制)。**
    # 「接続できた」は「正しいデータセットに接続できた」ではない ——
    # 2026-08-30、別プロジェクトのFusekiがポート3030を保持していた。
    # 形が違ったので落ちたが、同じ形で別のデータを返す構成なら
    # **偽の数字が記録に入っていた。**
    #
    # **そして「印字する」は「検査する」ではない。** manifestの`triple_count`と
    # 突き合わせて、違えばここで止める(期待値を手書きしない——配備段が
    # 置いたmanifestから読む)。
    quads = client.query("SELECT (COUNT(*) AS ?c) WHERE { GRAPH ?g { ?s ?p ?o } }")
    graphs = client.query("SELECT (COUNT(DISTINCT ?g) AS ?c) WHERE { GRAPH ?g { ?s ?p ?o } }")
    quad_count = quads[0]["c"].value if quads else "?"
    graph_count = graphs[0]["c"].value if graphs else "?"
    print(f"\nデータセット: {quad_count} クアッド / {graph_count} 名前付きグラフ", flush=True)

    manifest_path = Path(args.manifest) if args.manifest else None
    if manifest_path is None:
        print(
            "  **警告: --manifest が無いのでデータセットの同一性を検査していない。**"
            " 測った数字を記録に使うなら --manifest を渡すこと(観察O16)",
            flush=True,
        )
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # 裁定B58: `triple_count` という欄名でクアッド数を持っている
        expected = manifest.get("triple_count")
        print(f"  manifest: release={manifest.get('release')} triple_count={expected}", flush=True)
        if str(expected) != str(quad_count):
            print(
                f"**中止: 期待と違うデータセットである**"
                f"(manifest {expected} ≠ 実測 {quad_count})。"
                f"ここで測った数字は記録しない。",
                file=sys.stderr,
            )
            return 3
        print("  **確認: manifestと一致する。測定を続けてよい。**", flush=True)

    print(
        "\n=== 2. ラベル領域(warm_up = search_entities。裁定B60)===",
        flush=True,
    )
    label = _timed("ラベル領域", lambda: None if warm_up(client, base_uri) else "温めが失敗", args.repeats)

    print("\n=== 3. 支出領域(legacy-cq06。§19.3が175.250秒を測った領域)===", flush=True)
    cq06 = LEGACY_CQ06.read_text(encoding="utf-8").replace(
        "https://jgkg.norr-tech.com", base_uri
    )
    expenditure = _timed(
        "支出領域", lambda: f"{len(client.query(cq06))} 行", args.repeats
    )

    print("\n=== 4. エンティティ詳細(1エンティティ分)===", flush=True)
    hits = search_entities(client, base_uri, "省", 1)
    if hits.results:
        target = hits.results[0].id_path
        detail = _timed(
            "エンティティ詳細",
            lambda: (
                f"{len(d.relationships)} 関係グループ"
                if (d := get_entity_detail(client, base_uri, target, 50))
                else "None"
            ),
            args.repeats,
        )
    else:
        print("  検索が0件で対象を選べなかった", flush=True)
        detail = []

    rows = [
        ("Fusekiが応答を返すまで", [(ready, "索引のページインを含まない")]),
        ("ラベル領域(APIの初回リクエスト)", label),
        ("支出領域(§19.3と同じ領域)", expenditure),
        ("エンティティ詳細", detail),
    ]
    lines = [
        "## 配備先の構成での索引の初回読み(裁定B71)",
        "",
        f"- データセット: **{quad_count} クアッド** / {graph_count} 名前付きグラフ",
        (
            f"- 実行環境: `{os.environ.get('RUNNER_OS', '(不明)')}` / "
            f"ランナー `{os.environ.get('RUNNER_NAME', '(不明)')}`"
        ),
        "",
        "| 段 | 1回目(コールド) | 2回目 | 3回目 |",
        "|---|---|---|---|",
    ]
    for name, measured in rows:
        cells = [f"{t:.3f} 秒" for t, _ in measured[:3]]
        cells += ["—"] * (3 - len(cells))
        lines.append(f"| {name} | **{cells[0]}** | {cells[1]} | {cells[2]} |")
    lines += [
        "",
        "### この測定の限界(明記する)",
        "",
        "- **ランナーのディスクはSSDであり、配備先が同等かは別の問題である。**",
        "  言えるのは「**このランナーのFSで、この索引に対して、初回読みはN秒だった**」まで。",
        "- 段1(Fusekiが応答を返すまで)は**索引のページインを含まない** ——",
        "  D-1の「コールドスタート14秒」がこれで、裁定B55がその不足を指摘した。",
        "- 開発機の数字(§19.3の175.250秒・§20.1の111.219秒・§20の142.234秒)は",
        "  **Windowsバインドマウント越し**であり、この表と直接比較してはならない",
        "  (裁定B62。発見7の倍率は書き込みの測定なので読み取りに転用できない)。",
    ]
    summary = "\n".join(lines)
    print("\n" + summary, flush=True)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8") as f:
            f.write(summary + "\n")
        print("\n(GITHUB_STEP_SUMMARY に書き出した)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
