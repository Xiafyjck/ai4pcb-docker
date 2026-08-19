#!/usr/bin/env bash
# 装 nvm 和 Node.js。构建期执行。
set -Eeuo pipefail

nvm_version="${NVM_VERSION:-v0.40.6}"
node_version="${NODE_VERSION:-node}"     # "node" 是 nvm 里 latest 的别名

export NVM_DIR=/root/.nvm
export NVM_SYMLINK_CURRENT=true          # 维护 $NVM_DIR/current symlink，好让 PATH 写死

install -d -m 0755 "${NVM_DIR}"
curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/${nvm_version}/install.sh" | bash

# nvm 是 shell 函数不是可执行文件，用之前必须 source。
# shellcheck disable=SC1091
source "${NVM_DIR}/nvm.sh"

nvm install "${node_version}"
nvm alias default "${node_version}"

node -v
npm -v
