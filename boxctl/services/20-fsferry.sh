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
    install -d -m 0755 "${BOXCTL_FSFERRY_DIR}"
    # FSFERRY_DIR 由 boxctl 的 apply_env 导出，这里不重复拼一遍——两处分开写会漂移。
    nohup fsferry-agent >> "$(_fsferry_log)" 2>&1 &
    disown
}

fsferry_stop() {
    pkill -f fsferry-agent || true
}

fsferry_restart() {
    fsferry_stop
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
