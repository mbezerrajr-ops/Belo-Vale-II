# MinIO compilado do código-fonte, na mesma versão que a produção usa.
#
# Em 2026 a MinIO arquivou o servidor de código aberto: a imagem saiu do
# Docker Hub e do quay.io, e dl.min.io responde 410. O código continua no
# GitHub. Isto é uma ponte: trocar por um servidor compatível com S3 que
# ainda receba manutenção é trabalho à parte (ver docs/known-issues.md).
#
# RELEASE.2025-04-22T22-12-26Z, a mesma da produção: mesma versão, mesmo
# formato dos dados no volume. O commit é o que o binário oficial informa em
# `minio --version`, e o build confere que a tag aponta para ele. Flags e
# carimbo de versão são os do Makefile e do buildscripts/gen-ldflags.go
# da própria MinIO.
#
# Pasta própria como contexto de build: a pasta infra/ tem os .env.

FROM golang:1.24.2-bookworm AS build
ARG TARGETOS
ARG TARGETARCH
ARG MINIO_TAG=RELEASE.2025-04-22T22-12-26Z
ARG MINIO_COMMIT=0d7408fc9969caf07de6a8c3a84f9fbb10a6739e
ARG MINIO_VERSION=2025-04-22T22:12:26Z

WORKDIR /src
RUN git init -q . \
    && git remote add origin https://github.com/minio/minio.git \
    && git fetch -q --depth 1 origin "refs/tags/${MINIO_TAG}" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "${MINIO_COMMIT}"

RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} go build -tags kqueue -trimpath \
      -ldflags "$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go "${MINIO_VERSION}")" \
      -o /out/minio

FROM alpine:3.22
# curl: o healthcheck do compose chama /minio/health/live com ele.
RUN apk add --no-cache ca-certificates curl
COPY --from=build /out/minio /usr/bin/minio
COPY --from=build /src/LICENSE /licenses/LICENSE
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/bin/minio"]
