# ai4pcb-docker

用于本地或 GitHub Actions 按需构建 AI4PCB 云端开发镜像。

## 已有变体

| 变体 | 基础镜像 | 用途 |
| --- | --- | --- |
| `cu132-devel-ubuntu2404` | `nvidia/cuda:13.2.1-devel-ubuntu24.04` | CUDA/C++ 开发，包含 nvcc 和构建工具 |
| `cu132-runtime-ubuntu2404` | `nvidia/cuda:13.2.1-runtime-ubuntu24.04` | 更小的 CUDA 运行环境 |

所有变体均包含：

- root 公钥 SSH，仅允许公钥登录
- 构建时获取最新稳定 NVM、最新 Node.js 24.x LTS 及其配套 npm
- 构建时获取最新稳定 Mihomo，由 Supervisor 自动启动和重启
- 官方安装脚本安装的 `uv`、固定版本的 `just`、`vim`
- Git、curl、wget、rsync
- ping、ip/ss、dig、nc、mtr、traceroute、tcpdump、socat
- 常用诊断和压缩工具
- `setup` 命令，用于安装经常变化的个人开发工具

不预装 Conda、PyTorch 或其他项目级 Python 包。

## 本地使用

列出变体：

```bash
just variants
```

构建默认开发镜像：

```bash
just build
```

构建指定变体：

```bash
just build cu132-runtime-ubuntu2404
```

启动、复制公钥并连接：

```bash
just run
just key
just ssh
```

登录后安装可选开发工具：

```bash
setup
```

## GitHub Actions 按需构建

1. 将仓库推送到 GitHub。
2. 进入 **Actions → Build container images → Run workflow**。
3. 选择单个变体或 `all`。
4. 构建完成后从 GHCR 拉取：

```bash
docker pull ghcr.io/OWNER/ai4pcb-docker:cu132-devel-ubuntu2404
```

启动云端容器：

```bash
docker run -d \
  --name ai4pcb-dev \
  --gpus all \
  --shm-size=8g \
  -p 2222:22 \
  -e MIHOMO_CONFIG=/run/mihomo/config.yaml \
  -v /data/ai4pcb/mihomo/config.yaml:/run/mihomo/config.yaml:ro \
  -v /data/ai4pcb/mihomo-state:/var/lib/mihomo \
  -v /data/ai4pcb/codex:/root/.codex \
  -v /data/workspace:/workspace \
  ghcr.io/OWNER/ai4pcb-docker:cu132-devel-ubuntu2404
```

在云服务器宿主机复制公钥：

```bash
docker cp ~/.ssh/id_ed25519.pub ai4pcb-dev:/run/ssh/root.pub
```

然后连接：

```bash
ssh -p 2222 root@SERVER_IP
```

## Mihomo 与持久化

镜像内只包含 Mihomo 二进制、启动脚本和代理环境变量，不包含私密
`config.yaml`。Mihomo 默认读取环境变量指定的路径：

```text
MIHOMO_CONFIG=/etc/mihomo/config.yaml
MIHOMO_HOME=/var/lib/mihomo
```

学院平台如果支持全局环境变量，可以把 `MIHOMO_CONFIG` 改为实际挂载路径。
启动脚本会等待该文件出现，然后自动运行 Mihomo；不再需要 tmux。配置建议使用：

```yaml
mixed-port: 7890
```

镜像内默认代理变量均指向本机 7890 端口：

```text
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
ALL_PROXY=socks5h://127.0.0.1:7890
```

建议分别持久化以下目录或文件：

| 容器路径 | 内容 |
| --- | --- |
| `$MIHOMO_CONFIG` | 私密 Mihomo 配置，只读挂载 |
| `/var/lib/mihomo` | Mihomo 数据、Geo 数据和缓存 |
| `/root/.codex` | Codex 配置和登录状态 |
| `/workspace` | 项目文件 |

查看服务状态和日志：

```bash
docker exec ai4pcb-dev supervisorctl status
docker logs -f ai4pcb-dev
```

验证预装版本：

```bash
docker exec ai4pcb-dev bash -lc \
  'node -v; npm -v; nvm --version; mihomo -v'
```

私有 GHCR 镜像需要先登录：

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u OWNER --password-stdin
```

Token 只需要 `read:packages` 权限。

## 添加新变体

1. 复制 `images/` 下最接近的目录并修改 Dockerfile。
2. 将新目录名加入 `.github/workflows/build-images.yml` 的 `variant.options`。
3. 执行 `just build 新变体名` 本地验证。
4. 推送后通过 Actions 按需发布。

发布标签同时包含固定提交版本，例如：

```text
cu132-devel-ubuntu2404
cu132-devel-ubuntu2404-sha-1a2b3c4
```

前者方便更新，后者方便回滚。
