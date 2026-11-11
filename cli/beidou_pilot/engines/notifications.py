"""读取原生通知气泡，按当前游戏窗口投影控件位置。"""

import json

from ..observations import observe_domain, project_geometry


if __name__ == "__main__":
    print(json.dumps(project_geometry(observe_domain("notifications")), ensure_ascii=False))
