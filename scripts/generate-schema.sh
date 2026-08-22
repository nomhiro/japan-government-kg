#!/usr/bin/env bash
# LinkML から OWL / SHACL / Pydantic を生成する。
# --no-use-native-uris は設計書§10で必須(OWLとSHACLが同じIRIを語ることを保証する)。
# 日本語の言語タグは linkml==1.11.1 のCLIに該当オプションが無いため後処理で付ける。
set -euo pipefail

# Windowsのコンソールコードページ(cp932)でstdoutが開かれると、リダイレクト先の
# Turtleが不正なUTF-8になりrdflibが読めない。どの環境でも同じ生成物になるよう固定する
# (設計書§11.1の再現性要件)
export PYTHONUTF8=1

OUT=schema/generated
mkdir -p "$OUT"

# **モジュール名を列挙しない。** ここに書き忘れると、そのモジュールの生成物が
# 作られず(あるいは古いまま残り)、検証が静かに素通しになる。schema/*.yaml が
# 対象の定義そのものである(レビューI6と同じ型の欠陥をここでも避ける)
for src in schema/*.yaml; do
  [ -f "$src" ] || continue
  module="$(basename "$src" .yaml)"
  echo "generating from ${src}"
  uv run gen-owl --no-use-native-uris "$src" > "${OUT}/${module}.owl.ttl"
  uv run gen-shacl "$src" > "${OUT}/${module}.shacl.ttl"
  uv run gen-pydantic "$src" > "${OUT}/${module}_models.py"
  uv run python -m jgkg.schema_lang "${OUT}/${module}.owl.ttl" "${OUT}/${module}.shacl.ttl"
done

echo "generated files:"
ls -1 "$OUT"
