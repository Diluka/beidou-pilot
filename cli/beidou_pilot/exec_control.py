"""容器内命令的执行登记，供宿主定向转发取消。"""

from collections.abc import Callable
import json
import os
from pathlib import Path
import re
import signal
import sys


def run(main: Callable[[], int]) -> int:
    if os.geteuid() == 0 and os.environ.get("MAPLE_BACKEND") == "beidou":
        os.setgroups([])
        os.setgid(1000)
        os.setuid(1000)
    root = Path(os.environ.get("CLIENT_ROOT", "/work"))
    cancelling = len(sys.argv) == 3 and sys.argv[1] == "--cancel-exec"
    inherited_token = os.environ.pop("BEIDOU_EXEC_TOKEN", None)
    token = sys.argv[2] if cancelling else inherited_token
    if token is None:
        return main()
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise SystemExit("执行 token 无效。")
    directory = root / "state"
    directory.mkdir(parents=True, exist_ok=True)
    pid_file = directory / ("exec-" + token + ".pid")
    cancelled = directory / ("exec-" + token + ".cancel")
    if cancelling:
        cancelled.touch(mode=0o600)
        try:
            pid = int(pid_file.read_text())
            os.kill(pid, signal.SIGINT)
        except (FileNotFoundError, ProcessLookupError):
            pass  # 命令尚未登记或已自然结束；启动入口也会检查取消标记。
        return 0
    pid_file.write_text(str(os.getpid()))
    try:
        if cancelled.exists():
            raise KeyboardInterrupt
        return main()
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": {"code": "interrupted", "message": "执行已取消。"}}))
        return 130
    finally:
        pid_file.unlink(missing_ok=True)
        cancelled.unlink(missing_ok=True)
