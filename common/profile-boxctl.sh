# /etc/profile.d/00-boxctl.sh —— 比 .bashrc 更早的触发点。
#
# 平台用自己的脚本覆盖镜像 ENTRYPOINT，我们拿不到容器启动那一刻。但如果平台那个启动
# 脚本是 login shell（bash -l，或它 source 了 /etc/profile），这里就会在容器起来时执行，
# 不用等人登录。命中与否都无害：boot 幂等，且有 flock，没命中就是一次空转。
#
# 用 POSIX 语法：/etc/profile 可能由 dash 解释，[[ ]] 在那里是语法错误。
#
# 一律吞掉错误：这段跑在平台的启动路径上，boxctl 出问题不该把平台的启动脚本带崩。
if command -v boxctl >/dev/null 2>&1; then
    eval "$(boxctl env 2>/dev/null)" || true
    (boxctl boot >/dev/null 2>&1 &) || true
fi
