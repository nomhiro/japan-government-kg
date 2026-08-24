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
#                    --corporations-scope payees \
#                    [--previous-release 2026-08-23] \
#                    [--out-dir data/artifact/2026-08-24-payees] \
#                    [--allow-overwrite] \
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

# Task 11修正ラウンド3(項目2)。付けずにWindows上で直接実行すると、
# 標準出力の日本語(鮮度監視・スキーマ生成・パイプラインの各段の出力)が
# プラットフォームの既定コードページ(UTF-8でない)で解釈されて文字化けする
# (動作自体には影響しないが、運用時にログが読めない。scripts/serve.shの
# 同種の修正〔修正ラウンド2〕で「build.shは対応済み」と誤って記載していたが、
# 実際には対応していなかった——このスクリプトの中の複数の`uv run python`
# 呼び出し全てに効かせるため、個別のコマンドに付けるのではなくここで
# exportする)
export PYTHONUTF8=1

: "${JENA_VERSION:?JENA_VERSION を .env に設定する}"

usage() {
  cat >&2 <<'USAGE'
使い方: scripts/build.sh --source <ID>=<YYYY-MM-DD> [--source ...] [オプション]

  --source ID=YYYY-MM-DD     ソースと取得日。**複数回指定する。** 少なくとも
                             houjin-bangou は必要(縦スライスの土台)
  --previous-release NAME    前リリースの識別子(成果物ディレクトリのbasename。
                             例: 2026-08-24、または2026-08-24-payeesのような
                             非ISO形式の名前も可。Ruling B31修正ラウンド3で
                             日付形式限定を解消した)。差分検出(carry-over)を
                             有効にする
  --include-all-corporations 法人グラフを含める(範囲は --corporations-scope で選ぶ)。
                             **rs-system を含むなら必須**(裁定B17懸念2/B18)
  --corporations-scope SCOPE all(既定)または payees。payeesは支出先として実際に
                             登場する法人に限る(Ruling B30。約19,000件・
                             TDB2実サイズ429MiB=8GiBの5.2%。修正ラウンド2で
                             旧「232MiB」という数字が別の見積り(選択肢A、
                             未使用)からの混入だったと判明し訂正した——
                             docs/measurements-phase1.md参照。
                             all=全法人約581万件・13.8GiB。rs-systemを含む
                             リリースでのみ payees を指定できる)
  --allow-partial            隔離が起きてもリリースを続ける(既定は止まる)
  --fail-on-stale            鮮度監視で陳腐化があればビルドを始めずに止める
  --out-dir PATH             成果物の出力先。既定は data/artifact/<最新の取得日>。
  --allow-overwrite          出力先(既定・明示のいずれも)に既に何らかのファイルが
                             あっても続行する(Ruling B31修正ラウンド3・項目3)。
                             **既定ではこのガードは--out-dirの明示有無を問わず
                             常に効く**——省略すると出力先に既存の何かがあるとき
                             拒否する。失敗したビルドのやり直し(kg.nqだけが
                             残った中途半端な出力先への再実行)も、このフラグの
                             明示が必要になる(意図的なコスト。「意図的な
                             バイパス」ではなく「意図の表明」を要求する)
USAGE
}

SOURCE_ARGS=()
PIPELINE_FLAGS=()
OUT=""
ALLOW_OVERWRITE=0
FAIL_ON_STALE=0
LATEST_DATE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --source)
      [ $# -ge 2 ] || { echo "--source に値が無い" >&2; usage; exit 2; }
      SOURCE_ARGS+=(--source "$2")
      # 出力先の既定値に使う「最新の取得日」。ISO 8601 は辞書順=日付順なので
      # 文字列比較で足りる。**この値がリリースの同一性(pipeline側のrelease)
      # と一致するとは限らない**(Ruling B31以降、releaseは成果物ディレクトリの
      # basenameであり、取得日から決まらない)。ここでは単に「出力先が未指定の
      # ときに使う、それらしいディレクトリ名」の既定値として使うだけであり、
      # 既存リリースへの上書きは下記のガードで別途防ぐ
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
    --allow-overwrite)
      ALLOW_OVERWRITE=1
      shift
      ;;
    --include-all-corporations)
      PIPELINE_FLAGS+=(--include-all-corporations)
      shift
      ;;
    --corporations-scope)
      [ $# -ge 2 ] || { echo "--corporations-scope に値が無い" >&2; usage; exit 2; }
      PIPELINE_FLAGS+=(--corporations-scope "$2")
      shift 2
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

# **Ruling B31: 出力先が既に何か持っていたら拒否する。**
# `LATEST_DATE`(最新のソース取得日)は「それらしいディレクトリ名」では
# あるが、リリースの同一性そのものではない(上記コメント参照) — 同じ日に
# 別構成(全法人/支出先限定など)のリリースを作ると、既定の出力先が既存の
# 全法人13.8GiB証拠と衝突しうる(Task 11修正ラウンドで実際に踏んだ危険)。
# **`manifest.json`の有無だけでは判定しない**——保護対象の全法人証拠
# (`data/artifact/2026-08-24/`)は`kg.nq`/`pipeline-report.json`はあるが
# `manifest.json`が無い(このディレクトリを作った当時のbuild.shはmanifest
# 生成に対応していなかった)。manifest.jsonの有無だけで判定すると、
# **まさに保護すべき対象そのものを検出できない。** ディレクトリが空でない
# (何らかのファイルが既にある)ことを検出条件にする。
#
# **Ruling B31修正ラウンド3(項目3)**: 以前は`--out-dir`を明示した場合に
# このガードを完全にバイパスしていた(「明示は利用者の意思表示」という
# 判断)。しかし`--out-dir data/artifact/2026-08-25`と打つだけで完了条件Aの
# 証拠(非コミットで代替が無い)が消えてしまう——**「明示」と「上書きの
# 承知」は別のことだった。** ガードは`--out-dir`の明示有無を問わず常に
# 効かせ、上書きしたいときだけ`--allow-overwrite`を別途要求する
# (「意図的なバイパス」を「意図の表明」に変える)。
#
# **副作用として、失敗したビルドのやり直しにもこのフラグが必要になる**
# (パイプラインが途中で落ちるとkg.nqだけが残った非空の出力先ができるため)。
# これは意図的なコスト——「前回失敗したビルドの残骸」と「保護すべき既存
# リリース」を、ディレクトリの中身だけからは区別できないため、いずれの場合も
# 利用者に確認を要求する
if [ "$ALLOW_OVERWRITE" -eq 0 ] && [ -d "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  echo "エラー: 出力先 ${OUT} には既に何らかのファイルがある(既存リリース" \
       "または失敗したビルドの残骸の疑い)。上書きするなら --allow-overwrite を" \
       "明示すること。失敗したビルドのやり直しも --allow-overwrite を明示する" \
       "(既存リリースとの区別をディレクトリの中身だけでは判定できないため)" >&2
  exit 1
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

echo "== TDB2インデックス構築(コンテナのネイティブ層) =="
# **バインドマウント上に直接構築しない(task-11-fix-brief.md §2。発見7)。**
# TDB2はノード表へのランダムI/Oが支配的で、Docker Desktop for Windows の
# バインドマウントは実質ネットワークファイル共有として振る舞う——設計書§6.3が
# 「TDB2はメモリマップドファイルを使うためSMB/NFS上に置くな」と警告していた
# 状況そのもの。**実測(progress.md 発見7の定量的裏付け): ネイティブ層
# 34,343 quads/秒 → バインドマウント596/秒(単調に減速)。約58倍の差。**
# 以前はここで直接 `--loc "/work/${OUT}/tdb2"`(バインドマウント上)に構築
# していたが、この経路は5.8M件規模で13時間以上かかり成立しない。
#
# コンテナのネイティブ層(overlayのwritable layer)に構築し、**同一コンテナ
# 実行内で**tar.gz化してからバインドマウント側(${OUT})へ出す。読み(kg.nq)は
# シーケンシャルなのでバインドマウント越しでも問題ない——ランダムI/Oだけを
# ネイティブ層に置く。
#
# **`/tdb2`という名前にする(`native-tdb2`ではない)。** `tar -C / tdb2` の
# 結果、tarball内のトップレベル名が`tdb2`になり、serve.pyが検査する
# `DB_DIRNAME = "tdb2"`(src/jgkg/serve.py)と最初から一致する——改名の
# ひと手間もその食い違いのリスクも要らない。
#
# **`time`はjena-toolsのベースイメージ(eclipse-temurin)に無い。** 使うと
# `sh: 1: time: not found`が`set -e`により即死する(発見7の副次教訓)。
# 所要時間はこのスクリプト自身の`phase_done`で測る。
#
# **`mkdir -p`をtdbloaderの前に置く(発見4: tdbloaderは出力ディレクトリを
# 自分では作らない)。** `--rm`付きの毎回新しいコンテナが毎回新しいoverlay
# layerで動くため、発見5/6(訂正版。実際は背景ジョブの終了判定ミスと
# 稼働中ディレクトリの誤削除)が踏んだ「前世代の/tdb2が生き残ったまま
# 新しい書き込みが追記される」危険は構造的に発生しない(前世代のoverlay
# layerはそのコンテナと一緒に消えている)。
#
# MSYS_NO_PATHCONV=1 が必要。**Windows の Git Bash / MSYS は `/work/...` のような
# POSIX風の絶対パス引数を Windows パスに書き換えてコンテナに渡す。**
# 実測(2026-08-23): /work/data/artifact/<日付>/kg.nq が
# `C:/Program Files/Git/work/data/artifact/<日付>/kg.nq` に化けて Can't read file で落ちた。
# **コンテナ内のパスなのでホスト側の変換をしてはならない。**
# cp932 や NTFS の予約文字と同じ、Windowsでしか出ない類型(設計書§11.1の再現性)。
rm -f "${OUT}/tdb2.tar.gz"
NATIVE_BUILD_LOG="${OUT}/.native-tdb2-build.log"
NATIVE_SCRIPT="set -e
mkdir -p /tdb2
tdb2.tdbloader --loc /tdb2 /work/${OUT}/kg.nq
du -sb /tdb2
tar -czf /work/${OUT}/tdb2.tar.gz -C / tdb2
"
# pipefail は先頭で設定済み(set -euo pipefail)。docker側が失敗すれば
# パイプ全体の終了コードが非0になり set -e で止まる
MSYS_NO_PATHCONV=1 docker compose --profile tools run --rm --entrypoint sh jena-tools \
  -c "$NATIVE_SCRIPT" 2>&1 | tee "$NATIVE_BUILD_LOG"
phase_done "tdbloader(コンテナのネイティブ層でTDB2構築+tar.gz化)"

echo "== 構築結果の実物検査 =="
# **`docker compose run`の終了コードを信じない**(progress.md 発見5/6の訂正で
# 確定した教訓。長時間実行では`docker ps`と実物で確認するのが本来の作法だが、
# ここは`--rm`付きの同期実行であり背景ジョブのラッパを介さないため、この
# スクリプト自身の制御フロー(pipefail)は機能する。それでも「構築後にtar.gzと
# 展開後サイズの検査を必ず入れる」(task-11-fix-brief.md §2)という要求は独立に
# 満たす——万が一途中の失敗が握り潰されても、tar.gzの中身が空/構造がおかしい
# ことで検出できるようにする)
#
# **実測で踏んだ新しい罠(2026-08-24): バインドマウントの書き込み反映に遅延
# がある。** `docker compose run`(コンテナ内でtar.gz化まで完了・exit 0)が
# 返った直後にホスト側で`tar -tzf`を実行すると、tdbloader自身のログには
# 成功(`Quads = 817,982 : Rate = 38,060/s`、エラー無し)が出ており、
# tar.gz自体も非空(du -sbの値と整合するサイズ)なのに、`tdb2/Data-0001/`が
# 見つからず検査が落ちる事象を確認した。数秒後に同じ`tar -tzf`を手動で
# 実行すると正しく`tdb2/Data-0001/`以下42ファイルが見える——**内容は最初から
# 正しかった。ホスト側から見える内容がコンテナのexit直後にはまだ反映されて
# いなかった**(Docker Desktop for Windowsのバインドマウント特有の遅延。
# 発見4/5/6/7と同系列の「バインドマウントは素朴には信用できない」の別の顔)。
# **対処: 即座に失敗にせず、短い間隔でリトライする**(ファイルの中身を
# 再構築するのではなく、ホスト側から見える状態が追いつくのを待つだけ)
#
# **追記(同日、2回目の実測): 最初の対処(2秒間隔×5回=最大10秒)では
# 不足だった。** 同じビルドをリトライ機構付きでもう一度実行したところ、
# 5回(10秒)リトライしてもなお`tdb2/Data-0001/`が見えず失敗した。ビルド
# 終了後、時間を置いてから同じ`tar.gz`(44,666,075バイト・全43エントリ)を
# 手動検査すると内容は完全に正しかった——つまり反映遅延は「数秒」ではなく
# **10秒を超えて続くことがある**(上限は未知。おそらくtar.gzのサイズに応じて
# 伸びる)。10秒固定の再試行はこの種の遅延に対して脆いと判断し、指数バック
# オフで最大約142秒まで待てるようにした(早い場合は数秒で抜け、遅い場合でも
# 打ち切らない)。
if [ ! -s "${OUT}/tdb2.tar.gz" ]; then
  echo "エラー: ${OUT}/tdb2.tar.gz が作られなかったか空である" >&2
  exit 1
fi
DATA0001_FOUND=0
_wait_start=$SECONDS
_sleep_s=2
_max_attempts=12
_attempt=0
while [ "$_attempt" -lt "$_max_attempts" ]; do
  _attempt=$((_attempt + 1))
  # 注意: `tar -tzf ... | grep -q PATTERN` は書かない。grep -qは最初の
  # マッチが見えた時点で読み取りを終えてパイプを閉じる(tar側はSIGPIPEを
  # 受けて即終了する)ため、目当てのエントリより後ろにある残りの
  # アーカイブ本体(実データファイル群)が最後まで読めるかどうかを
  # 検査しないまま「見つかった」と判定してしまう。ここでの検査目的は
  # 「tdb2/Data-0001/が見える」ことだけでなく「gzip streamの終端まで
  # tarが壊れずに読み切れる」ことも兼ねているので、一旦変数に全件を
  # 読み切ってからgrepする。
  if listing=$(tar -tzf "${OUT}/tdb2.tar.gz" 2>/dev/null) \
     && grep -q '^tdb2/Data-0001/' <<<"$listing"; then
    DATA0001_FOUND=1
    echo "  tdb2/Data-0001/ が見えた(試行 ${_attempt}/${_max_attempts}、" \
         "待ち始めてから $((SECONDS - _wait_start))秒)"
    break
  fi
  if [ "$_attempt" -eq "$_max_attempts" ]; then
    break
  fi
  echo "  tdb2/Data-0001/ がまだ見えない(試行 ${_attempt}/${_max_attempts}、" \
       "経過 $((SECONDS - _wait_start))秒)。バインドマウントの反映待ちの" \
       "可能性があるため${_sleep_s}秒後に再試行する"
  sleep "$_sleep_s"
  if [ "$_sleep_s" -lt 16 ]; then
    _sleep_s=$((_sleep_s * 2))
  fi
done
if [ "$DATA0001_FOUND" -ne 1 ]; then
  echo "エラー: ${OUT}/tdb2.tar.gz の中に tdb2/Data-0001/ が無い" \
       "(${_max_attempts}回・約$((SECONDS - _wait_start))秒リトライしても" \
       "見えなかった。TDB2の実データが構築されていない疑い)" >&2
  exit 1
fi
# du -sb の出力(`<バイト数><TAB>/tdb2`)をログから取り出す。§6.3の8GiB判定に
# 使う数値なので、**読み取れなければ manifest に黙って書かず、ここで止める**
TDB2_EXPANDED_BYTES=$(grep -P '^[0-9]+\t/tdb2$' "$NATIVE_BUILD_LOG" | tail -1 | cut -f1)
if [ -z "$TDB2_EXPANDED_BYTES" ]; then
  echo "エラー: du -sb の出力を ${NATIVE_BUILD_LOG} から読み取れなかった" \
       "(TDB2展開後サイズを記録できない。§6.3の8GiB判定に必要)" >&2
  exit 1
fi
echo "TDB2展開後サイズ: ${TDB2_EXPANDED_BYTES} bytes"
phase_done "構築結果の検査"

echo "== manifest作成 =="
JGKG_OUT="$OUT" JGKG_JENA_VERSION_FOR_MANIFEST="$JENA_VERSION" \
  JGKG_TDB2_EXPANDED_BYTES="$TDB2_EXPANDED_BYTES" uv run python -c "
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
    # Task 11修正ラウンド(fix-brief §3): du -sb で実測したTDB2展開後サイズ。
    # §6.3の8GiB判定(全法人13.8GiB/支出先限定429MiB。修正ラウンド2で旧
    # 「232MiB」表記を実測値に訂正——docs/measurements-phase1.md参照)を
    # リリースごとにmanifestから読めるようにする
    tdb2_expanded_bytes=int(os.environ['JGKG_TDB2_EXPANDED_BYTES']),
)
build.write_manifest(m, out / 'manifest.json')
print(m.model_dump_json(indent=2))
"

phase_done "manifest作成"
echo "完了: ${OUT}(総所要 $(( $(date +%s) - BUILD_STARTED_AT )) 秒)"
