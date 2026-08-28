#!/usr/bin/env bash
# 公開されたGitHub Releaseから取得し、検証してから展開し、Fusekiを起動する。
#
# D-1(決定#42の実証): 「API層とFusekiは、起動時にGitHub Releasesから索引を
# 取得して一時ディスクに展開する、ステートレスなサーバーレスコンテナ上で動かす」
# という決定#42の実行時経路そのもの。**これが実質、コンテナの起動スクリプトになる。**
#
# **既存の scripts/serve.sh は data/artifact/<name>/ というローカルの成果物を
# 前提にしている。** このスクリプトは「外部の利用者としてふるまう」ことが目的
# なので、data/artifact/ と data/lake/ には一切触れない —
# ダウンロード先・展開先はすべて $WORKDIR (既定は使い捨ての一時ディレクトリ) に置く。
#
# 検証は2箇所で行う(いずれかが失敗したら即座に止める。既定は止まる側):
#   1. curl直後にsha256sumで素朴に照合する(外部の利用者が最初にやること)
#   2. jgkg.serve (内部でbuild.verify_manifest) が展開の直前に独立にもう一度照合する
#      (`scripts/serve.sh`と同じ既存の照合経路をそのまま再利用する。stage_release は
#      target の形〔.../current/tdb2〕しか要求しないため、data/artifact/ 配下でなくても
#      使える。この形でのsha256不一致拒否は tests/test_serve.py の
#      test_stage_release_refuses_a_corrupted_artifact が既に確認しており〔target は
#      tmp_path配下の任意のcurrent/tdb2〕、新規のテストはここでは追加しない)
#
# CQの実行とメモリ計測はこのスクリプトの範囲外(コンテナは自分自身を計測しない —
# Dockerfileの最終形も範囲外。task-D1-brief.md「起動スクリプトの検証まででよい」)。
# Fusekiが起動してエンドポイントが応答したら終わる。検証者としての確認は呼び出し側で行う。
set -euo pipefail

# Windows Git Bash特有の落とし穴が2つあり、**互いに逆方向**なので同時に有効化できない:
#   (a) `docker run -v` : MSYSのパス変換が「コンテナ側」のパス(`/fuseki/config`等)まで
#       「ホスト側の絶対パス」と誤認して変換してしまう(実測: `/fuseki/config` ->
#       `C:/Program Files/Git/fuseki/config` になり、存在しないパスとしてマウント失敗)。
#       `MSYS_NO_PATHCONV=1` を**そのdockerコマンドだけに**渡せば直る
#   (b) `curl -o <絶対POSIXパス>` : 逆に`MSYS_NO_PATHCONV=1`を**スクリプト全体に
#       export**すると、curl自身へのホスト側絶対パス(`/c/Users/...`)の変換が
#       止まってしまい、`curl: (23) client returned ERROR on write` で落ちる(実測。
#       相対パスや`MSYS_NO_PATHCONV`未設定なら同じ絶対パスで成功する ——
#       つまりcurlの成否ではなく、この変換の有無そのものが原因と確認済み)。
# したがって**exportしない**。docker runの行にだけインライン変数で渡す(下記)。
# Linux/macでは`MSYS_NO_PATHCONV`は無関係なので、どちらの経路でも影響しない

RELEASE_REPO="${RELEASE_REPO:-nomhiro/japan-government-kg}"
RELEASE_TAG="${RELEASE_TAG:?使い方: RELEASE_TAG=<タグ> scripts/run-from-release.sh}"
PORT="${PORT:-3031}"
CONTAINER_NAME="${CONTAINER_NAME:-jgkg-d1-verify}"
WORKDIR="${WORKDIR:-$(mktemp -d)}"
# kg.nq.gzも取得してnquads_sha256を照合するか(展開後175MB。ディスクに
# 余裕がなければ0にしてtarball側の照合だけで済ませてよい — task-D1-brief.md)
FETCH_NQUADS="${FETCH_NQUADS:-1}"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
: "${JENA_VERSION:?JENA_VERSION を .env に設定する}"

DOWNLOAD_DIR="${WORKDIR}/download"
mkdir -p "${DOWNLOAD_DIR}"
echo "== 作業ディレクトリ: ${WORKDIR} (data/artifact/, data/lake/ は参照しない) =="

json_field() {
  # jqがこの環境に無いため標準ライブラリのjsonだけで読む。欠けている欄は空文字
  python -c "import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print('' if v is None else v)" "$1" "$2"
}

BASE_URL="https://github.com/${RELEASE_REPO}/releases/download/${RELEASE_TAG}"

echo "== 取得: manifest.json / tdb2.tar.gz =="
SECONDS=0
# --retry: 転送の一時失敗に備える一般的な保険(5xx・タイムアウト等)。
# **`curl: (23) client returned ERROR on write`はretryの対象外**(ローカルの
# ディスク書き込み失敗であり、転送そのものの失敗ではないため再試行では治らない)。
# このエラーの実際の原因は本ファイル冒頭のコメントのとおり
# `MSYS_NO_PATHCONV`をexportしていたことで、--retryはそれを直していない
# (exportをやめた時点で解消したことを切り分け済み)
curl --retry 3 --retry-delay 2 -fsSL -o "${DOWNLOAD_DIR}/manifest.json" "${BASE_URL}/manifest.json"
curl --retry 3 --retry-delay 2 -fsSL -o "${DOWNLOAD_DIR}/tdb2.tar.gz"   "${BASE_URL}/tdb2.tar.gz"
DOWNLOAD_SEC=$SECONDS
# **この時点でのDOWNLOAD_SECはmanifest.json + tdb2.tar.gzのみ。**
# kg.nq.gzの取得(既定で行う。下記FETCH_NQUADS)はこのあとの別区間で行うため、
# 合計コールドスタートの計測にもkg.nq.gz分の時間は含まれない
# (§18.3参照。含めない理由は実行時が実際に必要とするのはtdb2.tar.gzだけで、
# nquads照合は任意の追加検証だから)
TARBALL_BYTES=$(wc -c < "${DOWNLOAD_DIR}/tdb2.tar.gz")
echo "  URL: ${BASE_URL}/manifest.json"
echo "  URL: ${BASE_URL}/tdb2.tar.gz"
echo "  ダウンロード時間: ${DOWNLOAD_SEC} 秒 (tdb2.tar.gz ${TARBALL_BYTES} バイト)"

echo "== 素朴なsha256照合(外部の利用者が最初にやること) =="
ACTUAL_SHA=$(sha256sum "${DOWNLOAD_DIR}/tdb2.tar.gz" | cut -d' ' -f1)
EXPECTED_SHA=$(json_field "${DOWNLOAD_DIR}/manifest.json" sha256)
echo "  manifestの記録: ${EXPECTED_SHA}"
echo "  実物のsha256  : ${ACTUAL_SHA}"
if [ "${ACTUAL_SHA}" != "${EXPECTED_SHA}" ]; then
  echo "!! sha256が一致しない。取得物が壊れている疑いがある。ここで止める" >&2
  exit 1
fi
echo "  一致(OK)"

if [ "${FETCH_NQUADS}" = "1" ]; then
  echo "== (任意)kg.nq.gz も取得してnquads_sha256を照合 =="
  curl --retry 3 --retry-delay 2 -fsSL -o "${DOWNLOAD_DIR}/kg.nq.gz" "${BASE_URL}/kg.nq.gz"
  gunzip -k -f "${DOWNLOAD_DIR}/kg.nq.gz"
  ACTUAL_NQ_SHA=$(sha256sum "${DOWNLOAD_DIR}/kg.nq" | cut -d' ' -f1)
  EXPECTED_NQ_SHA=$(json_field "${DOWNLOAD_DIR}/manifest.json" nquads_sha256)
  echo "  manifestの記録: ${EXPECTED_NQ_SHA}"
  echo "  実物のsha256  : ${ACTUAL_NQ_SHA}"
  if [ "${ACTUAL_NQ_SHA}" != "${EXPECTED_NQ_SHA}" ]; then
    echo "!! kg.nqのsha256が一致しない。ここで止める" >&2
    exit 1
  fi
  echo "  一致(OK)"
  rm -f "${DOWNLOAD_DIR}/kg.nq" "${DOWNLOAD_DIR}/kg.nq.gz"
fi

echo "== 展開して配置(jgkg.serveが独立にもう一度sha256とJenaバージョンを照合する) =="
SECONDS=0
PYTHONUTF8=1 uv run python -m jgkg.serve "${DOWNLOAD_DIR}" \
  --target "${WORKDIR}/current/tdb2" --jena-version "${JENA_VERSION}"
EXTRACT_SEC=$SECONDS
EXPANDED_BYTES=$(du -sb "${WORKDIR}/current/tdb2" | cut -f1)
EXPECTED_EXPANDED=$(json_field "${DOWNLOAD_DIR}/manifest.json" tdb2_expanded_bytes)
echo "  展開時間: ${EXTRACT_SEC} 秒"
echo "  展開後の実サイズ: ${EXPANDED_BYTES} バイト (manifestの記録: ${EXPECTED_EXPANDED} バイト)"

echo "== Fusekiを起動(検証専用コンテナ。requirements-draft-fuseki-1には触れない) =="
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
SECONDS=0
# MSYS_NO_PATHCONV=1 はこのdocker runコマンドにだけ渡す(スクリプト冒頭のコメント参照。
# curlの絶対パス書き込みを壊すためexportはしない)
MSYS_NO_PATHCONV=1 docker run -d --name "${CONTAINER_NAME}" \
  -p "${PORT}:3030" \
  -e "ADMIN_PASSWORD=${FUSEKI_ADMIN_PASSWORD:-change-me-in-env}" \
  -v "$(pwd)/fuseki:/fuseki/config:ro" \
  -v "${WORKDIR}/current/tdb2:/fuseki/databases/kg" \
  requirements-draft-fuseki:latest \
  /opt/fuseki/fuseki-server --config=/fuseki/config/kg.ttl >/dev/null

ENDPOINT="http://localhost:${PORT}/kg/sparql"
echo "  起動待ち... (${ENDPOINT})"
# **既定は止まる側。** `docker run -d`はFuseki自体が起動直後に落ちても成功で返る
# (実際、tdb.lockが取れずに落ちる壊し確認〔§18.4(3)〕がまさにこの形)。
# 無期限に`until`で待ち続けると、起動失敗が「無応答のまま止まったように見える」
# だけになってしまうため、待機回数に上限を設けてログを出してから明示的に失敗させる
READY=0
for _ in $(seq 1 120); do
  if curl -s -o /dev/null -w '%{http_code}' --data-urlencode 'query=ASK { ?s ?p ?o }' "${ENDPOINT}" 2>/dev/null | grep -q 200; then
    READY=1
    break
  fi
  sleep 1
done
if [ "${READY}" != "1" ]; then
  echo "!! 120秒待ったがFusekiが応答しない。直近のログ:" >&2
  docker logs --tail 30 "${CONTAINER_NAME}" >&2 || true
  exit 1
fi
STARTUP_SEC=$SECONDS
TOTAL_SEC=$((DOWNLOAD_SEC + EXTRACT_SEC + STARTUP_SEC))
echo "  Fuseki起動〜最初のクエリ応答: ${STARTUP_SEC} 秒"
echo "  合計コールドスタート(ダウンロード+展開+起動): ${TOTAL_SEC} 秒"

echo
echo "完了。エンドポイント: ${ENDPOINT}"
echo "後片付け: docker rm -f ${CONTAINER_NAME} && rm -rf ${WORKDIR}"
