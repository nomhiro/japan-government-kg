# APIレイヤ(src/jgkg/api/)を自己完結したイメージとして提供する(D-6b-1)。
#
# **Fusekiとは別イメージ・別コンテナにする。** ACA(Azure Container Apps)は
# 1アプリに複数コンテナを置けるsidecarパターンを持ち、同一アプリ内のコンテナは
# ディスクとネットワークを共有してlocalhostで通信できる——FusekiとAPIを1つの
# イメージに詰め込む理由が無い(task-D6b1-brief.md #4)。
#
# **起動口は既存のまま変えない**: `uvicorn jgkg.api.app:create_production_app --factory`。
# `src/jgkg/api/app.py`のdocstringが明示する「モジュールレベルの`app = ...`を
# 置かない」判断を、CMDの`--factory`起点で維持する(importの副作用を持たせない)。
#
# **接続先はJGKG_SPARQL_ENDPOINTで差し替える(URLを直書きしない)。**
# `src/jgkg/config.py`のSettings(env_prefix="JGKG_")がそのまま読む——
# このDockerfileはENVで既定値を上書きしない(Pythonコード側の既定
# `http://localhost:3030/kg/sparql`を単一の出典に保つ)。docker-compose.serve.yml・
# 将来のACAでは環境変数として明示的に渡す。
#
# **起動時の温め(warmup.warm_up)はコードが既に行っている**
# (`src/jgkg/api/app.py`のlifespan)。このDockerfileでは何もしない——
# 「起動時に温めるか最初のリクエストで温めるか」の判断そのものはD-3が既に
# 決めていて(裁定B55・B60・B61)、D-6bはその上に載るだけ(task-D6b1-report.md参照)。
#
# ビルド例:
#   docker build -f docker/api.Dockerfile \
#     --build-arg GIT_COMMIT=$(git rev-parse HEAD) \
#     --build-arg GIT_DIRTY=false \
#     --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
#     -t jgkg-api:local .
FROM python:3.12-slim AS runtime

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN pip install --no-cache-dir --disable-pip-version-check .

ARG GIT_COMMIT=""
ARG GIT_DIRTY="unknown"
ARG BUILD_DATE=""
# **python:3.12-slimはOCIラベルを設定していない(実測)ので、ここでは
# 「ベースイメージの偽の主張を上書きする」問題は起きない**——docker/serve.Dockerfile
# (eclipse-temurin/Ubuntu由来)側のコメント参照。それでも`.description`は
# 明示しておく(値が無いより正確な値がある方がよい)
LABEL org.opencontainers.image.title="jgkg-api" \
      org.opencontainers.image.description="Japan Government KGのAPI層(/search・/entity/{id}・/neighborhood/{id}・/path)" \
      org.opencontainers.image.source="https://github.com/nomhiro/japan-government-kg" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      com.jgkg.build.git-dirty="${GIT_DIRTY}"

# uvicornの既定ポート8000のまま(frontend/src/api/client.tsの既定
# `http://localhost:8000`と揃える)。ホスト側のポート割り当ては
# docker-compose.serve.yml側で決める(8000はローカルのフロントエンド開発が
# 使うため、コンテナの外では別ポートに読み替える)
EXPOSE 8000
CMD ["uvicorn", "jgkg.api.app:create_production_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
