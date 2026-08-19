"""传输层:把一个共享目录变成两台机器之间的可靠消息通道。

只用标准库和 POSIX 语义,不关心上面跑的是什么应用。两条保证:

1. 原子性——先写 tmp/ 再 os.replace() 进目标目录。同卷 rename 是原子操作,
   读端永远看不到半截文件。这是 Maildir(qmail)传下来的老办法,也是 spool
   目录几十年来能在共享存储上工作的原因。

2. 可见性——跨节点只能轮询,不能用 inotify。inotify 只感知本机写入,另一台
   机器经共享卷写进来的文件不会触发任何事件。这是本方案最容易踩的坑。

目录布局(全部在 FSFERRY_DIR 下,必须与 tmp/ 同卷才能 rename):

    inbox/   <id>.cmd                      客户端投递的命令,内容就是命令原文
    work/    <id>.cmd                      代理认领后移到这里,崩溃时留下现场
    live/    <id>.out .err                 正在执行的命令的实时输出,人可 tail -F
    outbox/  <id>.out .err .exit .done     结果;done 最后写,是提交标记
    heartbeat                              代理存活证明,客户端靠它区分"慢"和"死"
    tmp/                                   原子写暂存

live/ 是原子性保证的刻意例外:它就是给人看的"半截文件",实时增长是目的。
程序间的消息交换从不读它——命令结束时内容原样转正进 outbox(原子写),
live 文件即删。命名与 outbox 完全镜像:同一个 id,同一对 .out/.err。

协议刻意用纯文本文件而不是 JSON:这条通道通向一台你 SSH 不进去的机器,它坏掉
时你手上只有 ls 和 cat。纯文件让你能肉眼看懂中间状态,甚至手工投一条命令验证
链路——`echo nvidia-smi > inbox/probe.cmd` 然后 `cat outbox/probe.out`。
"""

import os
import sys
import time
import uuid
from pathlib import Path

ENV_VAR = "FSFERRY_DIR"
SUBDIRS = ("inbox", "work", "live", "outbox", "tmp")
HEARTBEAT = "heartbeat"


def root_from_env() -> Path:
    """通道目录只有一个入口:环境变量。不提供命令行覆盖,也不做静默默认。

    单一入口是刻意的:多一个入口就多一套优先级规则和一份出错时"到底哪个
    生效了"的困惑。通道目录是部署事实(两端必须完全一致),部署时设一次即可。

    没设就立刻退出。两端各自指向不同目录的话,双方都不会报错,只会永远互相
    干等——那是最难查的一类故障,必须在启动时就拦下。
    """
    value = os.environ.get(ENV_VAR)
    if not value:
        sys.exit(
            f"fsferry: 未设置 {ENV_VAR}。它要指向共享卷上两机同路径的通道目录,\n"
            f"         优先选最快的那个卷(元数据延迟差别可达 8 倍,见 README 延迟一节)。"
        )
    root = Path(value)
    if not root.is_absolute():
        sys.exit(f"fsferry: {ENV_VAR} 必须是绝对路径,当前是 {value!r}")
    # 落在根目录下几乎肯定是变量展开出了问题:写成 "$XDG_DATA_HOME/fsferry"
    # 而该变量为空时(非交互 shell 常见),会静默变成 "/fsferry"。以 root 身份
    # 跑的话这个目录还真能建出来,于是通道悄悄开在错误的地方——错了还继续跑,
    # 最该拦住。
    if root.parent == Path("/"):
        sys.exit(
            f"fsferry: {ENV_VAR}={value!r} 落在文件系统根下,这几乎肯定是变量展开出了问题。\n"
            f"         常见原因:引用的变量在非交互 shell 里为空。先确认它有值再重设 {ENV_VAR}。"
        )
    return root


def ensure_dirs(root: Path) -> None:
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)


def atomic_write(root: Path, target: Path, data: bytes) -> None:
    """原子写:tmp/ 暂存 → fsync → rename 到位。target 必须与 root 同卷。

    fsync 不能省:rename 只保证目录项被原子替换,不保证内容已落盘,少了它
    另一个节点可能在 rename 之后读到一个空文件。
    """
    tmp = root / "tmp" / f"{target.name}.{uuid.uuid4().hex}"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, target)


def read_bytes(path: Path) -> bytes:
    """读文件;不存在返回空。被 GC 清掉等竞态不该让客户端崩掉。"""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def beat(root: Path) -> None:
    """代理心跳。客户端靠它区分"命令跑得慢"和"对端根本没在跑"。"""
    atomic_write(root, root / HEARTBEAT, str(time.time()).encode())


def heartbeat_age(root: Path):
    """心跳距今多少秒;从未启动过返回 None。"""
    try:
        return time.time() - (root / HEARTBEAT).stat().st_mtime
    except FileNotFoundError:
        return None


def wait_for(path: Path, timeout: float, start: float = 0.01, cap: float = 0.2) -> bool:
    """自适应轮询等一个文件出现:先密后疏。

    刚投出命令时对端多半马上就回,所以起步 10ms 让快命令近乎瞬时返回;命令
    要跑很久时逐步退到 200ms,避免长时间空转打满共享卷的元数据服务。
    """
    deadline = time.time() + timeout
    interval = start
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(interval)
        interval = min(interval * 1.5, cap)
    return path.exists()
