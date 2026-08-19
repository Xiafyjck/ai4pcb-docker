#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -eq 0 ]]; then
    exec just --justfile /opt/boxctl/setup.justfile setup
fi

exec just --justfile /opt/boxctl/setup.justfile "$@"
