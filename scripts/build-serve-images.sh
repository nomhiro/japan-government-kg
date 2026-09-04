#!/usr/bin/env bash
# 提供用の自己完結イメージ(serve-fuseki・serve-api)をビルドして起動する。
# D-6b-1。既存の docker-compose.yml(開発用)には触れない
# (docker-compose.serve.yml を -f で明示的に指定する)。
#
# 使い方:
#   scripts/build-serve-images.sh release <RELEASE_TAG>   # 索引の入手経路B(既定・正)
#   scripts/build-serve-images.sh local <RELEASE_NAME>     # 索引の入手経路A(開発用)
#
# RELEASE_TAG/RELEASE_NAME は data/artifact/ 配下のディレクトリ名と同じ形
# (例: 2026-08-28-d2-recipient-category-v2)。
#
# 本体の同一性照合(sha256・Jenaバージョン)は docker/serve.Dockerfile が
# jgkg.serve をそのまま呼んで行う(裁定B63: ここでは再実装しない)。
# このスクリプトの役割は2つだけ:
#   1. (local選択時のみ)data/artifact/<name>/ から1世代分をビルドコンテキスト内の
#      docker/local-release/ へコピーする(data/自体はビルドコンテキストから
#      除外している。.dockerignore参照)
#   2. git commit / dirty / build date を導出してビルド引数として渡す
#      (scripts/build.sh が manifest.json に記録するときと同じ導出。イメージにも
#      同じ追跡可能性を持たせる——task-D6b1-brief.md #3)
set -euo pipefail

MODE="${1:?使い方: scripts/build-serve-images.sh <release|local> <RELEASE_TAG_or_NAME>}"
NAME="${2:?使い方: scripts/build-serve-images.sh <release|local> <RELEASE_TAG_or_NAME>}"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
: "${JENA_VERSION:?JENA_VERSION を .env に設定する}"

case "${MODE}" in
  release)
    export INDEX_SOURCE=release
    export RELEASE_TAG="${NAME}"
    echo "== 索引の入手経路: B(公開GitHub Release ${RELEASE_TAG}) =="
    ;;
  local)
    export INDEX_SOURCE=local
    export RELEASE_TAG=""
    SRC="data/artifact/${NAME}"
    for f in manifest.json tdb2.tar.gz; do
      [ -f "${SRC}/${f}" ] || {
        echo "!! ${SRC}/${f} が無い。data/artifact/<name>/ に" \
             "manifest.json と tdb2.tar.gz を持つ世代を指定する" >&2
        exit 1
      }
    done
    echo "== 索引の入手経路: A(ローカル ${SRC}) =="
    mkdir -p docker/local-release
    cp "${SRC}/manifest.json" "${SRC}/tdb2.tar.gz" docker/local-release/
    ;;
  *)
    echo "!! 第1引数は release か local (渡された値: ${MODE})" >&2
    exit 1
    ;;
esac

# scripts/build.sh の導出とそろえる(git_commit/git_dirty/created_onと同じ性質の値。
# 手で書かない——このプロセスがコマンドとして実行して読む)
GIT_COMMIT=$(git rev-parse HEAD)
if [ -z "${GIT_COMMIT}" ]; then
  echo "!! git rev-parse HEAD が空を返した(gitリポジトリの外で実行している疑い)" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  GIT_DIRTY=true
else
  GIT_DIRTY=false
fi
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
export GIT_COMMIT GIT_DIRTY BUILD_DATE
echo "ビルド元コミット: ${GIT_COMMIT} (dirty=${GIT_DIRTY}, ${BUILD_DATE})"

echo "== ビルド =="
docker compose -f docker-compose.serve.yml build

echo "== 起動 =="
docker compose -f docker-compose.serve.yml up -d

echo
echo "完了。"
echo "  Fuseki: http://localhost:${SERVE_FUSEKI_PORT:-8060}/kg/sparql"
echo "  API   : http://localhost:${SERVE_API_PORT:-8055}"
echo "後片付け: docker compose -f docker-compose.serve.yml down"
