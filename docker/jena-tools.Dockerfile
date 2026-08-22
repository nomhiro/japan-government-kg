# TDB2 のインデックス構築に使う。Jena のバージョンは manifest に記録するため
# ここで固定し、実行側と照合する(設計書§6.3)。
FROM eclipse-temurin:21-jre

# JENA_VERSION は .env で指定する。最初の実行時に Apache Jena の
# 現行安定版を確認して設定する。
ARG JENA_VERSION
ENV JENA_HOME=/opt/apache-jena-${JENA_VERSION}
ENV PATH=${JENA_HOME}/bin:${PATH}
ENV JGKG_JENA_VERSION=${JENA_VERSION}

RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/jena.tar.gz \
      "https://archive.apache.org/dist/jena/binaries/apache-jena-${JENA_VERSION}.tar.gz"; \
    tar -xzf /tmp/jena.tar.gz -C /opt; \
    rm /tmp/jena.tar.gz; \
    tdb2.tdbloader --version || true

WORKDIR /work
