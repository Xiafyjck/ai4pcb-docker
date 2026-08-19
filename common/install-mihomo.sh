#!/usr/bin/env bash
# 装 mihomo（clash 内核）。构建期执行，vpn.py 运行时只查 PATH。
set -Eeuo pipefail

version="${MIHOMO_VERSION:-latest}"

case "$(dpkg --print-architecture)" in
amd64) arch="amd64" ;;
arm64) arch="arm64" ;;
*) echo "unsupported architecture: $(dpkg --print-architecture)" >&2; exit 1 ;;
esac

# 解析 latest 走 releases/latest 的重定向而不是 api.github.com：后者匿名调用有每小时
# 60 次的限额，CI 上撞限额会让构建莫名其妙地失败，而重定向没有限额。
if [[ "${version}" == "latest" ]]; then
    version="$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
        https://github.com/MetaCubeX/mihomo/releases/latest)"
    version="${version##*/}"
fi
[[ -n "${version}" && "${version}" != "null" ]] || { echo "cannot resolve mihomo version" >&2; exit 1; }

# 发布物形如 mihomo-linux-amd64-v1.19.0.gz，解开就是可执行文件本体。
url="https://github.com/MetaCubeX/mihomo/releases/download/${version}/mihomo-linux-${arch}-${version}.gz"
echo "downloading ${url}"
curl -fsSL "${url}" | gzip -d > /usr/local/bin/mihomo
chmod 0755 /usr/local/bin/mihomo
mihomo -v
