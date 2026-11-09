# MinIO server + mc client, built from pinned source releases.
# MinIO stopped publishing community container images in late 2025 (source-only since then),
# so we build it ourselves. Licence: AGPL-3.0 (we run it unmodified as a separate service).
FROM golang:1.25-alpine AS build
ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
ENV CGO_ENABLED=0 GOTOOLCHAIN=auto
RUN apk add --no-cache git
RUN git clone --depth 1 --branch "${MINIO_RELEASE}" https://github.com/minio/minio.git /src/minio \
    && cd /src/minio \
    && go build -trimpath -ldflags "-s -w -X github.com/minio/minio/cmd.Version=${MINIO_RELEASE}" -o /out/minio .
RUN git clone --depth 1 --branch "${MC_RELEASE}" https://github.com/minio/mc.git /src/mc \
    && cd /src/mc \
    && go build -trimpath -ldflags "-s -w" -o /out/mc .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates \
    && adduser -D -u 10001 minio \
    && mkdir -p /data \
    && chown minio:minio /data
COPY --from=build /out/minio /out/mc /usr/local/bin/
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
