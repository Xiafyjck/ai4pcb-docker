"""应用层(本地):把一条命令投给远端代理,取回结果。

    h200 'nvidia-smi'
    h200 'cd /path && ls'
    h200 --wait 600 'torchrun ...'

行为对齐 ssh 远程执行:stdout 进 stdout、stderr 进 stderr、退出码就是远端命令
的退出码。所以它能直接进管道、进 && 、进脚本的 if 判断,调用方不需要知道底下
是一个共享文件夹。
"""

import argparse
import os
import sys
import uuid

from . import channel

STALE_BEAT = 15.0   # 心跳超过这么久没更新,就认为代理多半不在了
HINT_AFTER = 2.0    # 等这么久还没结果,就把实时查看 live/ 输出的方法指给用户


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="h200",
        description="在远端机器上执行命令(经共享文件系统通道 fsferry)",
    )
    parser.add_argument("command", help="要执行的命令,记得用引号包住")
    parser.add_argument(
        "--wait",
        type=float,
        default=300.0,
        help="等结果的最长时间(秒),默认 300;跑长任务要调大",
    )
    args = parser.parse_args()

    root = channel.root_from_env()
    # 客户端自己建目录,不要求代理先跑过:否则两端启动顺序会变成竞态。
    # "对端在不在"由心跳判断,那才是它该管的事;目录存在性判断不了这个。
    channel.ensure_dirs(root)

    # 先看心跳:命令投出去之后再发现对端没在跑,只会白等一个 --wait
    age = channel.heartbeat_age(root)
    if age is None:
        print("h200: 警告 没有心跳文件,远端代理可能从未启动", file=sys.stderr)
    elif age > STALE_BEAT:
        print(f"h200: 警告 代理心跳已 {age:.0f}s 未更新,可能已经挂了", file=sys.stderr)

    rid = uuid.uuid4().hex
    channel.atomic_write(root, root / "inbox" / f"{rid}.cmd", args.command.encode())

    box = root / "outbox"
    done = box / f"{rid}.done"
    # 先短等一下:快命令在这窗口内就返回,终端保持干净。还没回来的多半是长
    # 任务——恰在用户开始想"它在干嘛"时,把实时查看入口递过去:代理正把命令
    # 的输出写在共享卷 live/ 下,照抄这行 tail 就能盯住,不必等跑完。
    finished = channel.wait_for(done, min(HINT_AFTER, args.wait))
    if not finished and args.wait > HINT_AFTER:
        print(f"h200: 仍在运行,实时看输出: tail -F {root}/live/{rid}.out", file=sys.stderr)
        finished = channel.wait_for(done, args.wait - HINT_AFTER)
    if not finished:
        # 还没被认领就撤回,避免代理事后捡起来跑一条没人要结果的命令
        (root / "inbox" / f"{rid}.cmd").unlink(missing_ok=True)
        sys.exit(
            f"h200: 等待结果超时({args.wait}s)。命令可能仍在远端跑;"
            f"用 --wait 调大,或直接去 {box} 按 id {rid} 取结果"
        )

    out = channel.read_bytes(box / f"{rid}.out")
    err = channel.read_bytes(box / f"{rid}.err")
    try:
        code = int(channel.read_bytes(box / f"{rid}.exit").decode().strip())
    except ValueError:
        code = 125
    for leftover in box.glob(f"{rid}.*"):
        leftover.unlink(missing_ok=True)

    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(err)
    sys.stderr.buffer.flush()
    sys.exit(code)


if __name__ == "__main__":
    main()
