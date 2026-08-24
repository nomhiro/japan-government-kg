#!/usr/bin/env bash
# 取得済みスナップショットから成果物までを1コマンドで作る。
# インデックス構築はコンテナ側で行い、実行環境のCPUを使わない
# (バーストVMのクレジット枯渇対策。設計書§6.3)
#
# 使い方(Task 11 / B28 で全ソース対応にした):
#   scripts/build.sh --source houjin-bangou=2026-08-23 \
#                    --source egov-law=2026-08-24 \
#                    --source rs-system=2026-08-23 \
#                    --include-all-corporations \
#                    [--previous-release 2026-08-23] \
#                    [--out-dir data/artifact/2026-08-24] \
#                    [--allow-partial] [--fail-on-stale]
#
# **以前は位置引数1つ(取得日)しか受けず、その日付を houjin-bangou の取得日
# として決め打ちしていた。** つまり egov-law + rs-system を含むリリースを
# このスクリプトでは作れなかった(Task 10 が pipeline.run に結線した経路に、
# 実行系からの入口が無かった)。ソースごとに取得日が違うことは run() の
# 第一の設計前提(§6.4 の更新頻度表は monthly/annual/ondemand と別)なので、
# その前提をそのまま渡せる形にする。引数の解釈とその検査は
# `python -m jgkg.pipeline`(コードとしてテストできる場所)に置き、
# ここはオーケストレーションだけを行う。
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

usage() {
  cat >&2 <<'USAGE'
使い方: scripts/build.sh --source <ID>=<YYYY-MM-DD> [--source ...] [オプション]

  --source ID=YYYY-MM-DD     ソースと取得日。**複数回指定する。** 少なくとも
                             houjin-bangou は必要(縦スライスの土台)
  --previous-release DATE    前リリースの日付。差分検出(carry-over)を有効にする
  --include-all-corporations 全法人(約581万件)を含める。
                             **rs-system を含むなら必須**(裁定B17懸念2/B18)
  --allow-partial            隔離が起きてもリリースを続ける(既定は止まる)
  --fail-on-stale            鮮度監視で陳腐化があればビルドを始めずに止める
  --out-dir PATH             成果物の出力先。既定は data/artifact/<最新の取得日>
                             (= pipeline が付けるリリースIDと同じ)。全ソース
                             据え置きの検証のように、リリースIDが前リリースと
                             同じになる実行を別ディレクトリへ出すときだけ渡す
USAGE
}

SOURCE_ARGS=()
PIPELINE_FLAGS=()
OUT=""
FAIL_ON_STALE=0
LATEST_DATE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --source)
      [ $# -ge 2 ] || { echo "--source に値が無い" >&2; usage; exit 2; }
      SOURCE_ARGS+=(--source "$2")
      # 出力先の既定値に使う「最新の取得日」。ISO 8601 は辞書順=日付順なので
      # 文字列比較で足りる(pipeline 側の release=max(fetched_on.values()) と
      # 同じ値になる。ズレると manifest の release と成果物ディレクトリ名が
      # 食い違うため、ここは推測ではなく同じ規則に揃える)
      case "$2" in
        *=*) d="${2#*=}" ;;
        *) echo "--source の形式が違う: $2(<ID>=<YYYY-MM-DD>)" >&2; exit 2 ;;
      esac
      if [ -z "$LATEST_DATE" ] || [ "$d" \> "$LATEST_DATE" ]; then
        LATEST_DATE="$d"
      fi
      shift 2
      ;;
    --previous-release)
      [ $# -ge 2 ] || { echo "--previous-release に値が無い" >&2; usage; exit 2; }
      PIPELINE_FLAGS+=(--previous-release "$2")
      shift 2
      ;;
    --out-dir)
      [ $# -ge 2 ] || { echo "--out-dir に値が無い" >&2; usage; exit 2; }
      OUT="$2"
      shift 2
      ;;
    --include-all-corporations)
      PIPELINE_FLAGS+=(--include-all-corporations)
      shift
      ;;
    --allow-partial)
      PIPELINE_FLAGS+=(--allow-partial)
      shift
      ;;
    --fail-on-stale)
      FAIL_ON_STALE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "不明な引数: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ ${#SOURCE_ARGS[@]} -eq 0 ]; then
  echo "--source が1つも渡されていない" >&2
  usage
  exit 2
fi

if [ -z "$OUT" ]; then
  OUT="data/artifact/${LATEST_DATE}"
fi
mkdir -p "$OUT"

# 段ごとの所要時間。**Task 11 の実測(Step 4「tdbloader の時間、パイプライン
# 全体の時間」)を使い捨てのストップウォッチで測らないため**(裁定B25: 測定は
# scripts/ にコミットする)、リリースを作るたびに毎回同じ形で出す。
# `date +%s` は秒精度で足りる(分単位の作業の測定であり、ミリ秒は要らない)
BUILD_STARTED_AT=$(date +%s)
_phase_start=$BUILD_STARTED_AT
phase_done() {
  local now
  now=$(date +%s)
  echo "[所要] $1: $((now - _phase_start)) 秒(開始からの累計 $((now - BUILD_STARTED_AT)) 秒)"
  _phase_start=$now
}

echo "== 鮮度監視(I3/F-5と同型の「消費者の無い記録」を作らないため、必ず1回呼ぶ) =="
# **記録するだけの関数を作って呼ばないことをしない。** freshness.report() の
# 唯一の実行系の消費者がここ。既定では止めない(鮮度は成果物の正しさの条件
# ではない)が、リリースを作るたびに必ず標準出力に出す
if [ "$FAIL_ON_STALE" -eq 1 ]; then
  uv run python -m jgkg.freshness --fail-on-stale
else
  uv run python -m jgkg.freshness
fi
phase_done "鮮度監視"

echo "== スキーマ生成 =="
./scripts/generate-schema.sh
phase_done "スキーマ生成"

echo "== パイプライン実行(検証を含む) =="
# 隔離が起きたら enforce_release_gate が例外を投げ、set -e で以降のインデックス
# 構築・manifest作成に進まない。**レポートは例外の前に書く**(何が落ちたかを
# 人が読めるようにするため。順序の保証は jgkg.pipeline.main の中にある)
uv run python -m jgkg.pipeline "${SOURCE_ARGS[@]}" --out-dir "$OUT" "${PIPELINE_FLAGS[@]+"${PIPELINE_FLAGS[@]}"}"
phase_done "パイプライン(取得済みスナップショット→kg.nq、検証含む)"

echo "== TDB2インデックス構築 =="
# **既存の tdb2 ディレクトリを必ず消してから読み込む。** tdb2.tdbloader は
# 「その場所にあるデータベースへ読み込む」ツールであって、置き換えるツールでは
# ない。同じリリースディレクトリを作り直すと(Task 11 が 2026-08-23 の
# Phase 0 リリースを再ビルドしたときに実際に起きる状況)、前の世代のトリプルが
# 残ったまま新しい kg.nq が足され、**成果物が kg.nq と一致しなくなる**
# (manifest の sha256 は kg.nq と tdb2.tar.gz を別々に記録するので、この
# 食い違いは照合では捕まらない)。tar.gz も同様に消す — 残っていると
# tar が上書きするので実害は無いが、失敗した実行の残骸を次の実行の
# 成果物と混ぜないため揃えて消す
if [ -e "${OUT}/tdb2" ]; then
  echo "既存の ${OUT}/tdb2 を削除する(tdbloader は追記であって置換ではない)"
  rm -rf "${OUT}/tdb2"
fi
rm -f "${OUT}/tdb2.tar.gz"
# MSYS_NO_PATHCONV=1 が必要。**Windows の Git Bash / MSYS は `/work/...` のような
# POSIX風の絶対パス引数を Windows パスに書き換えてコンテナに渡す。**
# 実測(2026-08-23): /work/data/artifact/<日付>/kg.nq が
# `C:/Program Files/Git/work/data/artifact/<日付>/kg.nq` に化けて Can't read file で落ちた。
# **コンテナ内のパスなのでホスト側の変換をしてはならない。**
# cp932 や NTFS の予約文字と同じ、Windowsでしか出ない類型(設計書§11.1の再現性)。
MSYS_NO_PATHCONV=1 docker compose --profile tools run --rm jena-tools \
  tdb2.tdbloader --loc "/work/${OUT}/tdb2" "/work/${OUT}/kg.nq"
phase_done "tdbloader(TDB2インデックス構築)"

echo "== 成果物のtar.gz化とmanifest =="
tar -czf "${OUT}/tdb2.tar.gz" -C "$OUT" tdb2
phase_done "tar.gz化"
JGKG_OUT="$OUT" JGKG_JENA_VERSION_FOR_MANIFEST="$JENA_VERSION" uv run python -c "
import json, os, pathlib
from jgkg import build, pipeline
out = pathlib.Path(os.environ['JGKG_OUT'])
report = json.loads((out / pipeline.REPORT_NAME).read_text(encoding='utf-8'))
m = build.build_manifest(
    nquads=out / 'kg.nq',
    tarball=out / 'tdb2.tar.gz',
    jena_version=os.environ['JGKG_JENA_VERSION_FOR_MANIFEST'],
    # **手書きしない。** リリースIDは pipeline が fetched_on から決める
    # (max(取得日))。シェル側で別に組み立てると、--out-dir を渡した実行で
    # ディレクトリ名とリリースIDが食い違ったまま manifest に焼き込まれる
    release=report['release'],
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

phase_done "manifest作成"
echo "完了: ${OUT}(総所要 $(( $(date +%s) - BUILD_STARTED_AT )) 秒)"
