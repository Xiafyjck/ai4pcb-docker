# Global proxy defaults for root SSH and login shells.
MIHOMO_CONFIG="${MIHOMO_CONFIG:-/etc/mihomo/config.yaml}"
MIHOMO_HOME="${MIHOMO_HOME:-/var/lib/mihomo}"
HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}"
HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"
ALL_PROXY="${ALL_PROXY:-socks5h://127.0.0.1:7890}"
NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"

http_proxy="${http_proxy:-${HTTP_PROXY}}"
https_proxy="${https_proxy:-${HTTPS_PROXY}}"
all_proxy="${all_proxy:-${ALL_PROXY}}"
no_proxy="${no_proxy:-${NO_PROXY}}"

export MIHOMO_CONFIG MIHOMO_HOME
export HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
export http_proxy https_proxy all_proxy no_proxy
