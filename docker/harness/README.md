# Codex 游戏 AI 容器

从仓库根构建，构建上下文仅为本目录：

```bash
docker build -t local/beidou-game-ai:0.167.0 docker/harness
```

镜像以官方 `node:24.22.2-bookworm-slim` 为基础，通过 `npm install --global @openai/codex@0.167.0` 安装固定版本。Node/npm 和 npm 自动选择的完整平台包保留在运行层，不手工解包或复制上游内部文件，避免漏装 Code Mode 等功能所需的配套程序。本次验证平台为 Linux amd64。

固定 npm 包没有 Codex 根 LICENSE/NOTICE，构建从对应 `rust-v0.167.0` 发行 tag 补齐 Apache-2.0 LICENSE 与 NOTICE（包含 Ratatui 声明）；平台包自带的其他许可、Node/npm 和发行版许可保留原位置，本项目 AGPL-3.0-only LICENSE 位于 `/usr/share/licenses/beidou-pilot/`。版本和来源见 Dockerfile，不再维护额外镜像 digest、下载包或许可 hash 校验，标准包管理器使用默认完整性校验。构建不登录或调用模型，不包含角色资料、认证、游戏资源或客户端。

镜像以 UID/GID `1000:1000` 运行，默认 `HOME=/home/game`，Codex 状态位于 `/home/game/.codex`。宿主专用状态目录必须允许 UID 1000 写入；需要持续会话时，仅将该目录挂到此位置。工作目录 `/game` 为空，不挂开发仓库、宿主 HOME 或 Docker socket。

运行时可只读挂载专用 provider TOML 到 `/run/game-ai/provider.toml`。入口每次用该文件初始化独立 config.toml；未提供时使用空配置与内置 OpenAI provider。API key 通过运行时显式环境变量提供。使用专用文件认证时，可将初始化资料只读挂到 `/run/game-ai/auth.json`；入口仅在状态目录尚无 auth.json 时复制，后续刷新结果保留在独立状态中。不要挂载整份开发 Codex 配置或认证目录，不把秘密作为镜像构建参数。

入口默认启动 stdio app-server，可由宿主薄控制器覆盖参数。它强制关闭无关执行、技能、MCP app 集成、插件、多代理与记忆等功能，使用短游戏基础指令，并保留 Codex 内置 `request_user_input` 作为开发 AI 询问通道。专用 provider 文件不应包含 MCP、技能、hooks 或开发指令；控制器仍需核对实际配置来源、技能/MCP 和最终请求工具清单。

Codex 的 `exec` / `wait` 编排壳仍可出现在最终工具集合中，只能编排独立 `game` 命名空间下的 `game_*` 游戏工具及原生询问入口。入口通过公开的 `features.code_mode.excluded_tool_namespaces=["functions","clock"]` 排除默认开发工具命名空间，并以 `features.sleep_tool=false` 关闭 `sleep` 工具；完整请求合同以这些产品默认设置验证，不依赖调用方再补裁剪参数。

默认模型为 `gpt-6-luna`；宿主控制器在核对实际模型清单后选择最低支持的思考档位，并可显式选择 `gpt-6.1-terra`。入口不固定上下文窗口或自动整理阈值，沿用所选模型 metadata；记录实际有效窗口与 token 后再调整。宿主控制器负责游戏 CLI、工具调用和放键确认，停止此容器不会自动关闭游戏客户端。

标准 `HTTP_PROXY` / `HTTPS_PROXY` 构建参数可用于受限网络；代理与认证不写入镜像。
