#!/usr/bin/env bash
# 取得段(コネクタ)を呼ぶ薄いラッパ。引数の解釈は python -m jgkg.fetch が行う
# (build.sh/pipeline.pyと同じ分離: シェル側はオーケストレーションだけ)。
#
# 使い方:
#   scripts/fetch.sh --source egov-law
#   scripts/fetch.sh --source rs-system --year 2025
#   scripts/fetch.sh --source houjin-bangou
#   scripts/fetch.sh --source egov-law --source rs-system --year 2025
#
# 詳しい使い方: uv run python -m jgkg.fetch --help
set -euo pipefail

# .env を読み込む(JGKG_HOUJIN_BANGOU_URL 等)。docker compose とは違い bash は
# .env を自動で読まない(build.sh/serve.shと同じ理由。2026-08-23判明)。
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# Windows上で日本語の標準出力が文字化けしないようにする
# (build.sh/generate-schema.sh/build-site.shと同じ対応)
export PYTHONUTF8=1

uv run python -m jgkg.fetch "$@"
