#!/usr/bin/env bash
# 取得済みスナップショットから成果物までを1コマンドで作る。
# インデックス構築はコンテナ側で行い、実行環境のCPUを使わない
# (バーストVMのクレジット枯渇対策。設計書§6.3)
set -euo pipefail

: "${JENA_VERSION:?JENA_VERSION を .env に設定する}"
FETCHED_ON="${1:?使い方: scripts/build.sh YYYY-MM-DD}"

OUT="data/artifact/${FETCHED_ON}"
mkdir -p "$OUT"

echo "== スキーマ生成 =="
./scripts/generate-schema.sh

echo "== パイプライン実行(検証を含む) =="
uv run python -c "
import datetime, json, pathlib
from jgkg import pipeline
report = pipeline.run(datetime.date.fromisoformat('${FETCHED_ON}'), pathlib.Path('${OUT}'))
pathlib.Path('${OUT}/pipeline-report.json').write_text(
    report.model_dump_json(indent=2), encoding='utf-8')
print(report.model_dump_json(indent=2))
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
    sources={'houjin-bangou': '${FETCHED_ON}'},
    graphs=report['graphs'],
)
build.write_manifest(m, out / 'manifest.json')
print(m.model_dump_json(indent=2))
"

echo "完了: ${OUT}"
