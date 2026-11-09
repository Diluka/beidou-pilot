"""核验原客户端布局及本地明确安装的桥接构建。"""

import hashlib
import json
from pathlib import Path

from .errors import ClientError
from .resources import load_resources


CLIENT_SHA256 = "1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df"
IJL_SHA256 = "db2dbe66ad6217fcd43772a2df04aac52f496f44bdc4623b0a66f143ed3b29aa"
PROXY_SHA256 = "f991f9f77545b479758641dbf61c9bcd011008556ade775257b29e7282dc2558"


def verify_binaries(root: Path) -> bool:
    """桥接构建只支持固定 V17 EXE，返回是否已安装本地登记构建。"""
    resources = load_resources(root)
    manifest_path = root / "state/agent-bridge-build.json"
    expected_dll = IJL_SHA256
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if (manifest.get("schema_version") != 1
                or manifest.get("target", {}).get("executable_sha256") != CLIENT_SHA256
                or manifest.get("target", {}).get("proxy_sha256") != PROXY_SHA256):
            raise ClientError("bridge_build_mismatch", "已登记桥接构建与当前 V17 客户端基线不符。")
        expected_dll = manifest.get("artifact", {}).get("sha256")
        if not isinstance(expected_dll, str) or len(expected_dll) != 64:
            raise ClientError("bridge_build_invalid", "桥接构建清单缺少 DLL SHA256。")
    for path, expected in ((resources.gui_client / "BeiDou.exe", CLIENT_SHA256),
                           (resources.gui_dll, expected_dll),
                           (resources.gui_client / "2ijl15.dll", PROXY_SHA256)):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected:
            raise ClientError("client_binary_mismatch", path.name + "与已登记客户端版本不符。")
    return manifest_path.is_file()
