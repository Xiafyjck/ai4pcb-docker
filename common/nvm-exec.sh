#!/usr/bin/env bash
set -Eeuo pipefail

export NVM_DIR="${NVM_DIR:-/root/.nvm}"
export NVM_SYMLINK_CURRENT="${NVM_SYMLINK_CURRENT:-true}"

# shellcheck source=/dev/null
source "${NVM_DIR}/nvm.sh"
nvm "$@"
