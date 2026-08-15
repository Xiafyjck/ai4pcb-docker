#!/usr/bin/env bash
set -Eeuo pipefail

mihomo_version="${MIHOMO_VERSION:-latest}"

case "$(uname -m)" in
    x86_64)
        mihomo_platform="linux-amd64-compatible"
        ;;
    *)
        echo "Unsupported Mihomo architecture: $(uname -m)" >&2
        exit 1
        ;;
esac

temp_dir="$(mktemp -d)"
trap 'rm -rf -- "$temp_dir"' EXIT

if [[ "${mihomo_version}" == "latest" ]]; then
    mihomo_release_url="$(
        curl --proto '=https' --tlsv1.2 -LsS \
            -o /dev/null \
            -w '%{url_effective}' \
            https://github.com/MetaCubeX/mihomo/releases/latest
    )"
    mihomo_tag="${mihomo_release_url##*/}"
else
    mihomo_tag="${mihomo_version}"
    [[ "${mihomo_tag}" == v* ]] || mihomo_tag="v${mihomo_tag}"
fi

[[ "${mihomo_tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
asset="mihomo-${mihomo_platform}-${mihomo_tag}.gz"

curl --proto '=https' --tlsv1.2 -fsSL \
    "https://api.github.com/repos/MetaCubeX/mihomo/releases/tags/${mihomo_tag}" \
    -o "${temp_dir}/release.json"

asset_url="$(
    jq -er --arg asset "${asset}" \
        '.assets[] | select(.name == $asset) | .browser_download_url' \
        "${temp_dir}/release.json"
)"
asset_digest="$(
    jq -er --arg asset "${asset}" \
        '.assets[] | select(.name == $asset) | .digest' \
        "${temp_dir}/release.json"
)"

[[ "${asset_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
mihomo_sha256="${asset_digest#sha256:}"

curl --proto '=https' --tlsv1.2 -fsSL \
    "${asset_url}" \
    -o "${temp_dir}/${asset}"

printf '%s  %s\n' \
    "${mihomo_sha256}" \
    "${temp_dir}/${asset}" \
    | sha256sum -c -

gzip -dc "${temp_dir}/${asset}" > "${temp_dir}/mihomo"
install -m 0755 "${temp_dir}/mihomo" /usr/local/bin/mihomo
mihomo -v
