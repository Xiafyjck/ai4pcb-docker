set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default: check

# 推之前跑一遍：镜像构建在 CI，语法错误在这里发现比等 CI 跑完便宜得多。
check:
    for f in boxctl/boxctl.sh boxctl/services/*.sh common/*.sh; do bash -n "$f"; done
    sh -n common/profile-boxctl.sh
    python3 -m py_compile vpn/vpn.py fsferry/src/fsferry/*.py
    @echo "ok"

# 本地构建。日常不用——推上去由 CI 构建并推 GHCR。这条留给调 Dockerfile 时用，
# 在 arm64 机器上会走 amd64 模拟，很慢。
build variant="cu132-devel-ubuntu2404" platform="linux/amd64":
    test -f "images/{{variant}}/Dockerfile"
    docker buildx build \
      --platform "{{platform}}" \
      --pull \
      --load \
      -f "images/{{variant}}/Dockerfile" \
      -t "ai4pcb-docker:{{variant}}" \
      .
