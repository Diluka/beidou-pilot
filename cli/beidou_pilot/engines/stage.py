#!/usr/bin/env python3
"""通过客户端原生 API 读取启动和登录阶段，保留桌面坐标投影。"""

import json
from pathlib import Path
import re

from ..errors import ClientError, JsonObject
from ..observations import NativeObserver, project_geometry


def read_stage(root: Path | None = None, backend: str | None = None) -> JsonObject:
    observer = NativeObserver(root, backend)
    if observer.session is None:
        return {"stage": "STOPPED", "running": False, "readonly": True,
                "backend": observer.backend, "source": "client-native-api", "unavailable": []}
    try:
        report = observer.observe("stage")
    except ClientError as error:
        if error.code != "native_observation_not_ready":
            raise
        report = {"stage": "STARTING", "source": "client-native-api", "readonly": True,
                  "backend": observer.backend,
                  "client": {"container_id": observer.session.container_id[:12],
                             "run_id": observer.session.run_id, "run_dir": str(observer.session.run_dir)},
                  "unavailable": [error.message]}
    report["running"] = True
    report = project_geometry(report)
    report["renderer"] = None
    if observer.backend == "beidou":
        for filename in ("renderer.log", "wine.log"):
            path = observer.session.run_dir / filename
            if path.is_file():
                with path.open(errors="replace") as stream:
                    hardware = re.search(r'(?:GL_RENDERER:|renderer=|OpenGL renderer string:).*?(Intel|llvmpipe|softpipe|swrast)',
                                         stream.read(262144), re.IGNORECASE)
                if hardware:
                    report["renderer"] = "intel" if hardware[1].lower() == "intel" else "software"
                    break
    return report


def main() -> None:
    print(json.dumps(read_stage(), ensure_ascii=False))


if __name__ == "__main__":
    main()
