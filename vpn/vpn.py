#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""把受限容器接入 WireGuard 内网、开出 clash 代理，并开放 SSH。

适用场景：容器没有 /dev/net/tun、没有 NET_ADMIN（HPC 计算节点、受限 K8s），
装不了普通 WireGuard，clash 也用不了 tun 模式。这里用 wireproxy 在纯用户态跑
WireGuard，用 mihomo 开一个本地 mixed 代理口，两者都不需要特权。三个进程
（sshd / mihomo / wireproxy）统一交给 supervisord 守护，挂了自动拉起。

为什么由本脚本拉起 supervisord，而不是让镜像的 ENTRYPOINT 干这件事：容器由平台
（学院）启动，它用自己的脚本覆盖了镜像 ENTRYPOINT——PID 1 是
launch_jupyterlab.sh，镜像里那套 docker-entrypoint + /etc/supervisor/supervisord.conf
一次都不会执行。所以只能在容器起来之后，由本脚本把 supervisord 作为普通后台
守护进程拉起。supervisord 不必是 PID 1：它照样会回收自己的子进程。

同理，凡是重启后必须存在的东西（配置、主机密钥、geoip 缓存）都只能放在共享卷上。
本脚本自身装在镜像里，要读写的路径逐项用环境变量指出（VPN_PUBKEY / VPN_RUN_DIR），
wg 配置和 clash 订阅直接给路径——代码和数据分开，见下方 BASE。

对外契约（镜像里装成 vpn 命令）：
    vpn start <wg>         起 sshd + mihomo + wireproxy
    vpn shutdown <wg>      全停
    vpn restart <wg>
    vpn status <wg>
    vpn logs <wg> [svc]    跟踪某个服务的日志（默认 wireproxy）
    vpn bashsetup <wg>     旧的开机自启写法，已被 boxctl 取代，别再用

<wg> 必填，可以是 wireguard/ 下的名字（cz4090），也可以是任意 .conf 路径。它同时
决定了实例名——运行时目录 .run/<实例名>/ 和 supervisor 的控制 socket 都挂在它底下。
刻意不猜 hostname：多个容器共享同一份文件夹时，必须由调用者指明本容器用哪份配置，
含糊比出错更危险。

wg 配置是每容器一份（各自的内网 IP），决定“本容器是谁”，所以做成位置参数、只留一个
入口；clash 订阅则是所有容器共用一份，跟身份无关，所以做成 --clash-conf。必须显式给路径：
早先那套“认领目录里唯一的 *.yaml”是代码和数据同处一个文件夹时的产物，多放一份订阅就会
突然罢工。

所有动作幂等：重复 start 收敛到“运行中”，可安全放进每次容器启动的引导里。
"""
import argparse
import fcntl
import ipaddress
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# 只暴露 SSH。容器内其余端口由客户端经这条 SSH 连接复用触达，故这里是常量而非
# 可配置清单——多开入站端口只会扩大受限容器的暴露面，且 SSH 已覆盖全部需求。
SSH_PORT = 22

# mihomo 的 RESTful API：只监听回环，用来切节点、看延迟。原始订阅里没有这一项，
# 而 mihomo 支持用 -ext-ctl 命令行覆盖，于是订阅文件可以保持一字不动。
CLASH_API = "127.0.0.1:9090"

# 本脚本装在镜像里，而它要读写的东西必须落在共享卷上：容器可写层重启即丢，SSH 主机密钥
# 每次重生会让客户端撞上 REMOTE HOST IDENTIFICATION HAS CHANGED，geoip 也得重下。
#
# 每一项都能单独用环境变量指到一个具体路径，不靠「都在同一个目录下」这条约定：那是本工具
# 早期把代码和数据放在一起时的形状，装进镜像之后就只剩误导了。
#
#   VPN_PUBKEY    允许登录的客户端公钥
#   VPN_RUN_DIR   运行时产物的根（主机密钥、geoip 缓存、日志、生成的配置）
#
# wg 配置和 clash 订阅本来就能直接给路径（位置参数 / --clash-conf），不另设变量。
#
# 都不设时回退到脚本自身所在目录——共享卷上直接 ./vpn.py 的老用法照旧能跑。回退取脚本
# 目录而非 cwd，因为引导脚本会从任意目录调用它。
BASE = Path(__file__).resolve().parent
WG_DIR = BASE / "wireguard"
PUBKEY = Path(os.environ.get("VPN_PUBKEY") or BASE / "pcb.pub")
RUN_DIR = Path(os.environ.get("VPN_RUN_DIR") or BASE / ".run")

SERVICES = ("sshd", "mihomo", "wireproxy")

# 代理变量的落点。镜像不再自带任何 profile.d 代理脚本，这是唯一的一份。
PROXY_PROFILE = Path("/etc/profile.d/vpn-proxy.sh")

PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def log(msg: str) -> None:
    print(f"[vpn] {msg}", file=sys.stderr)


def die(msg: str) -> None:
    print(f"[vpn] error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- 配置定位

def resolve_wg_conf(a) -> Path:
    """定位本容器的 wg 配置；不存在则连同可选名一起报错退出。

    列出可用名，是因为最常见的失败就是拼错名字——直接给出正确选项，省掉一次
    “到底有哪些”的往返。位置参数给的是路径时，main() 已经校验过了。
    """
    if a.wg:
        return a.wg
    c = WG_DIR / f"{a.name}.conf"
    if not c.is_file():
        avail = ", ".join(sorted(p.stem for p in WG_DIR.glob("*.conf"))) or "(none)"
        die(f"wg config not found: {c}\n"
            f"       available names: {avail}\n"
            f"       或直接给一个 .conf 路径")
    return c


def resolve_clash_conf(override) -> Path:
    """定位 clash 订阅：只认显式给出的路径。

    早先这里会去目录里认领“唯一的那份 *.yaml”。那是代码和数据同处一个文件夹时的产物
    ——脚本、订阅、运行时目录都挤在一起，扫一眼就能猜中。装进镜像、配置逐项指向具体
    文件之后，这条约定只剩两个坏处：多放一份订阅就突然罢工，而它报出来的目录还未必是
    用户以为的那个。要哪份就写哪份。

    不想要代理时用 --no-clash，那才是“没有订阅”的正当表达方式。
    """
    if not override:
        die("没有指定 clash 订阅\n"
            "       用 --clash-conf <path> 给出路径，或 --no-clash 只起隧道")
    c = Path(override).expanduser().resolve()
    if not c.is_file():
        die(f"--clash-conf not found: {c}")
    return c


def clash_port(conf: Path) -> int:
    """从订阅里读出本地代理端口。

    只读不改：端口要写进 profile.d 的探测逻辑和 status 输出，两边必须跟订阅里的
    实际值一致，写死常量会在换订阅后静默错位。
    """
    for line in conf.read_text(errors="replace").splitlines():
        m = re.match(r"^\s*(mixed-port|port)\s*:\s*(\d+)", line)
        if m:
            return int(m.group(2))
    log(f"warning: {conf.name} 里没找到 mixed-port，按 7890 处理")
    return 7890


def wg_network(conf: Path):
    """从 wg 配置的 Address 推出内网网段，用于 NO_PROXY。

    不加进 NO_PROXY 的话，容器里访问 wg 内网的其它机器会被 clash 按规则送出国，
    这是“隧道明明通了却连不上内网”的典型元凶。
    """
    for line in conf.read_text().splitlines():
        m = re.match(r"^\s*Address\s*=\s*([0-9a-fA-F.:]+/\d+)", line)
        if m:
            try:
                return ipaddress.ip_interface(m.group(1)).network
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------- 运行时布局

def run_dir(name: str) -> Path:
    return RUN_DIR / name


def sock_path(name: str) -> Path:
    """supervisord 的控制 socket。

    必须落在容器本地的 /run，不能放共享卷：共享卷是 gpfs，网络文件系统上创建不了
    unix socket。放 /run 还顺带保证了每个容器一套控制面，互不打扰。
    """
    return Path(f"/run/vpn-{name}.sock")


def pid_path(name: str) -> Path:
    return Path(f"/run/vpn-{name}.pid")


def build_wireproxy_conf(name: str, base_conf: Path, rd: Path) -> Path:
    """派生一份带入站转发段的 wireproxy 配置，返回其路径。

    关键约束：绝不改动基础配置。<name>.conf 是已调优、被视为固定的输入。这里只读
    它，取出 wireguard 核心（[Interface]/[Peer]），丢弃所有由本工具掌管的段（见
    MANAGED_SECTIONS），再补上唯一一段 [TCPServerTunnel]。结果：基础配置里无论有无
    残留的转发/代理段，派生结果都只含恰好一份 SSH 转发，重复运行也天然幂等。
    """
    managed = {"socks5", "http", "tcpservertunnel", "tcpclienttunnel"}
    kept, drop = [], False
    for line in base_conf.read_text().splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            drop = s[1:-1].strip().lower() in managed
        if not drop:
            kept.append(line)
    parts = [
        "\n".join(kept).rstrip(), "",
        "[TCPServerTunnel]",
        f"ListenPort = {SSH_PORT}",
        f"Target = 127.0.0.1:{SSH_PORT}",
        "",
    ]
    rc = rd / "wireproxy.conf"
    rc.write_text("\n".join(parts) + "\n")
    os.chmod(rc, 0o600)          # 里面有 wg 私钥
    return rc


def build_supervisord_conf(name: str, rd: Path, wp_conf: Path,
                           clash_conf: Path, want) -> Path:
    """生成本 name 专属的 supervisord 配置。

    每个 program 都 autorestart——这正是引入 supervisor 的全部理由：以前 wireproxy
    是 vpn.py 自己 Popen 出去的孤儿进程，握手失败或被 OOM 杀掉就永远躺平，得等人
    发现。

    环境变量在 [supervisord] 段统一清空：镜像给所有进程预置了
    HTTP_PROXY=http://127.0.0.1:7890，而 mihomo 自己就是那个 7890——它一旦继承这组
    变量，去连订阅或节点时就会绕回自己，表现为间歇性抽风。wireproxy 走 UDP 不受
    影响，sshd 会为登录会话重建环境，一并清掉最省心。
    """
    logd = rd / "log"
    logd.mkdir(parents=True, exist_ok=True)
    clean_env = ",".join(f'{k}=""' for k in PROXY_VARS)

    # supervisord 把 command= 按空白拆成 argv，所以每个路径都得引起来——运行时目录或
    # 订阅落在带空格的路径下时，不引会拆成两个参数，mihomo 直接找不到文件。
    prog = {
        "sshd": "/usr/sbin/sshd -D -e",
        "mihomo": shlex.join(["/usr/local/bin/mihomo",
                              "-d", str(rd / "mihomo"),
                              "-f", str(clash_conf),
                              "-ext-ctl", CLASH_API]),
        "wireproxy": shlex.join([wireproxy_bin(), "-c", str(wp_conf)]),
    }

    blocks = [f"""[supervisord]
nodaemon=false
user=root
pidfile={pid_path(name)}
logfile={logd / 'supervisord.log'}
logfile_maxbytes=10MB
logfile_backups=2
childlogdir={logd}
environment={clean_env}

[unix_http_server]
file={sock_path(name)}
chmod=0700

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://{sock_path(name)}
"""]

    # priority 决定启动顺序：先把 SSH 这条命脉拉起来，再上代理和隧道。三者之间没有
    # 真正的依赖（wg 走 UDP 直连，不经 clash），顺序只影响“出问题时哪个先就位”。
    for i, svc in enumerate(SERVICES):
        if svc not in want:
            continue
        blocks.append(f"""
[program:{svc}]
command={prog[svc]}
priority={10 * (i + 1)}
autostart=true
autorestart=true
startsecs=3
startretries=1000
stopsignal=TERM
stopasgroup=true
killasgroup=true
stdout_logfile={logd / (svc + '.log')}
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=2
redirect_stderr=true
""")

    sc = rd / "supervisord.conf"
    sc.write_text("".join(blocks))
    return sc


def wireproxy_bin() -> str:
    """定位 wireproxy 可执行文件。

    镜像在构建期就编译好装进 /usr/local/bin 了（见 docker/Dockerfile），所以只查
    PATH。刻意不在运行时装 Go 编译——那是本项目历史上最脆的一环（代理超时、版本
    冲突、模块改名）。
    """
    found = shutil.which("wireproxy")
    if found:
        return found
    die("wireproxy 不在 PATH 上——镜像应在构建期装好它，见 docker/Dockerfile")


# ---------------------------------------------------------------- 主机侧准备

def install_authorized_key() -> None:
    """把授权公钥装到 ~/.ssh/authorized_keys，并修正权限。

    这里只认一把密钥，所以直接覆盖写——覆盖天生幂等，省掉查重逻辑。权限收到
    700/600 是硬性前提：sshd 对目录或文件“组/他人可写”会静默拒绝登录，这正是
    “明明拷了公钥还是进不去”的元凶。
    """
    if not PUBKEY.is_file():
        die(f"pubkey missing: {PUBKEY}")

    # 空文件或者随手写坏的一行同样能被复制过去，而 start 的核对只看端口和进程，于是
    # 一切报绿、每一次 SSH 登录都失败。在覆盖 authorized_keys 之前先确认它确实是公钥。
    if PUBKEY.stat().st_size == 0:
        die(f"pubkey is empty: {PUBKEY}")
    if shutil.which("ssh-keygen"):
        r = subprocess.run(["ssh-keygen", "-l", "-f", str(PUBKEY)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            die(f"pubkey is not a valid public key: {PUBKEY}\n"
                f"       {r.stderr.decode(errors='replace').strip()}")

    ssh_dir = Path.home() / ".ssh"
    ssh_dir.mkdir(exist_ok=True)
    os.chmod(ssh_dir, 0o700)
    ak = ssh_dir / "authorized_keys"
    shutil.copyfile(PUBKEY, ak)
    os.chmod(ak, 0o600)


def ensure_host_keys(rd: Path) -> None:
    """让 SSH 主机密钥跨容器重启保持不变。

    镜像在构建期删掉了主机密钥，容器每次重启 /etc 又是全新的，于是 ssh-keygen -A
    每次都生成一套新身份——客户端每次重启后都会撞上 REMOTE HOST IDENTIFICATION
    HAS CHANGED，得先 ssh-keygen -R 才能再连。把密钥存进共享卷、启动时装回去，这个
    警告就再也不会出现。

    首次运行会把容器里现有的那套收进共享卷，而不是重新生成——否则这次改造本身就
    会触发一次密钥变更，正好是要消灭的那个麻烦。
    """
    store = rd / "ssh"
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o700)

    subprocess.run(["ssh-keygen", "-A"], check=False,          # 只补缺失的
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    saved = list(store.glob("ssh_host_*"))
    if saved:
        for k in saved:
            dst = Path("/etc/ssh") / k.name
            shutil.copyfile(k, dst)
            os.chmod(dst, 0o644 if k.name.endswith(".pub") else 0o600)
    else:
        for k in Path("/etc/ssh").glob("ssh_host_*"):
            shutil.copyfile(k, store / k.name)
            os.chmod(store / k.name, 0o644 if k.name.endswith(".pub") else 0o600)
        log(f"已把当前 SSH 主机密钥收进 {store}（此后重启不再变更）")

    Path("/run/sshd").mkdir(parents=True, exist_ok=True)


def write_proxy_profile(port: int, net) -> None:
    """写 /etc/profile.d 的代理变量，并把 wg 网段排除在代理之外。

    只有代理端口确实在监听时才导出——这解决了镜像里那组硬编码 ENV 的鸡生蛋问题：
    平台起容器时 mihomo 还不存在，可 PID 1 及其所有后代（jupyter、code-server 的
    终端）已经带着 HTTP_PROXY=127.0.0.1:7890，任何 curl/pip/npm 都直接失败。用
    /proc/net/tcp 做探测而不是 bash 的 /dev/tcp，是因为 profile.d 也可能被 dash 读，
    而且查一次内核表不产生任何连接。
    """
    hexport = f"{port:04X}"
    no_proxy = "localhost,127.0.0.1,::1" + (f",{net}" if net else "")
    PROXY_PROFILE.write_text(f"""\
# 由 vpn.py 生成，勿手改；vpn.py shutdown 会删除它。
# 仅当本地代理确实在监听时才导出代理变量——代理没起时保持直连，避免所有
# curl/pip/npm 撞上一个不存在的代理。
if grep -qi ':{hexport} .* 0A ' /proc/net/tcp 2>/dev/null; then
    HTTP_PROXY="http://127.0.0.1:{port}"
    HTTPS_PROXY="$HTTP_PROXY"
    ALL_PROXY="socks5h://127.0.0.1:{port}"
    NO_PROXY="{no_proxy}"
    http_proxy="$HTTP_PROXY"
    https_proxy="$HTTPS_PROXY"
    all_proxy="$ALL_PROXY"
    no_proxy="$NO_PROXY"
    export HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
    export http_proxy https_proxy all_proxy no_proxy
fi
""")
    os.chmod(PROXY_PROFILE, 0o644)


# ---------------------------------------------------------------- 遗留进程接管

def _cmdline(pid: str):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [a for a in raw.decode(errors="replace").split("\0") if a]


def listener_pid(port: int):
    """返回正在监听该端口的 pid；没有则 None。

    用来确认端口是不是真的到了我们手里。mihomo 绑不上 mixed-port 时只记一行错误
    日志、进程照活——supervisor 看它 RUNNING 就以为一切正常，实际代理还是旧进程在
    提供。只有查一次端口归属才能戳破这种“假running”。
    """
    try:
        out = subprocess.run(["ss", "-lntpH", f"sport = :{port}"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5).stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"pid=(\d+)", out)
    return int(m.group(1)) if m else None


def reap_legacy(cport) -> None:
    """腾空端口：杀掉不受 supervisor 管的同名进程。cport 为 None 表示不起代理。

    正常情况下这里什么都不用做——容器刚起来时没人启动这些服务。它是给“手工起过
    一次 mihomo”“supervisord 被 kill -9 后留下孤儿”这类情况兜底的：端口被占着的话
    新进程必然绑定失败。只在 supervisord 未运行时调用，所以不会误伤它自己的孩子。

    sshd 只杀监听进程。OpenSSH 会改写 cmdline：监听进程是
    “sshd: /usr/sbin/sshd [listener] 0 of 10-100 startups”，已建立的会话则是
    “sshd: root@pts/3”。按 [listener] 区分，不能按 argv[0]——新版里监听进程的
    argv[0] 也是 “sshd:”。这一点必须做对，否则执行 start 的人会被自己踢下线。
    """
    ports = tuple(x for x in (SSH_PORT, cport) if x)

    victims = []
    for p in Path("/proc").glob("[0-9]*"):
        argv = _cmdline(p.name)
        if not argv:
            continue
        line = " ".join(argv)
        base = Path(argv[0]).name
        if base in ("mihomo", "wireproxy"):
            victims.append((p.name, base))
        elif base.startswith("sshd") and ("[listener]" in line
                                          or line == "/usr/sbin/sshd"):
            victims.append((p.name, "sshd"))

    for pid, what in victims:
        log(f"接管遗留进程：{what} (pid {pid})")
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass

    # 等端口真正释放再往下走。直接 sleep 一个定值要么白等、要么不够——TIME_WAIT
    # 之外，被 SIGTERM 的进程收尾也需要时间。
    for _ in range(50):
        if not any(listener_pid(x) for x in ports):
            return
        time.sleep(0.2)
    log(f"warning: 端口 {'/'.join(str(x) for x in ports)} 仍被占用，服务可能起不来")


# ---------------------------------------------------------------- supervisor

def supervisord_bin() -> str:
    return shutil.which("supervisord") or die("supervisord 不在 PATH 上（apt install supervisor）")


def is_up(name: str) -> bool:
    """supervisord 是否在跑——以能否连上控制 socket 为准。

    不看 pid 文件：/run 虽是容器私有，但 supervisord 被 OOM 杀掉后 pid 文件会留下
    失真的值，而 socket 连不连得上就是它活着的定义。
    """
    s = sock_path(name)
    if not s.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(2)
            c.connect(str(s))
        return True
    except OSError:
        s.unlink(missing_ok=True)      # 陈旧 socket，清掉免得下次误判
        return False


def ctl(name: str, *args, capture=False):
    conf = run_dir(name) / "supervisord.conf"
    if not conf.is_file():
        die(f"没有运行时配置：{conf}\n       先跑一次 start")
    cmd = [shutil.which("supervisorctl") or "supervisorctl", "-c", str(conf), *args]
    if capture:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return r.stdout.decode(errors="replace")
    return subprocess.run(cmd).returncode


def _svc_pid(status_out: str, svc: str):
    m = re.search(rf"^{svc}\s+RUNNING\s+pid (\d+)", status_out, re.M)
    return int(m.group(1)) if m else None


def verify(name: str, cport, want) -> bool:
    """启动后核对结果：状态全 RUNNING，且端口确实归我们的进程。

    supervisor 只保证进程活着，不保证它干成了活——mihomo 绑不上 mixed-port 时只记
    一行错误日志、进程照活，supervisor 眼里它一切正常。少了这道核对，用户会拿到一个
    “状态全绿、实际代理还是旧进程”的容器，而这种错最难自己发现。
    """
    out = ctl(name, "status", capture=True)
    ok = True

    for line in out.strip().splitlines():
        if line.split()[1:2] != ["RUNNING"]:
            ok = False
            svc = line.split()[0]
            log(f"warning: {svc} 未就绪，看 {run_dir(name) / 'log' / (svc + '.log')}")

    for svc, port in (("sshd", SSH_PORT), ("mihomo", cport)):
        if svc not in want:
            continue
        holder, mine = listener_pid(port), _svc_pid(out, svc)
        if holder is None:
            ok = False
            log(f"warning: 没有进程在监听 {port}（{svc}）")
        elif mine and holder != mine:
            ok = False
            log(f"warning: 端口 {port} 被 pid {holder} 占着，"
                f"而不是 supervisor 管的 {svc}(pid {mine})")
    return ok


def _acquire_lock(name: str):
    """取本 name 的排他锁，取不到返回 None。

    同一时刻可能有好几处在触发 start（引导脚本、手工执行、多开的终端），并发很
    现实；用文件锁串行化，堵死“都查到没跑、又都去起”的竞态。
    """
    rd = run_dir(name)
    rd.mkdir(parents=True, exist_ok=True)
    lock = open(rd / "start.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except OSError:
        lock.close()
        return None


# ---------------------------------------------------------------- 动作

def start(a) -> None:
    """把本容器接入 wg、开出 clash 代理、开放 SSH；已在运行则原样返回。"""
    wg_conf = resolve_wg_conf(a)
    want = set(SERVICES)
    if a.no_clash:
        want.discard("mihomo")
    if a.no_wg:
        want.discard("wireproxy")

    # 不起 mihomo 就不需要订阅。放在 want 算完之后要，省得 --no-clash 还被逼着给一份。
    clash_conf = resolve_clash_conf(a.clash_conf) if "mihomo" in want else None

    lock = _acquire_lock(a.name)
    if lock is None:
        log(f"another start({a.name}) in progress; skipping")
        return
    try:
        rd = run_dir(a.name)
        (rd / "mihomo").mkdir(parents=True, exist_ok=True)
        cport = clash_port(clash_conf) if clash_conf else None

        install_authorized_key()
        ensure_host_keys(rd)
        wp_conf = build_wireproxy_conf(a.name, wg_conf, rd)
        conf = build_supervisord_conf(a.name, rd, wp_conf, clash_conf, want)
        if cport:
            write_proxy_profile(cport, wg_network(wg_conf))
        else:
            # 没有代理还留着上一次的 profile，新 shell 会指向一个不存在的端口。
            PROXY_PROFILE.unlink(missing_ok=True)

        if is_up(a.name):
            # 配置可能已经变了（换订阅、改 wg），让 supervisord 重读并收敛。
            ctl(a.name, "update")
            log(f"已在运行；配置已重载")
            status(a)
            return

        reap_legacy(cport)
        r = subprocess.run([supervisord_bin(), "-c", str(conf)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           start_new_session=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout.decode(errors="replace"))
            die("supervisord 启动失败")

        # 等它把 socket 建起来再报状态，否则紧跟着的 status 会扑空。
        for _ in range(50):
            if is_up(a.name):
                break
            time.sleep(0.1)
        else:
            die(f"supervisord 起来了但 socket 没出现：{sock_path(a.name)}")

        time.sleep(3.2)          # 略大于 startsecs，让 RUNNING/BACKOFF 尘埃落定
        log(f"start: {a.name}")
        status(a)
        if verify(a.name, cport, want):
            log("新开的 shell 才会拿到代理变量；当前 shell 执行： "
                f"source {PROXY_PROFILE}")
        else:
            die("启动没有完全成功，见上面的 warning")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def shutdown(a) -> None:
    """停掉本 name 的全部服务；未在运行也不报错。"""
    if is_up(a.name):
        ctl(a.name, "shutdown")
        for _ in range(50):
            if not is_up(a.name):
                break
            time.sleep(0.1)
    PROXY_PROFILE.unlink(missing_ok=True)   # 代理没了，变量也不该再留着
    log(f"shutdown: {a.name}")


def restart(a) -> None:
    shutdown(a)
    time.sleep(0.5)
    start(a)


def status(a) -> None:
    if not is_up(a.name):
        log(f"{a.name}: supervisord 未运行")
        return
    out = ctl(a.name, "status", capture=True)
    for line in out.strip().splitlines():
        log(line)
    if a.clash_conf:
        clash_conf = resolve_clash_conf(a.clash_conf)
        port = clash_port(clash_conf)
        log(f"clash 配置: {clash_conf.name}  代理: 127.0.0.1:{port}  API: {CLASH_API}")
    log(f"日志目录: {run_dir(a.name) / 'log'}")


def logs(a) -> None:
    svc = a.service or "wireproxy"
    if svc not in SERVICES:
        die(f"未知服务 {svc}；可选：{', '.join(SERVICES)}")
    logf = run_dir(a.name) / "log" / f"{svc}.log"
    if not logf.exists():
        die(f"no log yet: {logf}")
    subprocess.run(["tail", "-n", "50", "-f", str(logf)])


def bashsetup(a) -> None:
    """把开机自启行写进 ~/.bashrc，让每次进容器自动 start。

    用固定标记 `# vpn-autostart` 圈定自己那一行，先删旧再写新——因此重复执行、或
    改了 name 再跑，都只留一行、不会越堆越多，同样是幂等。要求 ~/.bashrc 位于持久
    卷上才有意义（容器 /root 会重置）。
    """
    resolve_wg_conf(a)          # 先校验，别写进一个连不上的名字
    marker = "# vpn-autostart"
    line = f"uv run {BASE / 'vpn.py'} start {a.spec} >/dev/null 2>&1  {marker}"
    rc = Path.home() / ".bashrc"
    kept = [ln for ln in (rc.read_text().splitlines() if rc.exists() else [])
            if marker not in ln]
    kept.append(line)
    rc.write_text("\n".join(kept) + "\n")
    log(f"已写入 {rc}：每次进 shell 自动 start {a.name}")
    log("本次立即生效： source ~/.bashrc")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="vpn", description="受限容器的用户态 WireGuard 接入 + clash 代理")
    ap.add_argument("action", choices=["start", "restart", "shutdown", "status",
                                       "logs", "bashsetup", "up", "down", "stop"])
    ap.add_argument("name", metavar="wg",
                    help="wg 配置（必填）：wireguard/ 下的名字（如 cz4090），"
                         "或任意 .conf 路径")
    ap.add_argument("service", nargs="?",
                    help=f"logs 专用，看哪个服务（{'/'.join(SERVICES)}），默认 wireproxy")
    ap.add_argument("--clash-conf", help="clash 订阅路径；不给则不起 mihomo")
    ap.add_argument("--no-clash", action="store_true", help="不起 mihomo")
    ap.add_argument("--no-wg", action="store_true", help="不起 wireproxy")
    a = ap.parse_args()

    # 相对路径会随调用者的 cwd 漂移，而本脚本被登录引导从任意目录调用；空串更糟，它会让
    # 变量静默失效、回退到脚本目录，把 .run/ 写进重启即丢的容器可写层。宁可在这里炸。
    for var in ("VPN_PUBKEY", "VPN_RUN_DIR"):
        val = os.environ.get(var)
        if val is not None and not Path(val).is_absolute():
            die(f"{var} must be an absolute path, got: {val!r}")

    # 位置参数既可以是 wireguard/ 下的名字，也可以是任意 .conf 路径——两者说的是
    # 同一件事：本容器用哪份 wg 配置。合成一个入口，是为了不让
    # “start cz4090 --wg-conf other.conf” 这种自相矛盾的组合成立：名字指向一份配置、
    # 实际加载的是另一份，而运行时目录还挂在名字底下。
    #
    # clash 订阅则相反，它是所有容器共用的一份，跟“本容器是谁”无关，所以留作选项。
    # up/down/stop 是旧名字，留作别名——肌肉记忆比命名整洁重要。
    action = {"up": "start", "down": "shutdown", "stop": "shutdown"}.get(
        a.action, a.action)

    a.spec, a.wg = a.name, None
    if "/" in a.name or a.name.endswith(".conf"):
        p = Path(a.name).expanduser().resolve()
        if p.is_file():
            a.wg, a.name = p, p.stem      # 实例名取文件名，运行时目录随之确定
        elif action in ("shutdown", "status", "logs"):
            # 控制类动作只需要实例名。共享卷抖一下、或者配置被挪走时，仍然得能停掉、
            # 看得到已经在跑的那套——否则一个读不到配置的容器就再也关不掉了。
            a.name = p.stem
        else:
            die(f"wg config not found: {p}")
    {
        "start": start, "shutdown": shutdown, "restart": restart,
        "status": status, "logs": logs, "bashsetup": bashsetup,
    }[action](a)


if __name__ == "__main__":
    main()
