#!/usr/bin/env bash
# /usr/local/bin/nvm —— 让 nvm 在非交互场景下也能敲。
#
# nvm 本体是 shell 函数，只有 source 过 nvm.sh 的 shell 里才存在。这个包装只对
# install / ls / which 这类「做完就完」的子命令有意义；`nvm use` 改的是本进程的
# PATH，出了这个包装就没了，切版本仍然要在自己的 shell 里 source。
set -Eeuo pipefail
export NVM_DIR="${NVM_DIR:-/root/.nvm}"
# shellcheck disable=SC1091
source "${NVM_DIR}/nvm.sh"
nvm "$@"
