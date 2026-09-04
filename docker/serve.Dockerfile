# 自己完結した「KGを提供できる」イメージ(D-6b-1)。
#
# 満たすこと(task-D6b1-brief.md):
#   - 索引をイメージ層に焼く(実行時にボリュームをマウントしない)
#   - fuseki/kg.ttl を焼く(tdb2:unionDefaultGraph true を含む。内容は変えずコピーする)
#   - JENA_VERSION の ARG でFusekiをピン留めする(docker/fuseki.Dockerfileと同じ方式・理由。
#     TDB2のオンディスク形式はJenaのバージョンに紐づく)
#   - 更新エンドポイントを公開しない(fuseki/kg.ttl 自体が fuseki:query のみを宣言している)
#
# **索引の入手経路は ARG INDEX_SOURCE で選ぶ。**
#
#   release (既定・正)  公開済みのGitHub Releaseから tdb2.tar.gz + manifest.json を
#                        curlで取得する。**このDockerfileと公開リリースのタグだけで、
#                        第三者もCIも同じイメージを再現できる**——設計書§6.3の
#                        「成果物配布方式」が目指す「配った物がそのまま動く」を、
#                        イメージのビルドそのものにも適用する。ネットワークが要る
#   local (開発用フォールバック)  docker/local-release/{manifest.json,tdb2.tar.gz}
#                        (scripts/build-serve-images.sh が data/artifact/<release>/ から
#                        ビルド直前に1世代分だけコピーする)を使う。ネットワーク不要で速い。
#                        data/ は .dockerignore でビルドコンテキストから除外しているため、
#                        このDockerfile自身はdata/を直接参照しない
#
# **どちらの経路でも索引の同一性照合(sha256・Jenaバージョン)を通す。**
# `jgkg.serve`(内部で`jgkg.build.verify_manifest`を呼ぶ。scripts/serve.sh・
# scripts/run-from-release.sh・.github/workflows/cold-read-measurement.ymlと同じ
# 唯一の照合経路)を**そのまま呼ぶ**。展開先を一時的に`.../current/tdb2`という
# `jgkg.serve`の形状検査(`stage_release`)が要求する形に整えるだけで、
# sha256/jena_versionの比較そのものを再実装しない(裁定B63: 同じ概念を
# 2つの実装に分けない)。**壊れたtarballや版の合わないmanifestを渡すと、
# ここでビルド自体が失敗する**(タスクブリーフが要求する「わざと壊す」確認)。
#
# ビルド例(scripts/build-serve-images.shが両方を薄くラップする):
#   B(既定・正):
#     docker build -f docker/serve.Dockerfile \
#       --build-arg JENA_VERSION=6.2.0 \
#       --build-arg RELEASE_TAG=2026-08-28-d2-recipient-category-v2 \
#       -t jgkg-serve:local .
#   A(開発用):
#     cp data/artifact/<release>/manifest.json docker/local-release/
#     cp data/artifact/<release>/tdb2.tar.gz    docker/local-release/
#     docker build -f docker/serve.Dockerfile \
#       --build-arg JENA_VERSION=6.2.0 --build-arg INDEX_SOURCE=local \
#       -t jgkg-serve:local .
#
# INDEX_SOURCE はFROM行の値を決めるため、最初のFROMより前(グローバルスコープ)で
# 宣言する必要がある(Docker/BuildKitの制約)。他のARGはそれぞれ使う段の中で宣言する。
ARG INDEX_SOURCE=release

# ---- 索引の入手経路 B(既定・正): 公開GitHub Releaseから取得する ----
FROM alpine:3.20 AS fetch-release
ARG RELEASE_TAG
ARG RELEASE_REPO=nomhiro/japan-government-kg
RUN apk add --no-cache curl
WORKDIR /assets
RUN set -eux; \
    test -n "${RELEASE_TAG}" || { \
      echo "RELEASE_TAG が未指定。--build-arg RELEASE_TAG=<公開リリースのタグ>" \
           "(例: 2026-08-28-d2-recipient-category-v2)を渡す" >&2; \
      exit 1; \
    }; \
    base_url="https://github.com/${RELEASE_REPO}/releases/download/${RELEASE_TAG}"; \
    curl --retry 3 --retry-delay 2 -fsSL -o manifest.json "${base_url}/manifest.json"; \
    curl --retry 3 --retry-delay 2 -fsSL -o tdb2.tar.gz "${base_url}/tdb2.tar.gz"

# ---- 索引の入手経路 A(開発用フォールバック): ローカルのステージング場所 ----
# scripts/build-serve-images.sh local <release> が事前にここへコピーする。
# **このDockerfile自身はdata/artifact/を一切参照しない**(.dockerignoreの理由と同じ:
# 索引の入手経路(B)を使うビルドが、使わない(A)側のためだけに巨大なdata/を
# コンテキストとして毎回送らされないようにする)。
FROM scratch AS fetch-local
COPY docker/local-release/manifest.json docker/local-release/tdb2.tar.gz /assets/

# INDEX_SOURCE に応じて上の2段のどちらかを選ぶ。選ばれなかった段はBuildKitの
# 依存グラフに現れないため実行されない(= 使わない経路の入力が無くても失敗しない)。
FROM fetch-${INDEX_SOURCE} AS fetch

# ---- 同一性照合+展開: jgkg.serve をそのまま呼ぶ(裁定B63: 再実装しない) ----
FROM python:3.12-slim AS index-builder
ARG JENA_VERSION
WORKDIR /build
# pyproject.toml・uv.lock・src だけで足りる(jgkg.build/jgkg.serveの依存は
# pydanticのみ。他プロジェクト依存〔linkml等〕も込みでpipに解かせて、
# .github/workflows/cold-read-measurement.ymlの `uv sync` と同じ「フル依存で
# jgkg.serveを動かす」構成に揃える——最小依存だけ抜き出す特別扱いを作らない)
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN pip install --no-cache-dir --disable-pip-version-check .
COPY --from=fetch /assets /build/incoming
RUN set -eux; \
    test -n "${JENA_VERSION}" || { \
      echo "JENA_VERSION が未指定。--build-arg JENA_VERSION=<Fusekiと同じ版>" >&2; \
      exit 1; \
    }; \
    python -m jgkg.serve /build/incoming \
      --target /build/data/artifact/current/tdb2 \
      --jena-version "${JENA_VERSION}"

# ---- 提供本体: Fusekiを公式アーカイブから自前ビルドする(docker/fuseki.Dockerfileと同じ理由) ----
FROM eclipse-temurin:21-jre AS runtime
ARG JENA_VERSION
ARG INDEX_SOURCE
ARG RELEASE_TAG=""
ARG GIT_COMMIT=""
ARG GIT_DIRTY="unknown"
ARG BUILD_DATE=""
ENV FUSEKI_HOME=/opt/fuseki
ENV JGKG_JENA_VERSION=${JENA_VERSION}

RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/fuseki.tar.gz \
      "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${JENA_VERSION}.tar.gz"; \
    tar -xzf /tmp/fuseki.tar.gz -C /opt; \
    rm /tmp/fuseki.tar.gz; \
    ln -s "/opt/apache-jena-fuseki-${JENA_VERSION}" "${FUSEKI_HOME}"; \
    mkdir -p /fuseki/databases; \
    test -x "${FUSEKI_HOME}/fuseki-server"

# fuseki/kg.ttl の内容は変えない(tdb2:unionDefaultGraph true・fuseki:query のみの
# 公開を含めてそのまま)。コピーするだけ
COPY fuseki/kg.ttl /fuseki/config/kg.ttl

# **索引をイメージ層に焼く(実行時にボリュームをマウントしない)。**
# tdb.lock は実行時にコンテナの書き込み可能層(overlay)へ作られるため、
# イメージ層自体が読み取り専用でもFusekiは開ける(実測済み。task-D6b1-report.md参照)
COPY --from=index-builder /build/data/artifact/current/tdb2 /fuseki/databases/kg

# **どのKGリリース・どのコミットから作られたかを刻む**(manifest.jsonが持つ
# git_commit/git_dirty/created_onと同じ追跡可能性を、イメージ側にも持たせる)。
# 検証済みのmanifest.jsonをそのまま焼く——値を手で転記しない
COPY --from=index-builder /build/incoming/manifest.json /fuseki/kg-manifest.json
# **ベースイメージ(eclipse-temurin。Ubuntu由来)のOCIラベルを上書きする。**
# `org.opencontainers.image.description`/`.version`はLABELが積算されるため、
# 明示的に上書きしないとUbuntuの説明・バージョン(例: "26.04")が残ったまま
# このイメージ自身の説明として`docker inspect`に出る——**このイメージはUbuntuでは
# ない。成果物が自分について偽を主張してはならない**(このプロジェクトの
# 再発欠陥6と同じ型。B-2裁定がmanifest.jsonのgit_commit/git_dirtyで扱った
# 「配布物が出典を偽らない」という要求を、ベースイメージ由来のラベルにも適用する)。
# `.version`は単一の意味のある値が無い(Jenaの版はJGKG_JENA_VERSION、KGの版は
# com.jgkg.kg.release-tagが別に持つ)ため、Ubuntuの版を残すよりは空にする
LABEL org.opencontainers.image.title="jgkg-serve" \
      org.opencontainers.image.description="日本政府KGを読み取り専用で提供するFuseki(索引をイメージ層に焼き込み済み)" \
      org.opencontainers.image.version="" \
      org.opencontainers.image.source="https://github.com/nomhiro/japan-government-kg" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      com.jgkg.build.git-dirty="${GIT_DIRTY}" \
      com.jgkg.kg.index-source="${INDEX_SOURCE}" \
      com.jgkg.kg.release-tag="${RELEASE_TAG}" \
      com.jgkg.kg.manifest-path="/fuseki/kg-manifest.json"

WORKDIR /fuseki
EXPOSE 3030
CMD ["/opt/fuseki/fuseki-server", "--config=/fuseki/config/kg.ttl"]
