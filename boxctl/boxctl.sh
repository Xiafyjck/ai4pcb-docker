#!/usr/bin/env bash
# boxctl —— 管容器内那些「本该自启、却没人替你启」的服务。
#
# 用在启动权不归自己的容器上：平台用它自己的脚本覆盖镜像 ENTRYPOINT，容器里的 PID 1
# 是平台的启动脚本，镜像里写的 ENTRYPOINT / supervisord 一次都不会执行。于是服务只能
# 在容器起来之后、由第一个登录的 shell 拉起。
#
# 刻意跟具体项目脱钩：服务定义都在 services/ 下，加一个服务就加一个文件。
set -Eeuo pipefail

BOXCTL_HOME="${BOXCTL_HOME:-/opt/boxctl}"
BOXCTL_CONFIG="${BOXCTL_CONFIG:-/root/.boxctl.env}"
BOXCTL_TEMPLATE="${BOXCTL_HOME}/boxctl.env.template"
SERVICE_DIR="${BOXCTL_HOME}/services"

log() { printf '[boxctl] %s\n' "$*" >&2; }
die() { log "$*"; exit 1; }

# 配置是纯 KEY=VALUE，直接 source。翻译成各工具自己认的变量名是 *_env 的活，配置文件
# 里只出现 BOXCTL_* 一套前缀。
load_config() {
    [[ -r "${BOXCTL_CONFIG}" ]] || return 1
    # shellcheck disable=SC1090
    source "${BOXCTL_CONFIG}"
}

# 服务文件按数字前缀排序，start all 的顺序就是文件名顺序（网络类的排前面）。
service_names() {
    local f n
    for f in "${SERVICE_DIR}"/[0-9]*-*.sh; do
        [[ -f "${f}" ]] || continue
        n="$(basename "${f}")"
        n="${n#*-}"
        printf '%s\n' "${n%.sh}"
    done
}

load_services() {
    local f
    for f in "${SERVICE_DIR}"/[0-9]*-*.sh; do
        [[ -f "${f}" ]] || continue
        # shellcheck disable=SC1090
        source "${f}"
    done
}

known_service() {
    local want="$1" s
    while read -r s; do
        if [[ "${s}" == "${want}" ]]; then
            return 0
        fi
    done < <(service_names)
    return 1
}

# 展开命令的服务参数：省略或 all 表示全部。调用点一律用命令替换接结果，好让未知服务
# 直接把整条命令带失败——放进 while 的进程替换里，die 只会杀掉子 shell，主循环反而
# 静悄悄地什么都不做。
targets() {
    local arg="${1:-all}"
    if [[ "${arg}" == "all" ]]; then
        service_names
        return 0
    fi
    known_service "${arg}" || die "未知服务：${arg}（可用：$(service_names | tr '\n' ' ')）"
    printf '%s\n' "${arg}"
}

# boot 日志跟着运行时产物走。没配 BOXCTL_STATE_DIR 时退到容器本地，重启即丢——但那种
# 情况下也没有服务能起来，日志里除了「XX 未设置」也没别的。
any_enabled() {
    local s
    for s in $(service_names); do
        if "${s}_enabled"; then
            return 0
        fi
    done
    return 1
}

log_dir() {
    if [[ -n "${BOXCTL_STATE_DIR:-}" ]]; then
        printf '%s\n' "${BOXCTL_STATE_DIR}/log"
    else
        printf '%s\n' /var/log/boxctl
    fi
}

emit() {
    [[ -n "${2:-}" ]] || return 0
    printf 'export %s=%q\n' "$1" "$2"
}

# 把 cmd_env 那份 export 应用到本进程，子进程跟着继承。
#
# 不能指望调用者已经 eval 过：登录 shell 确实先 eval 再 boot，但 boxctl boot 从 cron 或
# docker exec 单独跑时没人做这件事，服务就会拿不到路径、静默回退到镜像里的脚本目录，把
# 运行时产物写进重启即丢的容器可写层。给 shell 的和 boxctl 自己用的必须是同一份。
apply_env() {
    local lines
    lines="$(cmd_env)"
    eval "${lines}"
}

# ---------------------------------------------------------------- 子命令

cmd_env() {
    if ! load_config; then
        printf '# boxctl: %s 不存在\n' "${BOXCTL_CONFIG}"
        log "配置不存在：cp ${BOXCTL_TEMPLATE} ${BOXCTL_CONFIG} 后编辑"
        return 0
    fi

    # 拿到镜像的人得有个发现入口：什么都没启用时提示一次。只在 stderr 是终端时打——平台
    # 的启动脚本 source .bashrc 时没有 tty，不该往它的日志里灌东西；scp 只看 stdout，
    # 不受影响。配好之后这行自然消失。
    if [[ -t 2 ]] && ! any_enabled; then
        log "还没启用任何服务。看 boxctl help，配置在 ${BOXCTL_CONFIG}"
    fi

    # 只导出服务真正要用的那几个。用户自己的 shell 偏好（缓存重定向、工具链开关）不归
    # boxctl 管，写进 /root/.bashrc 就行——它跨重启在。
    local s
    for s in $(service_names); do
        "${s}_env"
    done
}

cmd_start() {
    load_config || die "配置不存在：${BOXCTL_CONFIG}"
    apply_env
    local s list
    list="$(targets "${1:-all}")"
    for s in ${list}; do
        if "${s}_running"; then
            log "${s}: 已在跑，跳过"
            continue
        fi
        log "${s}: 启动"
        "${s}_start"
    done
}

cmd_stop() {
    load_config || die "配置不存在：${BOXCTL_CONFIG}"
    apply_env
    local s list
    list="$(targets "${1:-all}")"
    for s in ${list}; do
        if ! "${s}_running"; then
            log "${s}: 没在跑，跳过"
            continue
        fi
        log "${s}: 停止"
        "${s}_stop"
    done
}

cmd_restart() {
    load_config || die "配置不存在：${BOXCTL_CONFIG}"
    apply_env
    local s list
    list="$(targets "${1:-all}")"
    for s in ${list}; do
        log "${s}: 重启"
        "${s}_restart"
    done
}

cmd_status() {
    load_config || die "配置不存在：${BOXCTL_CONFIG}"
    apply_env
    local s list state
    list="$(targets "${1:-all}")"
    for s in ${list}; do
        if ! "${s}_enabled"; then
            state="disabled"
        elif "${s}_running"; then
            state="running"
        else
            state="stopped"
        fi
        printf '%-10s %s\n' "${s}" "${state}"
        "${s}_status" || true
    done
}

cmd_logs() {
    load_config || die "配置不存在：${BOXCTL_CONFIG}"
    apply_env
    local s="${1:-}"
    [[ -n "${s}" ]] || die "用法：boxctl logs <$(service_names | paste -sd'|' -)> [子服务]"
    known_service "${s}" || die "未知服务：${s}"
    shift
    "${s}_logs" "$@"
}

# 登录时调用：只拉起「已启用且没在跑」的。判据是服务真的在不在，不是「这个容器生命
# 周期跑过没有」——后者要维护状态文件，还漏掉「服务被 OOM 全灭但 PID 1 没变」这一类。
cmd_boot() {
    # 同时开几个 shell 时只让一个真的去 start。锁默认放 /run：共享卷可能是网络文件
    # 系统，那上面的 flock 不可靠；/run 又是每个容器私有且重启即空的。
    exec 9>"${BOXCTL_LOCK:-/run/boxctl-boot.lock}"
    flock -n 9 || exit 0

    # 先读配置再算日志目录，否则 BOXCTL_STATE_DIR 还没生效，日志会落到容器本地。
    if ! load_config; then
        log "配置不存在：${BOXCTL_CONFIG}"
        return 0
    fi

    apply_env

    local dir
    dir="$(log_dir)"
    install -d -m 0755 "${dir}"

    {
        local s
        for s in $(service_names); do
            "${s}_enabled" || continue
            if "${s}_running"; then
                continue
            fi
            printf '==== %s boot %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${s}"
            "${s}_start" || printf 'boot: %s 启动失败（退出码 %s）\n' "${s}" "$?"
        done
    } >> "${dir}/boot.log" 2>&1
}

cmd_config() {
    if [[ ! -r "${BOXCTL_CONFIG}" ]]; then
        printf '配置文件  %s  (不存在，cp %s 过去)\n' "${BOXCTL_CONFIG}" "${BOXCTL_TEMPLATE}"
        return 1
    fi
    printf '配置文件  %s\n' "${BOXCTL_CONFIG}"
    load_config

    # 字段清单以模板为准（含注释掉的），这样填了什么、漏了什么一眼能看全。
    local name value
    for name in $(grep -oE 'BOXCTL_[A-Z0-9_]+=' "${BOXCTL_TEMPLATE}" \
                      | tr -d '=' | sort -u); do
        value="${!name:-}"
        if [[ -z "${value}" ]]; then
            printf '  %-28s -\n' "${name}"
        elif [[ "${name}" == *_DIR ]] && [[ ! -d "${value}" ]]; then
            printf '  %-28s %s  <-- 目录不存在\n' "${name}" "${value}"
        elif [[ "${name}" == *_CONF || "${name}" == *_PUBKEY ]] && [[ ! -r "${value}" ]]; then
            printf '  %-28s %s  <-- 文件读不到\n' "${name}" "${value}"
        else
            printf '  %-28s %s\n' "${name}" "${value}"
        fi
    done

}

cmd_doctor() {
    local rc=0 c
    for c in python3 flock ss supervisord wireproxy mihomo vpn fsferry-agent h200; do
        if command -v "${c}" >/dev/null 2>&1; then
            printf '  ok      %s\n' "${c}"
        else
            printf '  MISSING %s\n' "${c}"
            rc=1
        fi
    done
    return "${rc}"
}

usage() {
    cat <<EOF
用法: boxctl <命令> [服务]

  start   [all|服务]   启动；已在跑的跳过
  stop    [all|服务]   停止
  restart [all|服务]   硬重启，重新加载配置
  status  [all|服务]   看状态
  logs    <服务> [子]  看日志
  boot                 幂等，只拉起「已启用且没在跑」的；登录时由 .bashrc 调用
  env                  打印要 export 的 shell 片段，供 eval 使用
  config               打印生效配置并校验路径
  doctor               依赖自检

服务: $(service_names | tr '\n' ' ')
配置: ${BOXCTL_CONFIG}
文档: ${BOXCTL_HOME}/README.md
      ${BOXCTL_HOME}/vpn/README.md
      ${BOXCTL_HOME}/fsferry/README.md
EOF
}

main() {
    [[ -d "${SERVICE_DIR}" ]] || die "服务目录不存在：${SERVICE_DIR}"
    load_services

    local action="${1:-}"
    if [[ $# -gt 0 ]]; then
        shift
    fi

    case "${action}" in
    start)   cmd_start "$@" ;;
    stop)    cmd_stop "$@" ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status "$@" ;;
    logs)    cmd_logs "$@" ;;
    boot)    cmd_boot "$@" ;;
    env)     cmd_env "$@" ;;
    config)  cmd_config "$@" ;;
    doctor)  cmd_doctor "$@" ;;
    ""|-h|--help|help) usage ;;
    *)       usage; exit 2 ;;
    esac
}

main "$@"
