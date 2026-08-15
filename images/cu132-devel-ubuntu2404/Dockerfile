# syntax=docker/dockerfile:1.7
#
# 与原版的区别，以及为什么：
#
# 1. 不再声明 ENTRYPOINT。平台启动容器时会用自己的脚本覆盖它（PID 1 实际是
#    launch_jupyterlab.sh），原来的 docker-entrypoint + supervisord 一次都没执行
#    过。留着只会让人以为服务是自启的。现在启动由共享卷上的 vpn.py 负责。
# 2. 不再硬编码 HTTP_PROXY 等 ENV。镜像 ENV 是 PID 1 及其所有后代的既成事实，而
#    mihomo 要等容器起来之后才由 vpn.py 拉起——中间这段时间里 jupyter/code-server
#    终端里的每一次 curl/pip/npm 都会撞上一个不存在的代理。改由 profile.d 探测到
#    代理确实在监听时才导出（见 common/proxy-env.sh）。
FROM ghcr.io/casey/just:1.58.0 AS just
# wireproxy：用户态 WireGuard，不需要 /dev/net/tun 和 NET_ADMIN。上游模块已迁到
# windtf，旧的 pufferffish/octeep 路径会重定向过去并报 go.mod 路径校验错。
ARG GO_VERSION=1.26
FROM golang:${GO_VERSION}-bookworm AS wireproxy
ARG WIREPROXY_VERSION=latest
ARG GOPROXY=https://goproxy.cn,direct
ENV CGO_ENABLED=0 GOFLAGS=-trimpath GOTOOLCHAIN=auto
RUN go install github.com/windtf/wireproxy/cmd/wireproxy@${WIREPROXY_VERSION}
FROM nvidia/cuda:13.2.1-devel-ubuntu24.04
ARG NVM_VERSION=latest
ARG NODE_VERSION=24
ARG MIHOMO_VERSION=latest
ARG TOOL_REFRESH=manual
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV NVM_DIR=/root/.nvm \
    NVM_SYMLINK_CURRENT=true \
    PATH=/root/.nvm/current/bin:/root/.local/bin:${PATH}
COPY --from=just /just /usr/local/bin/just
COPY --from=wireproxy /go/bin/wireproxy /usr/local/bin/wireproxy
COPY common/ /opt/ai4pcb/common/
COPY setup/justfile /opt/ai4pcb/setup.justfile
RUN INSTALL_BUILD_TOOLS=1 bash /opt/ai4pcb/common/install-base.sh \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && nvcc --version \
    && /root/.local/bin/uv --version \
    && ldd /root/.local/bin/uv \
    && just --version \
    && wireproxy --version \
    && command -v supervisord \
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
    UV_LINK_MODE=copy \
    UV_TOOL_BIN_DIR=/usr/local/bin
WORKDIR /workspace
# 22 = sshd（经 wireproxy 的 netstack 暴露到 wg 内网），7890 = mihomo mixed-port。
# 两者都由容器启动后执行的 vpn.py 拉起，见共享卷上的 vpn/README.md。
EXPOSE 22 7890
STOPSIGNAL SIGTERM
# 平台会覆盖启动命令；这条只是让镜像在被单独 docker run 时不会立刻退出。
CMD ["sleep", "infinity"]
