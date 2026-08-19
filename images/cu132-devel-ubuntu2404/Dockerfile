# syntax=docker/dockerfile:1.7

# 必须声明在第一个 FROM 之前：ARG 只有在这个位置才是全局的，写在别的 FROM 后面就归那个
# stage 所有，FROM ${GO_IMAGE} 会拿到空串并报 "base name should not be blank"。
ARG GO_IMAGE=golang:bookworm

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

ARG NVM_VERSION=latest
ARG NODE_VERSION=node
ARG MIHOMO_VERSION=latest
# 改变它会让下面那层滚动工具重装。CI 传 run id，本地 just build 传时间戳——否则
# "latest" 会被缓存层永久冻在第一次构建那天。
ARG TOOL_REFRESH=manual

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_LINK_MODE=copy \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    BOXCTL_HOME=/opt/boxctl \
    NVM_DIR=/root/.nvm \
    NVM_SYMLINK_CURRENT=true \
    PATH=/root/.nvm/current/bin:/root/.local/bin:${PATH}

COPY --from=just /just /usr/local/bin/just
COPY --from=wireproxy /go/bin/wireproxy /usr/local/bin/wireproxy
COPY common/ /opt/boxctl/common/
COPY boxctl/ /opt/boxctl/
COPY vpn/ /opt/boxctl/vpn/
COPY fsferry/ /opt/boxctl/fsferry/
COPY setup/justfile /opt/boxctl/setup.justfile
# 文档跟代码同层，版本永远对得上。刻意不往 /root 放：那是用户的家目录，平台又靠快照留着
# 它，塞进去的文档会在容器里冻住，镜像更新了也不会跟着变。
COPY README.md /opt/boxctl/README.md

# uv 走官方安装器而不是 ghcr 上那个镜像：后者是 musl 静态构建，在本镜像里 DNS 解析会
# 失败。ldd 那行是这条约束的守卫——真装成静态二进制时它会当场炸，而不是等到运行时
# 某次下载莫名其妙超时。
RUN INSTALL_BUILD_TOOLS=1 bash /opt/boxctl/common/install-base.sh \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && nvcc --version \
    && uv --version \
    && ldd /root/.local/bin/uv \
    && just --version \
    && wireproxy --version \
    && command -v supervisord \
    && command -v vim \
    && command -v curl \
    && command -v ping \
    && command -v ss \
    && command -v dig

# 滚动版本的工具单独一层，靠 TOOL_REFRESH 破缓存，不去动上面那层 apt。
RUN echo "Refreshing rolling tools: ${TOOL_REFRESH}" \
    && NVM_VERSION="${NVM_VERSION}" NODE_VERSION="${NODE_VERSION}" \
       bash /opt/boxctl/common/install-node.sh \
    && MIHOMO_VERSION="${MIHOMO_VERSION}" \
       bash /opt/boxctl/common/install-mihomo.sh \
    && node --version \
    && npm --version \
    && mihomo -v

# fsferry 装成命令，通道目录由 FSFERRY_DIR 在运行时给。指定 /usr/bin/python3 是为了不让
# uv 再去下一个托管解释器：这个包零依赖，系统 python 足够。
RUN uv tool install --python /usr/bin/python3 /opt/boxctl/fsferry \
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
