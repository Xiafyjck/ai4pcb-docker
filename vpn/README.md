# vpn

让**装不了 WireGuard 隧道**的 docker 容器，通过 `wireguard-go` + `wireproxy`
的方式接进内网，开放一个 SSH 端口，同时开出一个 clash 代理口。

有些容器因为宿主机受管控等原因，装不了普通的 WireGuard——它拿不到隧道网卡
（没有 `/dev/net/tun`、没有 `NET_ADMIN` 权限）。同样的原因，clash 也用不了 tun
模式。这里两个都改用纯用户态方案：`wireproxy` 把容器接进内网，`mihomo` 开一个
本地混合代理口。两者都不需要特权。

借助 SSH 的端口复用能力，**只开一个 SSH(22) 端口，就能用上容器里的所有端口**。

作者的情况：多个 docker 实例，相同镜像，共享同一个文件夹。

## 三个服务，一个入口

`vpn.py` 拉起一个 supervisord，由它守护三个进程：

| 服务 | 干什么 | 挂了会怎样 |
|---|---|---|
| `sshd` | 监听 22，是唯一的入站口 | supervisor 自动拉起 |
| `mihomo` | 本地代理 `127.0.0.1:7890`，API `127.0.0.1:9090` | 同上 |
| `wireproxy` | 用户态 wg 隧道，把 wg 地址上的 22 转发到本地 22 | 同上 |

**为什么要 supervisor**：以前 wireproxy 是 `vpn.py` 直接 fork 出去的孤儿进程，
握手失败或被 OOM 杀掉就永远躺平，得等人发现。现在三个服务都 `autorestart`，杀掉
任意一个，几秒内自动回来。

**为什么由 `vpn.py` 拉起 supervisord，而不是写进镜像的 `ENTRYPOINT`**：容器由
平台（学院）启动，它用自己的脚本覆盖了镜像 `ENTRYPOINT`——容器里的 PID 1 实际是
`launch_jupyterlab.sh`。镜像里那套 `docker-entrypoint` + `/etc/supervisor/supervisord.conf`
**一次都不会执行**。所以只能在容器起来之后由本脚本拉起。supervisord 不必是 PID 1，
它照样回收自己的子进程。

同理，凡是重启后必须还在的东西（配置、SSH 主机密钥、geoip 缓存）都只能放在共享卷上，
不能落在容器可写层。

所以**代码和数据是分开的**：`vpn.py` 装在镜像里（`/opt/boxctl/vpn/`，命令名 `vpn`），
它要读写的每一项各自指向共享卷上的一个具体路径，不靠「都在同一个目录下」这条约定：

| 东西 | 怎么给 |
| --- | --- |
| wg 配置 | 位置参数直接给路径 |
| clash 订阅 | `--clash-conf` 给路径 |
| 客户端公钥 | 环境变量 `VPN_PUBKEY` |
| 运行时产物 | 环境变量 `VPN_RUN_DIR` |

都不给时回退到脚本自身所在目录（`wireguard/`、`pcb.pub`、`.run/`），共享卷上直接
`./vpn.py` 的老用法照旧能跑。下面说的「本目录」指的就是这个回退基准。

## 目录结构

```
<回退基准目录>/            # 不指环境变量时的老布局；vpn.py 本身不在这
  <订阅>.yaml           # clash 订阅（换订阅直接换这个文件）
  wireguard/<name>.conf   # 每个容器一份 WireGuard 配置
  pcb.pub                 # 允许登录的客户端公钥
  .run/<name>/            # 运行时产物，本工具自己管，不用动
      supervisord.conf    #   生成的 supervisor 配置
      wireproxy.conf      #   派生的 wg 配置（原配置只读不改）
      ssh/                #   SSH 主机密钥，跨重启保持不变
      mihomo/             #   mihomo 工作目录，geoip 缓存在这
      log/                #   四份日志：supervisord / sshd / mihomo / wireproxy
```

## 用法（在容器里执行）

由 `boxctl` 拉起时路径都从 `/root/.boxctl.env` 翻译过来，不用管。手工执行时自己给
路径、自己 export `VPN_PUBKEY` 和 `VPN_RUN_DIR`。

位置参数是**必填**的 wg 配置（下面都以 `cz4090` 为例，即 `wireguard/cz4090.conf`）。
这里故意不去猜容器名：当多个容器共用同一个文件夹时，得由你说清楚这台用哪份配置，
含糊反而容易连错。

```bash
vpn start cz4090      # 起 sshd + mihomo + wireproxy
vpn status cz4090     # 看三个服务的状态
vpn logs cz4090       # 看 wireproxy 日志
vpn logs cz4090 mihomo   # 看某个服务的日志
vpn restart cz4090
vpn shutdown cz4090   # 全停
```

`up` / `down` / `stop` 作为旧名字保留着，跟 `start` / `shutdown` 等价。

### 两份配置，两种给法

**wg 配置就是那个位置参数**。写名字就到 `wireguard/` 里找，写路径就直接用那份：

```bash
vpn start cz4090                      # = wireguard/cz4090.conf
vpn start /elsewhere/other.conf       # 配置不在标准目录时
```

两种写法都同时确定了**实例名**（路径形式取文件名），运行时目录 `.run/<实例名>/` 和
supervisor 的控制 socket 都挂在它底下。所以上面两条命令分别是 `cz4090` 和 `other`
两个互不干扰的实例。

之所以不做成 `start cz4090 --wg-conf other.conf`，是因为那样就有两个入口指向同一件
事，而且 `cz4090` 和 `other.conf` 可以互相矛盾——名字说用这份、实际加载那份，运行时
目录还挂在名字底下。wg 配置决定“本容器是谁”（内网 IP、运行时目录），只该有一个入口。

**clash 订阅是选项参数**，因为它跟“本容器是谁”无关——所有容器共用同一份订阅：

```bash
vpn start cz4090 --clash-conf /path/to/other.yaml
```

不给就自动认领 **wg 配置同级目录**里唯一的 `*.yaml`，换订阅时不用改命令。那儿有多份 yaml
时它绝不猜，会要求你指明。

另外两个开关：

```bash
vpn start cz4090 --no-clash    # 只要隧道，不起代理
vpn start cz4090 --no-wg       # 只要代理，不起隧道
```

这些命令可以**反复执行都不会出错**。已经在跑时再执行 `start`，它只会重新载入配置
并报告状态。

## 每次容器重启后

`boxctl` 已经接管了这件事：登录时它探测服务在不在，不在就自动 `start`。手动跑也行，
`start` 是幂等的：

```bash
boxctl start vpn      # 走配置文件里的 BOXCTL_WG_CONF
vpn start cz4090      # 或者直接点名实例
```

> `bashsetup` 子命令是 `boxctl` 之前的替代品，往 `~/.bashrc` 写一行 `start`。现在由
> `boxctl boot` 统一负责，不要再用它，两边都写会 start 两次。

首次执行会做两件一次性的事：把容器当前的 SSH 主机密钥收进 `.run/<name>/ssh/`，
以及把 geoip 数据库下载到 `.run/<name>/mihomo/`。此后每次重启都直接复用——**客户端
不会再撞上 `REMOTE HOST IDENTIFICATION HAS CHANGED`**，geoip 也不用重下。

## 客户端配置（你的 Mac）

在 `~/.ssh/config` 里加一段：

```
Host cz
    HostName <wg 地址>           # 本容器在 wg 内网的地址
    User root
    DynamicForward 1080         # 在本机开个 SOCKS 代理 -> 用上 cz 的任意端口
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

然后：

```bash
ssh cz                          # 登进去，同时在本机 127.0.0.1:1080 开出一个代理
```

任何支持 SOCKS 代理的软件，把代理填成 `socks5h://127.0.0.1:1080`，就能访问容器
里的任意服务（jupyter、tensorboard、数据库都行）。

例如访问服务器上的 jupyter 网页（假设它在容器里跑在 8888）：最省事的办法是把这个
端口一对一转发到本机——在上面的 `Host cz` 块里加一行 `LocalForward 8888
127.0.0.1:8888`，然后 `ssh cz`，浏览器直接打开 <http://127.0.0.1:8888> 就是容器
里的 jupyter，不用给浏览器配任何代理。

如果某个软件不支持 SOCKS，同理用一对一转发即可：

```
    LocalForward 8888 127.0.0.1:8888    # 需要几个就往这段里加几行
```

### ssh 细节：为什么只开 22 却能用所有端口

网络上确实只开了 22，但一条 SSH 连接内部可以“套”很多条子通道：

1. `DynamicForward 1080` 在你 Mac 上开了一个本地代理（127.0.0.1:1080）。
2. 某个软件想连容器里的 `8888`，就把请求发给这个本地代理。
3. SSH 把这个请求塞进**已经建好的那条 22 连接**里，捎给容器上的 sshd。
4. sshd（就在容器里）在本地连一下 `127.0.0.1:8888`，再把数据顺着原路带回来。

关键在于：最后连 8888 这一步，是 sshd **在容器内部**发起的，属于“往外连”，所以
根本不需要单独开放 8888 这个入口。整条 wg 隧道从头到尾只搬运 22 的流量，其它所有
端口都是“藏”在这条连接里一起走的。代价就是两头各开一个本地代理端口——客户端一个
（`DynamicForward`/`LocalForward`），服务器那头由 sshd 临时开到目标端口的连接。

## 用容器里的代理

`start` 会写一份 `/etc/profile.d/vpn-proxy.sh`，**新开的 shell** 自动带上
`http_proxy` 等变量。当前这个 shell 立即生效：

```bash
source /etc/profile.d/vpn-proxy.sh
```

两个细节：

- 它**先探测端口是否在监听，代理确实活着才导出**。镜像原本无条件把
  `HTTP_PROXY` 指向 `127.0.0.1:7890`，可 mihomo 是容器起来之后才拉起的——在那之前
  每一次 `curl`/`pip`/`npm` 都会撞上一个不存在的代理。所以镜像里那份
  `ai4pcb-proxy.sh` 连同那组 ENV 一起删掉了，代理变量只由这里出。
- `no_proxy` 里会自动带上 wg 网段。不加的话，从容器访问内网其它
  机器会被 clash 按规则送出国，这是“隧道明明通了却连不上内网”的典型元凶。

切节点、看延迟走 API：`curl 127.0.0.1:9090/proxies`。订阅文件本身一字未改——API
地址是用 mihomo 的 `-ext-ctl` 命令行参数注入的。

## 对镜像的要求

`vpn.py` 假定镜像里已经有这三样，都由本仓库的 Dockerfile 保证（`boxctl doctor` 会查）：

- `wireproxy`（构建期编译进 `/usr/local/bin`，换平台跟着构建平台走）
- `mihomo`
- `supervisor`（apt 包）

以前 `wireproxy` 是预编译二进制搁在共享卷的 `bin/` 里，换平台就得手工重编一次；
现在这个目录已经删了。

## 排错

**先看状态**：`vpn status cz4090`。三个服务都该是 `RUNNING`。

`start` 结束时会自我核对一遍：状态是否全 `RUNNING`，以及 22 和 7890 是不是真的
由 supervisor 管的那两个进程在监听。supervisor 只保证进程活着，不保证它干成了活
——mihomo 绑不上端口时只记一行错误日志、进程照活，光看状态会以为一切正常，实际
代理还是旧进程在提供。核对不通过会直接报 warning 并退出非零。

**端口被占**：`start` 会先清理不受 supervisor 管的同名进程——手工起过一次 mihomo、
或 supervisord 被 `kill -9` 后留下的孤儿，都属于这种。sshd 只杀监听进程，已经建立
的会话不受影响，执行 `start` 的人不会被自己踢下线。

**wireproxy 日志里成片的 `Cannot forward traffic: ... use of closed network
connection`**：这是噪音，不是故障。每条 SSH 连接正常结束时它都会记一条。判断隧道
通不通看 `sshd.log` 里有没有 `Accepted publickey`——有就是通的。
