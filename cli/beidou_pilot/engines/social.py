"""读取本端社交邀请和队伍事实，邀请坐标只投影当前窗口。"""

import argparse
import json

from ..observations import observe_domain, project_geometry


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["invitations", "party"])
    arguments = parser.parse_args()
    report = observe_domain(arguments.domain)
    if arguments.domain == "invitations":
        report = project_geometry(report)
    print(json.dumps(report, ensure_ascii=False))
