#!/usr/bin/env bash
# 取得済みスナップショットから成果物までを1コマンドで作る。
# インデックス構築はコンテナ側で行い、実行環境のCPUを使わない
# (バーストVMのクレジット枯渇対策。設計書§6.3)
set -euo pipefail

# .env を読み込む。**エラーメッセージが「.env に設定する」と案内しているのに、
# 読み込んでいなかった**(2026-08-23、実行系を初めて通したときに判明)。
# docker compose は .env を自動で読むが bash は読まない。このスクリプトは
# JENA_VERSION をシェル側でも使う(compose に渡す前に検査する)ので明示的に読む。
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

: "${JENA_VERSION:?JENA_VERSION を .env に設定する}"
FETCHED_ON="${1:?使い方: scripts/build.sh YYYY-MM-DD [--allow-partial] [--include-all-corporations]}"
shift

# 隔離が発生してもリリースを続けるか。既定は止まる(設計書§6.3のリリースゲート)
ALLOW_PARTIAL=False
# Task 8: 全法人(約581万件)をhoujin-bangou-allグラフとしてkg.nqに含めるか。
# 既定はFalse(触らない) — pipeline.run の include_all_corporations と同じ
# 既定値・同じ理由(O-11。Task 11がこのフラグを使う)
INCLUDE_ALL_CORPORATIONS=False
for arg in "$@"; do
  case "$arg" in
    --allow-partial)
      ALLOW_PARTIAL=True
      ;;
    --include-all-corporations)
      INCLUDE_ALL_CORPORATIONS=True
      ;;
    *)
      echo "不明な引数: $arg(使えるのは --allow-partial / --include-all-corporations のみ)" >&2
      exit 2
      ;;
  esac
done

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
    include_all_corporations=${INCLUDE_ALL_CORPORATIONS},
)
pathlib.Path('${OUT}/pipeline-report.json').write_text(
    report.model_dump_json(indent=2), encoding='utf-8')
print(report.model_dump_json(indent=2))
pipeline.enforce_release_gate(report, allow_partial=${ALLOW_PARTIAL})
"

echo "== TDB2インデックス構築 =="
# MSYS_NO_PATHCONV=1 が必要。**Windows の Git Bash / MSYS は `/work/...` のような
# POSIX風の絶対パス引数を Windows パスに書き換えてコンテナに渡す。**
# 実測(2026-08-23): /work/data/artifact/<日付>/kg.nq が
# `C:/Program Files/Git/work/data/artifact/<日付>/kg.nq` に化けて Can't read file で落ちた。
# **コンテナ内のパスなのでホスト側の変換をしてはならない。**
# cp932 や NTFS の予約文字と同じ、Windowsでしか出ない類型(設計書§11.1の再現性)。
MSYS_NO_PATHCONV=1 docker compose --profile tools run --rm jena-tools \
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
