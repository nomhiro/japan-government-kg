#!/usr/bin/env bash
# 成果物を照合して配置し、Fusekiを起動する。
#
# **配置の前に manifest と照合する**(sha256 と Jenaバージョン)。設計書§6.3の
# 「Jenaのバージョンをmanifestに記録し、実行側で照合する」を実際に行う唯一の場所。
# 照合しない記録は記録の演技にすぎない(レビューI3)。
#
# 注意: TDB2はメモリマップを使うため、稼働中のディレクトリを上書きしてはならない。
# **Task 10でアトミック切替を実装した**: `jgkg.serve`が`data/artifact/current/`を
# ディレクトリごと入れ替える(`data/artifact/incoming/`に展開してから
# リネームで差し替える。前世代は必ず`data/artifact/previous/`に残る)。
# **それでも先にFusekiを止める**(停止→退避→配置→起動の順を維持する。
# ディレクトリの差し替え自体はファイルシステム上は瞬時だが、稼働中のFuseki
# プロセスが同じディレクトリをmmapしたまま配下のファイルが差し替わる状態を
# 作らないため、停止は省略できない)。
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
RELEASE="${1:?使い方: scripts/serve.sh YYYY-MM-DD}"

ART="data/artifact/${RELEASE}"

echo "== Fusekiを停止 =="
docker compose stop fuseki || true

echo "== 成果物の照合と配置 =="
# --jena-version には fuseki イメージのタグを決めている値をそのまま渡す。
# .env の JENA_VERSION を上げて古い成果物を配ろうとすると、ここで止まる
# **PYTHONUTF8=1**: これを付けずにWindows上で直接実行すると、標準出力の
# 日本語がプラットフォームの既定コードページ(UTF-8でない)で解釈されて
# 文字化けする(繰越項目。動作自体には影響しないが、運用時にログが読めない)
PYTHONUTF8=1 uv run python -m jgkg.serve "$ART" --jena-version "${JENA_VERSION}"

echo "== Fusekiを起動 =="
docker compose up -d fuseki

echo "完了: ${ART} を配置した(data/artifact/current/ に切替。前世代は data/artifact/previous/)。CQを1本流して確認すること"
echo "  例: curl -s --data-urlencode query@queries/cq/p0-02-ministry-list.rq http://localhost:3030/kg/sparql"
