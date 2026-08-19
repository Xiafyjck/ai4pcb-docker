# syntax=docker/dockerfile:1.7

# 必须声明在第一个 FROM 之前：ARG 只有在这个位置才是全局的，写在别的 FROM 后面就归那个
# stage 所有，FROM ${GO_IMAGE} 会拿到空串并报 "base name should not be blank"。
ARG GO_IMAGE=golang:bookworm

FROM ghcr.io/astral-sh/uv:latest AS uv
FROM ghcr.io/casey/just:latest AS just

# wireproxy：用户态 WireGuard，不需要 /dev/net/tun 和 NET_ADMIN，受管控的容器也能用。
# 构建期编译进镜像，换构建平台自动跟着走——它以前是预编译二进制搁在共享卷里，换到
# arm64 机器就得手工重编一次。
# 上游模块已迁到 windtf，旧的 pufferffish/octeep 路径会重定向过去并报 go.mod 路径校验错。
FROM ${GO_IMAGE} AS wireproxy
ARG WIREPROXY_VERSION=latest
ARG GOPROXY=https://goproxy.cn,direct
ENV CGO_ENABLED=0 GOFLAGS=-trimpath GOTOOLCHAIN=auto
RUN go install github.com/windtf/wireproxy/cmd/wireproxy@${WIREPROXY_VERSION}

FROM nvidia/cuda:13.2.1-devel-ubuntu24.04

ARG MIHOMO_VERSION=latest
ARG NVM_VERSION=v0.40.6
ARG NODE_VERSION=node

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_LINK_MODE=copy \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    BOXCTL_HOME=/opt/boxctl \
    NVM_DIR=/root/.nvm \
    NVM_SYMLINK_CURRENT=true \
    PATH=/root/.nvm/current/bin:${PATH}

COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=just /just /usr/local/bin/just
COPY --from=wireproxy /go/bin/wireproxy /usr/local/bin/wireproxy
COPY common/ /opt/boxctl/common/
COPY boxctl/ /opt/boxctl/
COPY vpn/ /opt/boxctl/vpn/
COPY fsferry/ /opt/boxctl/fsferry/
COPY setup/justfile /opt/boxctl/setup.justfile

RUN INSTALL_BUILD_TOOLS=1 bash /opt/boxctl/common/install-base.sh \
    && MIHOMO_VERSION="${MIHOMO_VERSION}" bash /opt/boxctl/common/install-mihomo.sh \
    && NVM_VERSION="${NVM_VERSION}" NODE_VERSION="${NODE_VERSION}" \
       bash /opt/boxctl/common/install-node.sh \
    && uv tool install --python /usr/bin/python3 /opt/boxctl/fsferry \
    && nvcc --version \
    && uv --version \
    && just --version \
    && wireproxy --version \
    && command -v supervisord \
    && command -v curl \
    && command -v ping \
    && command -v ss \
    && command -v dig \
    && node --version \
    && npm --version \
    && vpn --help > /dev/null \
    && h200 --help > /dev/null \
    && boxctl doctor

WORKDIR /workspace

# 22 = sshd（经 wireproxy 的 netstack 暴露到 wg 内网），7890 = mihomo mixed-port。
# 两者都由容器启动后的 boxctl / vpn.py 拉起，不是镜像自启的。
EXPOSE 22 7890
STOPSIGNAL SIGTERM

# 刻意不声明 ENTRYPOINT：平台会用自己的脚本覆盖它，留着只会让人以为服务是自启的。
# 这条 CMD 只是让镜像被单独 docker run 时不至于立刻退出。
CMD ["sleep", "infinity"]
