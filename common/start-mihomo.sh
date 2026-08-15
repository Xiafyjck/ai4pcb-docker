#!/usr/bin/env bash
set -Eeuo pipefail

config="${MIHOMO_CONFIG:-/etc/mihomo/config.yaml}"
state_dir="${MIHOMO_HOME:-/var/lib/mihomo}"
poll_interval="${MIHOMO_CONFIG_POLL_INTERVAL:-5}"

if [[ "${config}" != /* || "${state_dir}" != /* ]]; then
    echo "MIHOMO_CONFIG and MIHOMO_HOME must be absolute paths" >&2
    exit 64
fi

install -d -m 0700 "${state_dir}"

if [[ ! -s "${config}" ]]; then
    echo "Waiting for Mihomo config at ${config} ..."
fi

until [[ -s "${config}" ]]; do
    sleep "${poll_interval}"
done

echo "Mihomo config ready; starting proxy."
exec /usr/local/bin/mihomo -d "${state_dir}" -f "${config}"
