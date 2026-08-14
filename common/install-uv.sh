#!/usr/bin/env bash
set -Eeuo pipefail

uv_version="${UV_VERSION:-0.12.4}"
install_dir="${UV_INSTALL_DIR:-/usr/local/bin}"

case "$(uname -m)" in
    x86_64)
        uv_target="x86_64-unknown-linux-gnu"
        ;;
    aarch64 | arm64)
        uv_target="aarch64-unknown-linux-gnu"
        ;;
    *)
        echo "Unsupported architecture: $(uname -m)" >&2
        exit 1
        ;;
esac

archive="uv-${uv_target}.tar.gz"
release_url="https://releases.astral.sh/github/uv/releases/download/${uv_version}"
temp_dir="$(mktemp -d)"
trap 'rm -rf -- "$temp_dir"' EXIT

curl --proto '=https' --tlsv1.2 -fsSL \
    "${release_url}/${archive}" \
    -o "${temp_dir}/${archive}"
curl --proto '=https' --tlsv1.2 -fsSL \
    "${release_url}/${archive}.sha256" \
    -o "${temp_dir}/${archive}.sha256"

(
    cd "$temp_dir"
    sha256sum -c "${archive}.sha256"
)

tar -xzf "${temp_dir}/${archive}" -C "$temp_dir"
install -d -m 0755 "$install_dir"
install -m 0755 "${temp_dir}/uv-${uv_target}/uv" "${install_dir}/uv"
install -m 0755 "${temp_dir}/uv-${uv_target}/uvx" "${install_dir}/uvx"

if ! ldd "${install_dir}/uv" 2>&1 | grep -q 'libc\.so'; then
    echo "Expected a dynamically linked GNU uv binary" >&2
    exit 1
fi
