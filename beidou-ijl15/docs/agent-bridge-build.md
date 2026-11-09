# Maple 桥接 DLL 构建

在 Visual Studio 2022 C++ 与 Windows 10 SDK 环境中，从干净且已提交的源码运行：

```powershell
./beidou-ijl15/tools/build-agent-bridge.ps1
```

从仓库根执行，先用 `git submodule update --init --recursive` 初始化固定依赖。脚本将 Detours 的固定源码复制到忽略的 `beidou-ijl15/out/detours/`，通过 VS2022 的 x86 工具链和 NMake 构建静态库，再构建解决方案的 `Release x86`（对应项目 `Release|Win32`），以命令行选择 `v143`。原项目的 `v142` 默认值保持不变；不依赖预编译 Detours 库，不改写第三方子模块。

上游文件混用 UTF-8 BOM 和无 BOM 的 GBK。编译器按 BOM 识别 Unicode 文件，其余源文件按 CP936 读取；窄字符串按 CP936 写入 DLL，保留客户端中文文本。新增含中文的 UTF-8 源文件应带 BOM，不能全局改成 `/utf-8`。

GitHub Actions 工作流 [agent-bridge.yml](../../.github/workflows/agent-bridge.yml) 在 PR 创建/更新和 `main` 推送时运行，也支持手动运行。`Windows bridge build` 使用 `windows-2022` 的 VS2022 工具链，成功后上传 `maple-agent-bridge-win32` 工件。

输出目录 `beidou-ijl15/out/agent-bridge/` 包含 DLL、可用的 PDB、许可证、桥与 Detours 构建日志、导出表、运行库依赖与 `manifest.json`。清单记录源码 commit/tree、目标 EXE 和 `2ijl15.dll` 固定 SHA256、本次 DLL 与 Detours 静态库 SHA256、Lua/Detours 来源、实际 MSVC/SDK 与 runner 身份。工件不包含原版客户端、WZ、配置或账号数据。

构建会核对 PE 文件为 x86 DLL，并保留原图片库的六个导出函数。这些检查证明产物结构与来源；游戏内桥接、中文显示、原 DLL 转发和生命周期行为仍需使用匹配客户端单独验收。
