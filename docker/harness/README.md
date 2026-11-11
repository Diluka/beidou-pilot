# 客户端内的 Codex 游戏 AI

harness 镜像继承所选提交的 headless 或 GUI 客户端镜像，增加固定版本 Codex、`beidou-game-ai` 和 `beidou-pilot-client` 专用技能。`FROM` 用于打包复用客户端 CLI、原生运行环境、Lua 与版本登记；模型会话和角色经历仍由独立的 `harness/` 消费者维护。LLM 是可选的决策旁路，可与客户端和脚本并行、独立启停。

从仓库根构建，显式提供已构建的客户端镜像。headless 的运行用户为 `65532:65532`；GUI 使用 `CLIENT_USER=root`，由原客户端入口完成防火墙初始化并切换到 GUI 用户。

```bash
docker build --file docker/harness/Dockerfile \
  --build-arg CLIENT_IMAGE=local/beidou-pilot-headless:SOURCE_SHA \
  --build-arg CLIENT_USER=65532:65532 \
  --tag local/beidou-game-ai-headless:SOURCE_SHA .
```

构建通过官方 `node:24.22.2-bookworm-slim` 阶段安装 `@openai/codex@0.167.0`。运行层保留完整 Node/npm 与 npm 选择的平台包，不拆分上游内部文件；Node、npm 及其依赖许可保持原位置。Codex 的 Apache-2.0 LICENSE/NOTICE 从对应 `rust-v0.167.0` tag 补齐到 `/usr/share/licenses/codex/`，客户端许可继续保留在 base 中。构建不登录、不调用模型，不包含账号、角色资料、认证或游戏资源。标准 `HTTP_PROXY` / `HTTPS_PROXY` 构建参数可用于受限网络。

镜像继承客户端原 `ENTRYPOINT`、`CMD`、工作目录及运行环境。容器 PID1 继续管理客户端生命周期，从不自动启动 LLM；只有显式运行 `beidou-game-ai` 时才启动所属客户端内的 harness 和 Codex app-server。客户端和原生脚本无需模型认证、provider 或代理即可启动。日常实例选择及启动用法见[运行说明](../../docs/HARNESS.md)。不挂载宿主源码、开发 HOME 或 Docker socket。

LLM 暂停、停止或退出时，客户端与已经启动的原生任务继续运行；harness 不清理 shell、不取消 Lua、不关闭客户端。持续任务使用原生 `script start`，重接模型先观察当前任务与新鲜状态，不重复启动或抢占。取消原生任务、确认放键和关闭客户端分别由显式操作负责。

专用技能位于 `/game/.agents/skills/beidou-pilot-client`，对应公共 CLI、Lua 和操作参考位于 `/game/docs`。这份技能只有仓库能力和 CLI 用法，不包含部署环境或角色状态。harness 从 `/game` 发现并核对这份技能；其他技能、MCP 和插件不随镜像提供。

`/opt/beidou-game-ai/entrypoint.sh` 是容器内 Codex 的独立启动入口。调用方必须设置本实例专用 `CODEX_HOME`，并提供适当的 `HOME`；状态、provider 和认证文件均放在运行时私密目录。`BEIDOU_GAME_AI_PROVIDER_CONFIG` 可指定专用 provider TOML，`BEIDOU_GAME_AI_AUTH_FILE` 仅在状态内尚无认证时初始化副本；API key 通过显式运行时环境变量提供。不要提供开发配置目录，不把代理或认证写入镜像。实际连接模型时再配置所需网络出口；代理是可选运行配置，不影响客户端和脚本启动。

普通模式开放容器内 shell，agent 根据技能直接使用 `beidou-pilot`。`BEIDOU_GAME_AI_READ_ONLY=1` 关闭 shell，harness 仅提供两个观察工具，不接管输入；不能用只读提示词代替这个工具边界。入口保留 Codex 内置询问，关闭 bundled skills、apps、多代理、记忆、目标、hooks、插件和搜索等无关能力。启动合同核对专用技能、配置来源和实际请求的工具集合。

默认模型为 `gpt-6-luna`；harness 核对实际模型清单后选择最低支持的思考档位，可显式选择 `gpt-6.1-terra`。上下文窗口与整理阈值沿用所选模型 metadata，接口未提供的用量和价格保持未知。
