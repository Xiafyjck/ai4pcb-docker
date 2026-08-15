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
install -d -m 0755 /etc/mihomo /etc/supervisor /var/log/supervisor
install -d -m 0700 /var/lib/mihomo
rm -f /etc/ssh/ssh_host_*

install -m 0644 \
    /opt/ai4pcb/common/99-container.conf \
    /etc/ssh/sshd_config.d/99-container.conf

install -m 0755 \
    /opt/ai4pcb/common/docker-entrypoint.sh \
    /usr/local/bin/docker-entrypoint

install -m 0755 \
    /opt/ai4pcb/common/start-mihomo.sh \
    /usr/local/bin/start-mihomo

install -m 0755 \
    /opt/ai4pcb/common/nvm-exec.sh \
    /usr/local/bin/nvm

install -m 0644 \
    /opt/ai4pcb/common/supervisord.conf \
    /etc/supervisor/supervisord.conf

install -m 0644 \
    /opt/ai4pcb/common/proxy-env.sh \
    /etc/profile.d/ai4pcb-proxy.sh

install -m 0755 \
    /opt/ai4pcb/common/setup.sh \
    /usr/local/bin/setup
