# ai4pcb-docker

用于本地或 GitHub Actions 按需构建 AI4PCB 云端开发镜像。

| 变体 | 基础镜像 | 用途 |
| --- | --- | --- |
| `cu132-devel-ubuntu2404` | `nvidia/cuda:13.2.1-devel-ubuntu24.04` | CUDA/C++ 开发，包含 nvcc 和构建工具 |

镜像包含：

- `uv`、`just`、Git、curl、wget、rsync
- ping、ip/ss、dig、nc、mtr、traceroute、tcpdump、socat 等诊断工具
- `wireproxy`（构建期编译）、`mihomo`、`supervisor`、`openssh-server`
- `nvm` + Node.js latest（`nvm` 命令有个包装，`install`/`ls` 能直接敲；`use` 得在自己的
  shell 里 source，它改的是本进程的 PATH）
- `vpn`：用户态 WireGuard 接入 + clash 代理，见 [vpn/README.md](vpn/README.md)
- `h200` / `fsferry-agent`：共享文件系统上的命令摆渡，见 [fsferry/README.md](fsferry/README.md)
- `boxctl`：统一管理上面这些服务
- `setup` 命令，用于安装经常变化的个人开发工具

不预装 Conda、PyTorch 或其他项目级 Python 包。

## 平台约束

这个镜像是给**学院平台**用的，那里有三件事跟普通 `docker run` 不一样：

1. **启动权不在我们手里**。平台用自己的脚本覆盖镜像 `ENTRYPOINT`，容器里的 PID 1 是
   `launch_jupyterlab.sh`。所以镜像刻意不声明 `ENTRYPOINT`——写了也一次都不会执行，
   留着只会让人以为服务是自启的。
2. **容器会定时停机重启**，靠周期性快照保存状态。`/root`、`/workspace` 跨重启是在的，
   但刚写的东西可能还没进快照。
3. **服务得在容器起来之后自己拉起**。这是 `boxctl` 存在的理由。

`boxctl` 本身**不是守护进程**，是跑完就退的一次性命令。守护是分层的：

- **一个容器生命周期之内**，supervisord 守着 sshd / mihomo / wireproxy，三个都 `autorestart`，
  杀掉任意一个几秒内回来。`boxctl` 不参与。
- **跨重启**，supervisord 随容器一起没了，得有人重新拉起。启动权不在我们手里，但
  `launch_jupyterlab.sh` 会 `source /root/.bashrc`——**那就是容器启动时最早的执行点**，
  服务不必等人登录。

所以钩子插在 `/root/.bashrc` 的**最前面**，而且不带交互判断。两条都是硬要求：

- Debian 的 `/root/.bashrc` 开头有一句 `[ -z "$PS1" ] && return`，非交互 shell 到那里就
  返回了，**追加在后面的内容一行都不会跑**；
- 平台那次 source 正是非交互的，`[[ $- == *i* ]]` 这类判断会把它挡在门外。

这段对 stdout 绝对安静：`scp`/`sftp` 会话也 source 这个文件，往 stdout 写一个字节就会把
传输搞坏。错误也一律吞掉——它跑在平台的启动路径上，boxctl 出问题不该把平台带崩。

`/etc/profile.d/00-boxctl.sh` 是备用触发点，给 login shell 只读 `/etc/profile` 不读
`.bashrc` 的场合兜底。两条都命中也无所谓：`boxctl boot` 幂等且带 `flock`，第二次只是空转。

镜像里也**刻意不设 `HTTP_PROXY` 等环境变量**。镜像 ENV 是 PID 1 及其所有后代的既成
事实，而 mihomo 要等容器起来之后才被拉起——在那之前每一次 `curl`/`pip`/`npm` 都会撞上
一个不存在的代理。代理变量只由 `vpn.py` 在探测到端口确实在监听之后写的
`/etc/profile.d/vpn-proxy.sh` 出。

## 代码在镜像，配置在共享卷

| 项 | 归属 | 位置 |
| --- | --- | --- |
| 工具链、`wireproxy`/`mihomo`/`supervisor` | 镜像 | Dockerfile |
| `vpn.py`、`fsferry`、`boxctl` 代码 | 镜像 | `/opt/boxctl/` |
| 共享卷路径、实例名、开关 | 用户 | `/root/.boxctl.env` |
| wg 配置、clash 订阅、客户端公钥 | 用户 | 共享卷，逐项在配置里指到文件 |
| 运行时产物（主机密钥、geoip 缓存、日志） | 用户 | 共享卷 `$BOXCTL_STATE_DIR` |
| fsferry 通道目录 | 用户 | 共享卷 `$BOXCTL_FSFERRY_DIR` |

分开的理由：容器可写层重启即丢。SSH 主机密钥每次重生会让客户端撞上
`REMOTE HOST IDENTIFICATION HAS CHANGED`，geoip 数据库每次都得重下 8 MB。所以凡是
「重启后必须还在」的东西都只能落在共享卷上。

wg 私钥、SSH 主机密钥、机场订阅一律**不进仓库、不进镜像**，`.gitignore` 和
`.dockerignore` 都挡了一道。

## boxctl

```
boxctl start   [all|vpn|fsferry]   # 启动；已在跑的跳过
boxctl stop    [all|vpn|fsferry]
boxctl restart [all|vpn|fsferry]   # 硬重启，重新加载配置
boxctl status  [all|vpn|fsferry]
boxctl logs    <vpn|fsferry> [子服务]
boxctl boot                        # 幂等，只拉起「已启用且没在跑」的；登录时自动调用
boxctl env                         # 打印要 export 的 shell 片段，供 eval
boxctl config                      # 打印生效配置并校验路径
boxctl doctor                      # 依赖自检
```

`boot` 的判据是**服务真的在不在**（supervisor 控制 socket + 端口在监听），不是「这个容器
生命周期跑过没有」。后者要维护状态文件，还漏掉「服务被 OOM 全灭但 PID 1 没变」这一类。
多个 shell 同时开时用 `flock` 防抖，只有一个会真的去 start。

`boxctl` 这层刻意跟 ai4pcb 脱钩——它解决的是「容器启动权不在自己手里、重启后服务要自己
回位」这个通用问题。加服务就在 `boxctl/services/` 下加一个文件，定义
`<名字>_enabled` / `_running` / `_start` / `_stop` / `_restart` / `_status` / `_logs` / `_env`
八个函数，文件名的数字前缀决定 `start all` 的顺序。

## 配置

配置就一个文件：`/root/.boxctl.env`，镜像自带带注释的模板，直接 `vim` 改，改完
`boxctl config` 校验一遍。**没有 `boxctl config set`**——多一个入口就多一套优先级规则，
以及出错时「到底哪个生效了」的困惑。

字段全部用 `BOXCTL_*` 一套前缀，`boxctl` 在拉起工具时翻译成工具自己认的变量名
（`BOXCTL_SSH_PUBKEY` → `VPN_PUBKEY`，`BOXCTL_FSFERRY_DIR` → `FSFERRY_DIR`）。工具单独拿出去
用不受影响。

```bash
BOXCTL_ENABLE_VPN=1
BOXCTL_ENABLE_FSFERRY=0

BOXCTL_STATE_DIR=/<共享卷>/<你的目录>/.boxctl
BOXCTL_SSH_PUBKEY=/<共享卷>/<你的目录>/pcb.pub

BOXCTL_WG_CONF=/<共享卷>/<你的目录>/vpn/cz4090.conf
BOXCTL_CLASH_CONF=/<共享卷>/<你的目录>/vpn/<订阅>.yaml

BOXCTL_FSFERRY_DIR=/<快卷>/<你的目录>/fsferry
```

**每一项都直接指向一个具体路径**，不靠「都在同一个目录下」这类约定——那是 `vpn.py` 早期
把代码和数据放在一起时的形状，不该往上传染。

`BOXCTL_WG_CONF` 同时决定「本容器是谁」：实例名取文件名（`cz4090.conf` → `cz4090`），运行
时目录和 supervisor 的控制 socket 都挂在那个名字底下。不再单列实例名——两处分开填迟早会
矛盾：名字说用这份、实际加载那份。

`BOXCTL_STATE_DIR` 是运行时产物的根，各服务在底下自建子目录。必须在共享卷上：SSH 主机密钥
要跨重启保持不变，否则客户端每次都撞上 `REMOTE HOST IDENTIFICATION HAS CHANGED`。

boxctl **只管服务**。改 PATH、缓存目录、工具链开关这些是你自己的事，写进 `/root/.bashrc`
就行，它跨重启在（换镜像才会回到镜像里那份）。

开关默认全关，所以配置填好之前登录不会有任何副作用。

## 首次使用

容器起来后：

```bash
vim /root/.boxctl.env     # 填各个文件路径，打开需要的开关
boxctl config             # 校验：路径存不存在、哪些字段还空着
exec bash                 # 重新登录，引导链条接管
boxctl status             # 三个服务应该都是 RUNNING
```

此后每次平台重启容器，`launch_jupyterlab.sh` source `.bashrc` 时就自动拉起了，不用等人
登录。手动也行，`start` 是幂等的：

```bash
boxctl start vpn
boxctl restart vpn        # 改了配置要重新加载时
boxctl logs vpn sshd      # 看某个子服务的日志
```

## 构建

推到 GitHub 后由 CI 构建并推 GHCR：**Actions → Build container images → Run workflow**。

推之前本地跑一遍语法检查，比等 CI 跑完再发现拼错便宜：

```bash
just check
```

拉镜像（私有 GHCR 要先 `docker login`，token 只需 `read:packages`）：

```bash
docker pull ghcr.io/OWNER/ai4pcb-docker:cu132-devel-ubuntu2404
```

发布标签同时包含固定提交版本，前者方便更新，后者方便回滚：

```text
cu132-devel-ubuntu2404
cu132-devel-ubuntu2404-sha-1a2b3c4
```

调 Dockerfile 时也可以本地构建，但 arm64 机器上要走 amd64 模拟，很慢：

```bash
just build
```
