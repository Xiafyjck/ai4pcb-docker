# syntax=docker/dockerfile:1.7

FROM ghcr.io/casey/just:1.58.0 AS just

FROM nvidia/cuda:13.2.1-runtime-ubuntu24.04

ARG NVM_VERSION=latest
ARG NODE_VERSION=24
ARG MIHOMO_VERSION=latest
ARG TOOL_REFRESH=manual

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV NVM_DIR=/root/.nvm \
    NVM_SYMLINK_CURRENT=true \
    PATH=/root/.nvm/current/bin:/root/.local/bin:${PATH}

COPY --from=just /just /usr/local/bin/just
COPY common/ /opt/ai4pcb/common/
COPY setup/justfile /opt/ai4pcb/setup.justfile

RUN INSTALL_BUILD_TOOLS=0 bash /opt/ai4pcb/common/install-base.sh \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && /root/.local/bin/uv --version \
    && ldd /root/.local/bin/uv \
    && just --version \
    && command -v vim \
    && command -v curl \
    && command -v ping \
    && command -v ss \
    && command -v dig

RUN echo "Refreshing rolling tools: $TOOL_REFRESH" \
    && NVM_VERSION="$NVM_VERSION" NODE_VERSION="$NODE_VERSION" \
       bash /opt/ai4pcb/common/install-node.sh \
    && MIHOMO_VERSION="$MIHOMO_VERSION" \
       bash /opt/ai4pcb/common/install-mihomo.sh \
    && node --version \
    && npm --version \
    && mihomo -v

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MIHOMO_CONFIG=/etc/mihomo/config.yaml \
    MIHOMO_HOME=/var/lib/mihomo \
    HTTP_PROXY=http://127.0.0.1:7890 \
    HTTPS_PROXY=http://127.0.0.1:7890 \
    ALL_PROXY=socks5h://127.0.0.1:7890 \
    NO_PROXY=localhost,127.0.0.1,::1 \
    http_proxy=http://127.0.0.1:7890 \
    https_proxy=http://127.0.0.1:7890 \
    all_proxy=socks5h://127.0.0.1:7890 \
    no_proxy=localhost,127.0.0.1,::1 \
    UV_LINK_MODE=copy \
    UV_TOOL_BIN_DIR=/usr/local/bin

WORKDIR /workspace

EXPOSE 22 7890
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]
