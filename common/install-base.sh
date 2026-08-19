#!/usr/bin/env bash
set -Eeuo pipefail

export DEBIAN_FRONTEND=noninteractive

packages=(
    openssh-server
    openssh-client
    supervisor
    ca-certificates
    curl
    wget
    git
    git-lfs
    rsync
    procps
    # vpn.py 是纯标准库的 python 脚本，而 ubuntu 基础镜像不带 python3
    python3
    iproute2
    iputils-ping
    dnsutils
    netcat-openbsd
    traceroute
    mtr-tiny
    socat
    tcpdump
    lsof
    strace
    file
    less
    vim
    tmux
    jq
    unzip
    gzip
    xz-utils
    zstd
    bash-completion
)

if [[ "${INSTALL_BUILD_TOOLS:-0}" == "1" ]]; then
    packages+=(
        build-essential
        pkg-config
        cmake
        ninja-build
        gdb
    )
fi

apt-get update
apt-get install -y --no-install-recommends "${packages[@]}"
rm -rf /var/lib/apt/lists/*

install -d -m 0755 /run/sshd
install -d -m 0700 /run/ssh /root/.ssh

# 刻意不建 /etc/mihomo、/var/lib/mihomo：它们在容器可写层，重启即丢，geoip 数据库每次
# 都得重下。mihomo 的工作目录由 vpn.py 指到共享卷上的运行时目录。

# 镜像里刻意不带 SSH 主机密钥：否则由本镜像起的所有容器共用同一个主机身份。每个容器
# 各自的密钥由 vpn.py 首次启动时生成、存进共享卷，此后跨重启不变——客户端不会再撞上
# REMOTE HOST IDENTIFICATION HAS CHANGED。
rm -f /etc/ssh/ssh_host_*

install -m 0644 \
    /opt/boxctl/common/99-container.conf \
    /etc/ssh/sshd_config.d/99-container.conf

install -m 0755 \
    /opt/boxctl/common/setup.sh \
    /usr/local/bin/setup

install -m 0755 \
    /opt/boxctl/common/vpn-wrapper.sh \
    /usr/local/bin/vpn

install -m 0755 \
    /opt/boxctl/boxctl.sh \
    /usr/local/bin/boxctl

install -m 0755 \
    /opt/boxctl/common/nvm-exec.sh \
    /usr/local/bin/nvm

# 备用触发点，给 .bashrc 那条走不通的场合兜底（login shell 只读 /etc/profile 不读
# .bashrc）。两条都命中也无所谓：boot 幂等且带 flock，第二次只是空转。
install -m 0644 \
    /opt/boxctl/common/profile-boxctl.sh \
    /etc/profile.d/00-boxctl.sh

# 配置带着模板一起进镜像，用户直接 vim 改。开关默认全关，所以没配之前 boot 是空转。
install -m 0644 \
    /opt/boxctl/boxctl.env.template \
    /root/.boxctl.env

# 平台的 PID 1（launch_jupyterlab.sh）会 source /root/.bashrc，所以这里是容器启动时最早
# 能拿到的执行点——服务不必等人登录就能起来。
#
# 必须插在文件最前面，且不能加交互判断，两条都是硬要求：
#   - Debian 的 /root/.bashrc 开头有一句 `[ -z "$PS1" ] && return`，非交互 shell 到那里
#     就返回了，追加在后面的内容一行都不会跑；
#   - 平台那次 source 正是非交互的，`[[ $- == *i* ]]` 会把它挡在门外。
#
# 整段对 stdout 绝对安静：scp/sftp 会话也 source 这个文件，往 stdout 写一个字节就会把
# 传输搞坏。错误一律吞掉——这段跑在平台的启动路径上，不该把平台的启动脚本带崩。
hook="$(mktemp)"
cat > "${hook}" <<'BASHRC'
# boxctl：导出共享卷相关变量，并把「已启用且没在跑」的服务拉起来。
# 位置有讲究：必须在下面那句非交互 early-return 之前，平台启动时 source 本文件才生效。
if command -v boxctl >/dev/null 2>&1; then
    eval "$(boxctl env 2>/dev/null)" || true
    (boxctl boot >/dev/null 2>&1 &) || true
fi

BASHRC
cat /root/.bashrc >> "${hook}" 2>/dev/null || true
install -m 0644 "${hook}" /root/.bashrc
rm -f "${hook}"
