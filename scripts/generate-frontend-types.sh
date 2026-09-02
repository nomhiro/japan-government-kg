#!/usr/bin/env bash
# フロントエンド(D-5)が使う2種類の生成物を作り直す。
#
#   1. frontend/openapi.json           ← FastAPIのOpenAPIスキーマ(scripts/export-openapi.py)
#   2. frontend/src/api/openapi-types.ts ← 1から生成するTypeScript型(openapi-typescript)
#   3. frontend/src/generated/labels.json ← オントロジーの日本語表示名(裁定B78。scripts/export-frontend-labels.py)
#
# **手書きしない(D-5ブリーフ設計2・裁定B78)。** どちらもAPI応答の形・
# オントロジーの内容から機械的に導出する——`schema/generated/`と同じ方針で
# 生成物をコミットし、CIは再生成して差分が無いことを確認する
# (scripts/generate-schema.shのCI検査と同じ形)。
set -euo pipefail

export PYTHONUTF8=1

echo "== OpenAPIスキーマを書き出す(Fusekiは不要。app.openapi()だけを呼ぶ) =="
uv run python scripts/export-openapi.py

echo "== TypeScriptの型を生成する =="
(cd frontend && npx --yes openapi-typescript openapi.json -o src/api/openapi-types.ts)

echo "== オントロジーの日本語表示名(裁定B78)を書き出す =="
uv run python scripts/export-frontend-labels.py
