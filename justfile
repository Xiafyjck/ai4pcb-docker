set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default: variants

default_variant := "cu132-devel-ubuntu2404"
default_container := "ai4pcb-dev"
default_port := "2222"
default_key := env_var("HOME") + "/.ssh/id_ed25519.pub"

variants:
    @find images -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort

build variant=default_variant platform="linux/amd64":
    test -f "images/{{variant}}/Dockerfile"
    docker buildx build \
      --platform "{{platform}}" \
      --pull \
      --build-arg "TOOL_REFRESH=$(date -u +%Y%m%d%H%M%S)" \
      --load \
      -f "images/{{variant}}/Dockerfile" \
      -t "ai4pcb-docker:{{variant}}" \
      .

run variant=default_variant name=default_container port=default_port:
    docker run -d \
      --name "{{name}}" \
      --gpus all \
      --shm-size=8g \
      -p "{{port}}:22" \
      "ai4pcb-docker:{{variant}}"

key name=default_container key=default_key:
    test -s "{{key}}"
    docker cp "{{key}}" "{{name}}:/run/ssh/root.pub"

ssh port=default_port:
    ssh -p "{{port}}" root@127.0.0.1

shell name=default_container:
    docker exec -it "{{name}}" bash

setup name=default_container:
    docker exec -it "{{name}}" setup

logs name=default_container:
    docker logs -f "{{name}}"

stop name=default_container:
    docker stop "{{name}}"

start name=default_container:
    docker start "{{name}}"

inspect name=default_container:
    docker exec "{{name}}" bash -lc \
      'nvcc --version 2>/dev/null || true; node --version; npm --version; mihomo -v; uv --version; just --version; curl --version | head -1'
