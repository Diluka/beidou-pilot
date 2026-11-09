#!/bin/bash
set -euo pipefail
umask 077

export DISPLAY=:97 WINEPREFIX=/work/prefix WINEARCH=win32 WINEDEBUG="${WINEDEBUG:--all}"
export WINEDLLOVERRIDES='ijl15=n,b;mscoree,mshtml='
run_dir="/work/runs/$RUN_ID"
mkdir -p -- "$run_dir" /work/prefix /work/bridge
rm -rf -- /work/client
/opt/beidou/prepare-client.sh /client /work/client /overrides/ijl15.dll

desktop_pids=()
cleanup() {
  status=$?
  trap - EXIT TERM INT
  if ! wineserver -k; then
    echo 'Failed to stop the Wine processes in this instance prefix.' >&2
    status=1
  fi
  for child in "${desktop_pids[@]}"; do
    if kill -0 "$child" 2>/dev/null; then
      kill "$child"
    fi
  done
  wait
  exit "$status"
}
trap cleanup EXIT
trap 'exit 0' TERM INT

Xvfb :97 -screen 0 1280x720x24 -nolisten tcp >"$run_dir/xvfb.log" 2>&1 &
xvfb_pid=$!
desktop_pids+=("$xvfb_pid")
until xdpyinfo >/dev/null 2>&1; do
  kill -0 "$xvfb_pid"
  sleep 0.1
done
xfwm4 --compositor=off >"$run_dir/window-manager.log" 2>&1 &
wm_pid=$!
desktop_pids+=("$wm_pid")
/opt/VirtualGL/bin/vglrun -d egl glxinfo -B >"$run_dir/renderer.log" 2>&1
wineboot -u >>"$run_dir/wine.log" 2>&1
wine regedit /S /opt/beidou/chinese-fontlink.reg >>"$run_dir/wine.log" 2>&1

cd /work/client
/opt/VirtualGL/bin/vglrun -d egl wine BeiDou.exe >>"$run_dir/wine.log" 2>&1 &
game_pid=$!
while true; do
  if ! kill -0 "$game_pid" 2>/dev/null; then
    wait "$game_pid"
    exit 0
  fi
  kill -0 "$xvfb_pid" "$wm_pid"
  sleep 0.2
done
