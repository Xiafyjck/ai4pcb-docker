#!/usr/bin/env bash
set -Eeuo pipefail

nvm_version="${NVM_VERSION:-latest}"
node_version="${NODE_VERSION:-24}"

export NVM_DIR="${NVM_DIR:-/root/.nvm}"
export NVM_SYMLINK_CURRENT="${NVM_SYMLINK_CURRENT:-true}"
export PROFILE="${PROFILE:-/root/.bashrc}"

if [[ "${nvm_version}" == "latest" ]]; then
    nvm_release_url="$(
        curl --proto '=https' --tlsv1.2 -LsS \
            -o /dev/null \
            -w '%{url_effective}' \
            https://github.com/nvm-sh/nvm/releases/latest
    )"
    nvm_tag="${nvm_release_url##*/}"
else
    nvm_tag="${nvm_version}"
    [[ "${nvm_tag}" == v* ]] || nvm_tag="v${nvm_tag}"
fi

[[ "${nvm_tag}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]

curl --proto '=https' --tlsv1.2 -LsSf -o- \
    "https://raw.githubusercontent.com/nvm-sh/nvm/${nvm_tag}/install.sh" \
    | bash

# shellcheck source=/dev/null
source "${NVM_DIR}/nvm.sh"
nvm install "${node_version}"
nvm alias default "${node_version}"
nvm use --silent default

nvm --version
node --version
npm --version
test -x "${NVM_DIR}/current/bin/node"
