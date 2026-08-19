# fsferry —— 在共享文件系统上摆渡命令，让这台机器可被没有 SSH 入口的一侧远程执行。
#
# 通道目录只认 FSFERRY_DIR，两端必须是同一个绝对路径。

fsferry_enabled() { [[ "${BOXCTL_ENABLE_FSFERRY:-0}" == "1" ]]; }

fsferry_env() {
    emit FSFERRY_DIR "${BOXCTL_FSFERRY_DIR:-}"
}

_fsferry_require() {
    [[ -n "${BOXCTL_FSFERRY_DIR:-}" ]] || die "BOXCTL_FSFERRY_DIR 未设置"
    # 相对路径在非交互 shell 里会静默变成 /fsferry 之类，以 root 跑还真能建出来。
    [[ "${BOXCTL_FSFERRY_DIR}" == /* ]] || die "BOXCTL_FSFERRY_DIR 必须是绝对路径"
}

_fsferry_log() { printf '%s\n' "${BOXCTL_FSFERRY_DIR}/agent.log"; }

fsferry_running() { pgrep -f fsferry-agent >/dev/null 2>&1; }

fsferry_start() {
    _fsferry_require

    # 通道里过的是远程命令、它们的输出和退出码。共享卷上同节点的其他用户默认读得到，
    # 所以目录收到 0700，已经建好的也一并收紧（fsferry 自己的 README 也要求 700）。
    install -d -m 0700 "${BOXCTL_FSFERRY_DIR}"
    chmod 0700 "${BOXCTL_FSFERRY_DIR}"

    # umask 让代理后续自建的子目录和消息文件跟着是 0700/0600——通道协议目录由 fsferry
    # 自己 mkdir，不设 umask 的话它们会落在默认的 0755。
    # FSFERRY_DIR 由 boxctl 的 apply_env 导出，这里不重复拼一遍——两处分开写会漂移。
    (umask 077; nohup fsferry-agent >> "$(_fsferry_log)" 2>&1 &)
}

fsferry_stop() {
    pkill -f fsferry-agent || true

    # 等它真的退出再返回。代理的 SIGTERM 处理只是把循环标志置 false，正阻塞在子命令上
    # 时不会立刻走——restart 直接接着 start 的话，会有两个代理同时消费同一条通道。
    local i
    for i in $(seq 50); do
        fsferry_running || return 0
        sleep 0.2
    done
    log "fsferry: 旧代理 20 秒后仍在，可能卡在某条命令上；未强杀"
    return 1
}

fsferry_restart() {
    fsferry_stop || true
    fsferry_start
}

fsferry_status() {
    local pids
    pids="$(pgrep -f fsferry-agent | tr '\n' ' ')" || true
    if [[ -n "${pids}" ]]; then
        printf '  pid %s\n' "${pids}"
    fi
}

fsferry_logs() {
    _fsferry_require
    tail -n "${BOXCTL_LOG_LINES:-200}" "$(_fsferry_log)"
}
