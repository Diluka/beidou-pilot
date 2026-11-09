#!/bin/bash
set -euo pipefail

if [[ $# != 3 ]]; then
  echo 'Usage: prepare-client.sh CLIENT_ROOT OUTPUT_ROOT BRIDGE_DLL' >&2
  exit 2
fi
client_root=$(realpath -e -- "$1")
output_root=$(realpath -m -- "$2")
bridge_dll=$(realpath -e -- "$3")
if [[ "$output_root" == "$client_root" || "$output_root" == "$client_root/"* ]]; then
  echo 'The runtime copy must be outside the source client directory.' >&2
  exit 2
fi
if [[ ! -f "$client_root/BeiDou.exe" || ! -f "$client_root/2ijl15.dll" || ! -d "$client_root/Data" || ! -f "$bridge_dll" ]]; then
  echo 'The client requires BeiDou.exe, 2ijl15.dll, Data, and the selected bridge DLL.' >&2
  exit 2
fi

mkdir -- "$output_root"
shopt -s dotglob nullglob
for source in "$client_root"/*; do
  if [[ "${source##*/}" == Data ]]; then
    ln -s -- "$source" "$output_root/Data"
  else
    cp -aL --reflink=auto -- "$source" "$output_root/"
  fi
done
rm -f -- "$output_root/ijl15.dll"
cp -- "$bridge_dll" "$output_root/ijl15.dll"
