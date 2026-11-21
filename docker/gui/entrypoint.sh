#!/bin/bash
set -euo pipefail
target_host="$TARGET_IP"
target_ip=$(getent ahostsv4 "$target_host" | awk 'NR == 1 {print $1}')
[ -n "$target_ip" ] || { echo "无法解析目标服务 $target_host。" >&2; exit 2; }
iptables -F
iptables -t nat -F
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p tcp -d "$target_ip" -m multiport --dports 8484,7575,7576,7577 -j ACCEPT
iptables -t nat -A OUTPUT -d 127.0.0.1 -p tcp -m multiport --dports 8484,7575,7576,7577 -j DNAT --to-destination "$target_ip"
iptables -t nat -A POSTROUTING -d "$target_ip" -p tcp -m multiport --dports 8484,7575,7576,7577 -j MASQUERADE
ip6tables -P INPUT DROP
ip6tables -P FORWARD DROP
ip6tables -P OUTPUT DROP
ip6tables -A INPUT -i lo -j ACCEPT
ip6tables -A OUTPUT -o lo -j ACCEPT
exec setpriv --reuid 1000 --regid 1000 --groups "$RENDER_GID" --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs --reset-env \
  env LANG=zh_CN.UTF-8 DISPLAY=:97 WINEPREFIX="$CLIENT_ROOT/runtime/prefix" WINEARCH=win32 WINEDEBUG="${WINEDEBUG:--all}" \
  RUN_ID="$RUN_ID" MAPLE_BACKEND=beidou MAPLE_INSTANCE="$MAPLE_INSTANCE" CLIENT_ROOT="$CLIENT_ROOT" \
  CLIENT_IMAGE_ID="$CLIENT_IMAGE_ID" MAPLE_RESOURCES_CONFIG="$MAPLE_RESOURCES_CONFIG" \
  PYTHONPATH=/opt/beidou-pilot/cli PYTHONDONTWRITEBYTECODE=1 MAPLE_BRIDGE_DIR="$MAPLE_BRIDGE_DIR" \
  MAPLE_DATA_ROOT="$MAPLE_DATA_ROOT" BEIDOU_CACHE_DIR="$BEIDOU_CACHE_DIR" /opt/beidou/bootstrap.sh
