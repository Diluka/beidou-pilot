#!/bin/bash
set -euo pipefail
iptables -F
iptables -t nat -F
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP
iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p tcp -d "$TARGET_IP" -m multiport --dports 8484,7575,7576,7577 -j ACCEPT
if [ -n "${MODEL_PROXY_IP:-}" ]; then
    iptables -A OUTPUT -p tcp -d "$MODEL_PROXY_IP" --dport "$MODEL_PROXY_PORT" -j ACCEPT
fi
iptables -t nat -A OUTPUT -d 127.0.0.1 -p tcp -m multiport --dports 8484,7575,7576,7577 -j DNAT --to-destination "$TARGET_IP"
iptables -t nat -A POSTROUTING -d "$TARGET_IP" -p tcp -m multiport --dports 8484,7575,7576,7577 -j MASQUERADE
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
  MAPLE_DATA_ROOT="$MAPLE_DATA_ROOT" /opt/beidou/bootstrap.sh
