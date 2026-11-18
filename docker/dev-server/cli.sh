#!/bin/sh
# Runs in the verified game container's /opt/server_backup working directory.
set -eu
umask 077
usage() {
    printf '%s\n' '开发服管理：version | apis [server|account|character|give] | call GET /server/v1/{version,online,world/list} | register（从 stdin 读取单行 JSON） | give WORLD CID mesos|exp|map NUMBER | give WORLD CID item ITEM_ID COUNT'
}
invalid() { usage >&2; exit 2; }
positive() { case $1 in ''|0*|*[!0-9]*) return 1;; esac; [ "${#1}" -le 10 ] && [ "$1" -le 2147483647 ]; }
official() { ./jdk-*/bin/java -Duser.home=/run/beidou-runtime -jar /run/beidou-dev/beidou-cli.jar "$@"; }
failed() { echo '开发服管理调用未确认成功；请核对目标与当前状态，不要盲目重试。' >&2; exit 1; }

case ${1-} in
    --help|-h) [ "$#" = 1 ] || invalid; usage; exit 0;;
    version|--version|-v) [ "$#" = 1 ] || invalid; official version; exit;;
    apis)
        case $# in 1) ;; 2) case $2 in server|account|character|give) ;; *) invalid;; esac;; *) invalid;; esac
        official "$@"; exit;;
    call)
        [ "$#" = 3 ] && [ "$2" = GET ] || invalid
        case $3 in /server/v1/version|/server/v1/online|/server/v1/world/list) ;; *) invalid;; esac
        response=$(official call GET "$3" 2>/dev/null) || failed;;
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
        response=$(official call --force POST /give/v1/resource "{\"worldId\":$2,\"playerId\":$3,\"type\":$type,$fields}" 2>/dev/null) || failed;;
    *) invalid;;
esac
# The pinned CLI pretty-prints its JSON envelope. Discard diagnostics and raw
# mutation responses (including malformed credential input); report business codes.
code=$(printf '%s\n' "$response" | awk '$1 == "\"code\"" && $2 == ":" && $3 ~ /^[0-9]+,$/ {print substr($3, 1, length($3)-1); exit}')
[ -n "$code" ] || failed
if [ "$1" = call ] && [ "$code" = 20000 ]; then
    printf '%s\n' "$response" | awk '/^\{$/ {json=1} json {print} /^\}$/ && json {exit}'
else
    printf '{"code":%s}\n' "$code"
fi
[ "$code" = 20000 ]
