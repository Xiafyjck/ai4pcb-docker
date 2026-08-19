#!/usr/bin/env bash
# /usr/local/bin/vpn —— 转调镜像里那份 vpn.py。
#
# 直接用 python3 而不是 uv run：vpn.py 零依赖纯标准库，走 uv 只会在网络还没通的时候
# 多一层「解释器要先下载」的失败可能——而它恰恰是用来把网络弄通的那个工具。
set -Eeuo pipefail
exec python3 "${BOXCTL_HOME:-/opt/boxctl}/vpn/vpn.py" "$@"
