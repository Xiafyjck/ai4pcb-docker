# Global proxy defaults for root SSH and login shells.
MIHOMO_CONFIG="${MIHOMO_CONFIG:-/etc/mihomo/config.yaml}"
MIHOMO_HOME="${MIHOMO_HOME:-/var/lib/mihomo}"
export MIHOMO_CONFIG MIHOMO_HOME

_ai4pcb_mihomo_port="${MIHOMO_PROXY_PORT:-7890}"
case "${_ai4pcb_mihomo_port}" in
    '' | *[!0-9]*)
        ;;
    *)
        if command -v ss >/dev/null 2>&1 \
            && ss -H -ltn "sport = :${_ai4pcb_mihomo_port}" 2>/dev/null \
                | grep -q .; then
            HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:${_ai4pcb_mihomo_port}}"
            HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:${_ai4pcb_mihomo_port}}"
            ALL_PROXY="${ALL_PROXY:-socks5h://127.0.0.1:${_ai4pcb_mihomo_port}}"
            NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"

            http_proxy="${http_proxy:-${HTTP_PROXY}}"
            https_proxy="${https_proxy:-${HTTPS_PROXY}}"
            all_proxy="${all_proxy:-${ALL_PROXY}}"
            no_proxy="${no_proxy:-${NO_PROXY}}"

            export HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
            export http_proxy https_proxy all_proxy no_proxy
        fi
        ;;
esac
unset _ai4pcb_mihomo_port
