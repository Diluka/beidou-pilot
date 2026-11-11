# BeiDou-ijl15

本目录集成 [BeiDouMS/BeiDou-ijl15](https://github.com/BeiDouMS/BeiDou-ijl15) 的桥接 DLL 工程，并由 beidou-pilot 维护原版客户端适配与共享 Lua Runtime。上游来源与许可继续随源码和构建清单保留。

## 本项目构建与使用

客户端统一从仓库根的 Docker 入口构建并启动：

```bash
./beidou-pilot --workbench /external/gui-workbench --backend beidou --json build
./beidou-pilot --workbench /external/gui-workbench --backend beidou --json open
./beidou-pilot --workbench /external/gui-workbench --json close
```

GUI 默认通过 GitHub CLI `gh` 获取所选提交成功的 `agent-bridge` CI 工件，核对原生输入后将 DLL 与清单装入 GUI 镜像。开发时可用 `--bridge-artifact DIR` 显式复用匹配的现成工件，此时无需 `gh`。工作台资源配置只提供原客户端、同源 NX 和可选 XML 路径，具体字段和授权要求见 [CLI](../docs/CLI.md#原版-gui)。

原始客户端目录只读挂载；容器在自己的运行副本中装配镜像内的桥，并保留原图片库 `2ijl15.dll`。原资源文件保持原样，账号、Wine prefix、桥目录和日志外置到所属工作台。

[Windows 构建工作流](../.github/workflows/agent-bridge.yml) 使用 MSVC、Windows SDK 和固定 Detours 源码生成桥工件。解决方案与 [build-agent-bridge.ps1](tools/build-agent-bridge.ps1) 是这条交付链的内部构建步骤；编译器、编码约束、输出与来源清单见[桥构建文档](docs/agent-bridge-build.md)。

## 上游分支背景

上游将主分支的两次 Release 称为 v1 和 v2。其原说明记录：v2 在部分机器进入登录界面时会崩溃，v1 没有这个问题，因此此分支继承 v1 并单独开发，主要服务于北斗客户端。

上游原说明列出的服务器项目为 [SleepNap/BeiDou](https://github.com/SleepNap/BeiDou)。本仓库不提供服务端，实际操作目标仍按工作台授权和 target 核验。

## 上游更新记录

相比主分支 v1

- 支持中文输入/角色中文名(修复卡门问题)
- 修复滚轮乱飞的问题
- 修复ToolTip超出游戏窗口的问题
- 支持长键盘快捷键
- 交易中心居中
- 增加中文汉化
- 增加魔攻/魔防/命中/回避/跳跃 上限突破
- 增加BossHp百分比显示（在Boss血条的头像下方）
- 免密模式（须服务端支持，客户端仅解除密码限制）
- 调整聊天框文字位置

针对中文环境的一些调整：

1. 装备tooltip字体大小
2. 道具有效期字体大小
3. 修复有效期日期顺序
4. 聊天栏的选项汉化了远征队
5. 在不修改wz的情况下解决了Eqp，Etc汉化后游戏崩溃的问题，Use汉化后吃药没声音的问题
