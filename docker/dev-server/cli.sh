#!/bin/sh
# Runs in the verified game container's /opt/server_backup working directory.
# 官方 beidou-cli 完全透传：调用、批量、配置、登录、更新等都由官方命令解释；
# 敏感 API 需要 --force，由官方 CLI 自行确认。register 与 give 是本入口的便捷别名。
set -eu
umask 077
usage() {
    printf '%s\n' '开发服管理：官方 beidou-cli 完全透传（version | apis | call | batch | login | config | update | uninstall 等）；便捷别名 register（stdin 单行 JSON）与 give WORLD CID mesos|exp|map NUMBER | give WORLD CID item ITEM_ID COUNT。'
}
invalid() { usage >&2; exit 2; }
positive() { case $1 in ''|0*|*[!0-9]*) return 1;; esac; [ "${#1}" -le 10 ] && [ "$1" -le 2147483647 ]; }
failed() { echo '开发服管理调用未确认成功；请核对目标与当前状态，不要盲目重试。' >&2; exit 1; }

case ${1-} in
    --help|-h)
        [ "$#" = 1 ] || invalid
        usage
        exit 0;;
    register)
        [ "$#" = 1 ] || invalid
        IFS= read -r body || [ -n "$body" ] || invalid
        # Reject extra input. Pass only one object to the fixed registration endpoint.
        if IFS= read -r extra || [ -n "$extra" ]; then invalid; fi
        case $body in '{'*'}') ;; *) invalid;; esac
        # The Java launcher reads its argument file on stdin; the password is never a
        # host/Docker/Java process argument. Quote JSON as ONE Java argument, not CLI source.
        response=$({
            printf '%s\n' -Duser.home=/run/beidou-runtime -jar /run/beidou-dev/beidou-cli.jar call --force POST /account/v1
            printf '"'; printf '%s' "$body" | sed 's/[\\"]/\\&/g'; printf '"\n'
        } | ./jdk-*/bin/java @/dev/stdin 2>/dev/null) || failed
        unset body;;
    give)
        [ "$#" = 5 ] || [ "$#" = 6 ] || invalid
        { [ "$2" = 0 ] || positive "$2"; } && positive "$3" && positive "$5" || invalid
        [ "$2" -le 255 ] || invalid
        case $4 in
            mesos) type=3;; exp) type=4;; map) type=13;; item) type=5;; *) invalid;;
        esac
        if [ "$type" = 5 ]; then
            [ "$#" = 6 ] && positive "$6" && [ "$6" -le 32767 ] || invalid
            fields="\"id\":$5,\"quantity\":$6"
        else
            [ "$#" = 5 ] || invalid
            fields="\"quantity\":$5"
        fi
        response=$({
            printf '%s\n' -Duser.home=/run/beidou-runtime -jar /run/beidou-dev/beidou-cli.jar call --force POST /give/v1/resource
            printf '"'; printf '{"worldId":%s,"playerId":%s,"type":%s,%s}' "$2" "$3" "$type" "$fields" | sed 's/[\\"]/\\&/g'; printf '"\n'
        } | ./jdk-*/bin/java @/dev/stdin 2>/dev/null) || failed;;
    *)
        exec ./jdk-*/bin/java -Duser.home=/run/beidou-runtime -jar /run/beidou-dev/beidou-cli.jar "$@";;
esac
# The pinned CLI pretty-prints its JSON envelope. Discard diagnostics and raw
# mutation responses (including malformed credential input); report business codes.
code=$(printf '%s\n' "$response" | awk '$1 == "\"code\"" && $2 == ":" && $3 ~ /^[0-9]+,$/ {print substr($3, 1, length($3)-1); exit}')
[ -n "$code" ] || failed
printf '{"code":%s}\n' "$code"
[ "$code" = 20000 ]
