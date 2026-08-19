"""应用层(远端):常驻在只能靠共享卷通信的机器上,收命令、执行、回结果。

轮询 inbox/ 取命令 → bash 执行(stdout/stderr 实时落在 live/,人可 tail)
→ 把 stdout/stderr/退出码写回 outbox/。

这个进程是那台机器对外的唯一执行入口,而它所在的机器没有 SSH 入口——它一旦
挂掉,你没法登上去重启,只能靠外层作业机制重新拉起。所以代码宁可啰嗦也要把
每种失败显式回报给客户端,而不是让对面干等到超时:干等只告诉你"没反应",
显式回报能告诉你"为什么"。

命令继承本进程的环境变量,所以请在已配好环境(source 过 set_cache.sh 之类)
的 shell 里启动代理,子命令才能拿到 XDG / venv 等上下文。

命令串行执行,一次一条。这是刻意的:诊断类用途不需要并发,串行既避免把训练
机压垮,也让 outbox 里的时间线可读。
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import channel

POLL = float(os.environ.get("FSFERRY_POLL", "0.05"))          # 空闲轮询周期(秒)
BEAT_EVERY = 2.0                                              # 心跳周期(秒)
GC_EVERY = 60.0                                               # 清理周期(秒)
STALE_TTL = float(os.environ.get("FSFERRY_TTL", "3600"))      # 无人取走的结果保留多久(秒)
MAX_OUTPUT = int(os.environ.get("FSFERRY_MAX_OUTPUT", str(8 * 1024 * 1024)))

_limit = float(os.environ.get("FSFERRY_MAX_RUNTIME", "0"))    # 单条命令上限,0 = 不限
MAX_RUNTIME = _limit if _limit > 0 else None

_running = True


def _stop(signum, frame) -> None:
    global _running
    _running = False


def log(msg: str) -> None:
    print(f"[fsferry-agent] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def respond(root: Path, rid: str, out: bytes, err: bytes, code: int) -> None:
    """回写结果。out/err/exit 先落盘,done 最后写。

    客户端只等 done,所以它看到 done 时前三个文件必定已经就绪——用一个末尾
    标记文件换取"多文件结果"的原子性,省掉把输出塞进 JSON 再转义的麻烦。
    """
    box = root / "outbox"
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT]
        err += f"\nfsferry: stdout 超过 {MAX_OUTPUT} 字节上限,已截断\n".encode()
    if len(err) > MAX_OUTPUT:
        err = err[:MAX_OUTPUT] + "\nfsferry: stderr 已截断\n".encode()
    channel.atomic_write(root, box / f"{rid}.out", out)
    channel.atomic_write(root, box / f"{rid}.err", err)
    channel.atomic_write(root, box / f"{rid}.exit", str(code).encode())
    channel.atomic_write(root, box / f"{rid}.done", b"")


def execute(root: Path, work_file: Path) -> None:
    rid = work_file.stem
    cmd = work_file.read_text(errors="replace")
    log(f"run {rid}: {cmd.strip()!r}")   # 审计留痕:谁让这台机器干了什么,有据可查
    started = time.time()
    # stdout/stderr 走 live/ 下的具名文件。"文件而不是管道"是硬要求:用管道的
    # 话,命令里若后台起了进程(nohup ... &),那个进程会继承管道,subprocess.run
    # 必须等到管道关闭才返回——于是一条后台命令就能让代理永久阻塞。代理串行执行,
    # 整条通道随之死掉,而这台机器没有 SSH 入口,救不回来。换成文件后只等直接
    # 子进程。"具名而不是匿名临时文件"则是为了能实时看:命令还在跑时,另一台
    # 机器 tail -F live/<id>.out 就能盯住输出,不必等它跑完。
    # stdin 也要断开:否则命令继承代理的 stdin,一个等输入的命令同样能挂死通道。
    live_out = root / "live" / f"{rid}.out"
    live_err = root / "live" / f"{rid}.err"
    with open(live_out, "wb") as fout, open(live_err, "wb") as ferr:
        try:
            done = subprocess.run(
                ["bash", "-c", cmd],
                stdin=subprocess.DEVNULL, stdout=fout, stderr=ferr,
                timeout=MAX_RUNTIME,
            )
            code, extra = done.returncode, b""
        except subprocess.TimeoutExpired:
            code, extra = 124, f"fsferry: 超过代理上限 {MAX_RUNTIME}s,已终止\n".encode()
        except Exception as exc:                              # 代理自身的失败也要回报
            code, extra = 125, f"fsferry: 代理执行失败: {exc}\n".encode()
    out = channel.read_bytes(live_out)
    err = channel.read_bytes(live_err) + extra
    respond(root, rid, out, err, code)
    # 结果已提交进 outbox,live 文件使命完成。命令若留了后台进程还握着 fd,
    # 删掉名字不影响它继续跑,只是之后的输出没人收——和从前写临时文件时一样。
    live_out.unlink(missing_ok=True)
    live_err.unlink(missing_ok=True)
    log(f"done {rid}: exit={code} 用时 {time.time() - started:.2f}s")


def gc(root: Path) -> None:
    """清理没人来取的陈旧文件。客户端正常取走后会自己删,这里兜的是客户端中途
    被 Ctrl-C 掉、或投完命令就断开的情况。"""
    # live/ 敢进这份名单,靠的是串行:gc 只在两条命令的间隙运行,正常结束的
    # live 文件此刻已删,能留到过期的只有异常残骸(如崩溃后未被重启逻辑收走的)。
    now = time.time()
    for name in ("outbox", "inbox", "tmp", "live"):
        for path in (root / name).iterdir():
            try:
                if now - path.stat().st_mtime > STALE_TTL:
                    path.unlink()
                    log(f"gc 清理 {name}/{path.name}")
            except FileNotFoundError:
                pass


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def main() -> None:
    root = channel.root_from_env()
    channel.ensure_dirs(root)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # 上次崩溃时正在跑的命令,完整结果永远不会来了。明确回报失败,免得客户端
    # 干等;live/ 里还留着中断前已产生的输出,一并交还——多还原一截现场。
    for leftover in (root / "work").iterdir():
        rid = leftover.stem
        log(f"发现上次未完成的命令 {leftover.name},回报失败")
        out = channel.read_bytes(root / "live" / f"{rid}.out")
        err = channel.read_bytes(root / "live" / f"{rid}.err")
        err += "fsferry: 代理在执行本命令期间重启,以上是中断前已产生的输出\n".encode()
        respond(root, rid, out, err, 125)
        (root / "live" / f"{rid}.out").unlink(missing_ok=True)
        (root / "live" / f"{rid}.err").unlink(missing_ok=True)
        leftover.unlink()

    log(f"就绪 dir={root} poll={POLL}s pid={os.getpid()}")
    last_beat = last_gc = 0.0
    while _running:
        now = time.time()
        if now - last_beat >= BEAT_EVERY:
            channel.beat(root)
            last_beat = now
        if now - last_gc >= GC_EVERY:
            gc(root)
            last_gc = now

        pending = sorted((root / "inbox").glob("*.cmd"), key=_mtime)
        if not pending:
            time.sleep(POLL)
            continue
        for request in pending:
            claimed = root / "work" / request.name
            try:
                os.replace(request, claimed)   # 认领:rename 原子,同一条命令不会被跑两次
            except FileNotFoundError:
                continue                       # 已被 gc 清掉
            execute(root, claimed)
            claimed.unlink()
            if not _running:
                break

    (root / channel.HEARTBEAT).unlink(missing_ok=True)   # 主动撤心跳:让客户端立刻知道代理走了
    log("收到退出信号,已停止")


if __name__ == "__main__":
    sys.exit(main())
