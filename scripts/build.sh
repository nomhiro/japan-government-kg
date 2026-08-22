#!/usr/bin/env bash
# 取得済みスナップショットから成果物までを1コマンドで作る。
# インデックス構築はコンテナ側で行い、実行環境のCPUを使わない
# (バーストVMのクレジット枯渇対策。設計書§6.3)
set -euo pipefail

: "${JENA_VERSION:?JENA_VERSION を .env に設定する}"
FETCHED_ON="${1:?使い方: scripts/build.sh YYYY-MM-DD [--allow-partial]}"

# 隔離が発生してもリリースを続けるか。既定は止まる(設計書§6.3のリリースゲート)
ALLOW_PARTIAL=False
if [ "${2:-}" = "--allow-partial" ]; then
  ALLOW_PARTIAL=True
elif [ -n "${2:-}" ]; then
  echo "不明な引数: $2(使えるのは --allow-partial のみ)" >&2
  exit 2
fi

OUT="data/artifact/${FETCHED_ON}"
mkdir -p "$OUT"

echo "== スキーマ生成 =="
./scripts/generate-schema.sh

echo "== パイプライン実行(検証を含む) =="
# 隔離が起きたら enforce_release_gate が例外を投げ、set -e で以降のインデックス
# 構築・manifest作成に進まない。**レポートは例外の前に書く**(何が落ちたかを
# 人が読めるようにするため)
uv run python -c "
import datetime, json, pathlib
from jgkg import pipeline
# **取得して来るソースの日付だけを渡す。** リポジトリにコミットした参照表
# (ministry-codes)の日付は sources.py の recorded_on から取られる。
# 以前は法人番号の取得日を参照表にも流用しており、CQ P0-4 が根拠のない日付を
# 答えていた(レビューI2)
report = pipeline.run(
    {'houjin-bangou': datetime.date.fromisoformat('${FETCHED_ON}')},
    pathlib.Path('${OUT}'),
)
pathlib.Path('${OUT}/pipeline-report.json').write_text(
    report.model_dump_json(indent=2), encoding='utf-8')
print(report.model_dump_json(indent=2))
pipeline.enforce_release_gate(report, allow_partial=${ALLOW_PARTIAL})
"

echo "== TDB2インデックス構築 =="
docker compose --profile tools run --rm jena-tools \
  tdb2.tdbloader --loc "/work/${OUT}/tdb2" "/work/${OUT}/kg.nq"

echo "== 成果物のtar.gz化とmanifest =="
tar -czf "${OUT}/tdb2.tar.gz" -C "$OUT" tdb2
uv run python -c "
import json, pathlib
from jgkg import build
out = pathlib.Path('${OUT}')
report = json.loads((out / 'pipeline-report.json').read_text(encoding='utf-8'))
m = build.build_manifest(
    nquads=out / 'kg.nq',
    tarball=out / 'tdb2.tar.gz',
    jena_version='${JENA_VERSION}',
    release='${FETCHED_ON}',
    # **手書きしない。** 以前は {'houjin-bangou': FETCHED_ON} と決め打ちで、
    # KGに入っている ministry-codes グラフが manifest に現れなかった
    sources=report['sources'],
    graphs=report['graphs'],
    # 隔離されたソースは sources に載らない代わりにここに出る(--allow-partial 時)
    quarantined_sources=report['quarantined_sources'],
)
build.write_manifest(m, out / 'manifest.json')
print(m.model_dump_json(indent=2))
"

echo "完了: ${OUT}"
