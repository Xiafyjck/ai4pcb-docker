# ai4pcb-docker

用于本地或 GitHub Actions 按需构建 AI4PCB 云端开发镜像。

## 已有变体

| 变体 | 基础镜像 | 用途 |
| --- | --- | --- |
| `cu132-devel-ubuntu2404` | `nvidia/cuda:13.2.1-devel-ubuntu24.04` | CUDA/C++ 开发，包含 nvcc 和构建工具 |
| `cu132-runtime-ubuntu2404` | `nvidia/cuda:13.2.1-runtime-ubuntu24.04` | 更小的 CUDA 运行环境 |

所有变体均包含：

- root 公钥 SSH，仅允许公钥登录
- GNU/glibc 版 `uv`、`just`、`vim`
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
