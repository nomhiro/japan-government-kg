# Fuseki を公式アーカイブから自前ビルドする。
#
# **公開されている Fuseki の Docker イメージを使わない理由**(2026-08-23 実測):
#   - `apache/jena-fuseki` は **Docker Hub に存在しない**
#     (`docker manifest inspect` が object not found)
#   - 実在するのは `stain/jena-fuseki`(コミュニティ提供)だが、
#     **最新タグが 5.1.0 で 6.x が無い**
#   → JENA_VERSION でピン留めするという設計書§6.3の要件を、公開イメージでは満たせない。
#
# TDB2 はオンディスク形式が Jena のバージョンに紐づくため、
# **インデックスを作った側(jena-tools)と提供する側(ここ)が同じバージョンでなければならない。**
# 両方を同じ Apache 公式アーカイブから同じ ARG で入れることで、一致を構造的に保証する。
FROM eclipse-temurin:21-jre

ARG JENA_VERSION
ENV FUSEKI_HOME=/opt/fuseki
ENV JGKG_JENA_VERSION=${JENA_VERSION}

RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/fuseki.tar.gz \
      "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${JENA_VERSION}.tar.gz"; \
    tar -xzf /tmp/fuseki.tar.gz -C /opt; \
    rm /tmp/fuseki.tar.gz; \
    # バージョンに依らない固定パスを作る(compose の command をバージョンから切り離す)
    ln -s "/opt/apache-jena-fuseki-${JENA_VERSION}" "${FUSEKI_HOME}"; \
    mkdir -p /fuseki/databases; \
    test -x "${FUSEKI_HOME}/fuseki-server"

WORKDIR /fuseki
EXPOSE 3030
