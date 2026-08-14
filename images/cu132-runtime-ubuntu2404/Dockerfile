# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:latest AS uv
FROM ghcr.io/casey/just:latest AS just

FROM nvidia/cuda:13.2.1-runtime-ubuntu24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=just /just /usr/local/bin/just
COPY common/ /opt/ai4pcb/common/
COPY setup/justfile /opt/ai4pcb/setup.justfile

RUN INSTALL_BUILD_TOOLS=0 bash /opt/ai4pcb/common/install-base.sh \
    && uv --version \
    && just --version \
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
