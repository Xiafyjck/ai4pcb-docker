# syntax=docker/dockerfile:1.7

FROM ghcr.io/casey/just:latest AS just

FROM nvidia/cuda:13.2.1-devel-ubuntu24.04

ARG UV_VERSION=0.12.4

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY --from=just /just /usr/local/bin/just
COPY common/ /opt/ai4pcb/common/
COPY setup/justfile /opt/ai4pcb/setup.justfile

RUN INSTALL_BUILD_TOOLS=1 bash /opt/ai4pcb/common/install-base.sh \
    && UV_VERSION="$UV_VERSION" bash /opt/ai4pcb/common/install-uv.sh \
    && nvcc --version \
    && uv --version \
    && ldd /usr/local/bin/uv \
    && just --version \
    && command -v vim \
    && command -v curl \
    && command -v ping \
    && command -v ss \
    && command -v dig

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_LINK_MODE=copy \
    UV_TOOL_BIN_DIR=/usr/local/bin

WORKDIR /workspace

EXPOSE 22
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]
