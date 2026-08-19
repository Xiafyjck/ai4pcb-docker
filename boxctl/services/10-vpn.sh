# vpn —— 用户态 WireGuard 接入 + clash 代理，由 vpn.py 经 supervisor 守护
# sshd / mihomo / wireproxy 三个进程。
#
# 排在 fsferry 前面：它把容器接进内网并开出代理口，后面的服务可能要用。

vpn_enabled() { [[ "${BOXCTL_ENABLE_VPN:-0}" == "1" ]]; }

vpn_env() {
    emit VPN_PUBKEY "${BOXCTL_SSH_PUBKEY:-}"
    if [[ -n "${BOXCTL_STATE_DIR:-}" ]]; then
        emit VPN_RUN_DIR "${BOXCTL_STATE_DIR}/vpn"
    fi
}

# 实例名（「本容器是谁」）由 wg 配置的文件名决定，不单列配置项：两处分开填迟早会矛盾
# ——名字说用这份、实际加载那份，而运行时目录还挂在名字底下。
_vpn_instance() {
    local base
    base="$(basename "${BOXCTL_WG_CONF}")"
    printf '%s\n' "${base%.conf}"
}

# 起服务要真读得到配置。
_vpn_require() {
    _vpn_require_name
    [[ -r "${BOXCTL_WG_CONF}" ]] || die "BOXCTL_WG_CONF 读不到：${BOXCTL_WG_CONF}"
    [[ -n "${BOXCTL_STATE_DIR:-}" ]] || die "BOXCTL_STATE_DIR 未设置"
}

# 停服务、看状态、看日志只需要实例名，而实例名从路径字符串就能取出来。配置读不到时
# 仍然要能关掉已经在跑的那套——否则共享卷抖一下，这个容器就再也停不下来了。
_vpn_require_name() {
    [[ -n "${BOXCTL_WG_CONF:-}" ]] || die "BOXCTL_WG_CONF 未设置"
}

# 传给 vpn.py 的公共参数，结果放进 _vpn_argv。位置参数直接给 wg 配置的路径，实例名由它
# 取文件名得出。用全局数组而不是把参数打印出来再读回：路径里有空格时前者不会散架。
_vpn_argv=()
_vpn_build_argv() {
    _vpn_argv=("${BOXCTL_WG_CONF}")
    if [[ -n "${BOXCTL_CLASH_CONF:-}" ]]; then
        _vpn_argv+=(--clash-conf "${BOXCTL_CLASH_CONF}")
    else
        # 订阅留空就是「不要代理」。vpn.py 不再去目录里猜订阅，所以这里必须把意图说明白，
        # 否则它会因为缺订阅直接拒绝启动。
        _vpn_argv+=(--no-clash)
    fi
}

# 探测而不是记状态：supervisord 的控制 socket 是它活着的定义（vpn.py 同样以此为准），
# 再加一条 22 在监听，才算真的起来了——supervisor 只保证进程在，不保证它绑上了端口。
vpn_running() {
    [[ -n "${BOXCTL_WG_CONF:-}" ]] || return 1
    [[ -S "/run/vpn-$(_vpn_instance).sock" ]] || return 1
    ss -ltn 2>/dev/null | awk 'NR > 1 {print $4}' | grep -qE '[:.]22$'
}

vpn_start() {
    _vpn_require
    _vpn_build_argv
    vpn start "${_vpn_argv[@]}"
}

vpn_stop() {
    _vpn_require_name
    vpn shutdown "${BOXCTL_WG_CONF}"
}

vpn_restart() {
    _vpn_require
    _vpn_build_argv
    vpn restart "${_vpn_argv[@]}"
}

# 详细状态转给 vpn.py：它能分别报三个子进程，比这里的端口探测细。
vpn_status() {
    [[ -n "${BOXCTL_WG_CONF:-}" ]] || return 0
    local argv=("${BOXCTL_WG_CONF}")
    if [[ -n "${BOXCTL_CLASH_CONF:-}" ]]; then
        argv+=(--clash-conf "${BOXCTL_CLASH_CONF}")
    fi
    vpn status "${argv[@]}" 2>&1 | sed 's/^/  /'
}

vpn_logs() {
    _vpn_require_name
    vpn logs "${BOXCTL_WG_CONF}" "$@"
}
