#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -eq 0 ]]; then
    exec just --justfile /opt/ai4pcb/setup.justfile setup
fi

exec just --justfile /opt/ai4pcb/setup.justfile "$@"
