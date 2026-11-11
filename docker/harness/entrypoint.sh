#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
set -eu
umask 077

# The caller supplies this instance's private state, never a development HOME.
: "${CODEX_HOME:?需要本实例专用的 CODEX_HOME}"
mkdir -p "$CODEX_HOME"
if [ -n "${BEIDOU_GAME_AI_PROVIDER_CONFIG:-}" ]; then
    cp "$BEIDOU_GAME_AI_PROVIDER_CONFIG" "$CODEX_HOME/config.toml"
else
    : > "$CODEX_HOME/config.toml"
fi
if [ -n "${BEIDOU_GAME_AI_AUTH_FILE:-}" ] && [ ! -f "$CODEX_HOME/auth.json" ]; then
    cp "$BEIDOU_GAME_AI_AUTH_FILE" "$CODEX_HOME/auth.json"
fi

case "${BEIDOU_GAME_AI_READ_ONLY:-0}" in
    0) shell_tool=true; excluded_namespaces='["clock"]' ;;
    1) shell_tool=false; excluded_namespaces='["functions","clock"]' ;;
    *) printf '%s\n' 'BEIDOU_GAME_AI_READ_ONLY 只允许 0 或 1。' >&2; exit 2 ;;
esac
if [ "$#" -eq 0 ]; then set -- app-server --stdio --strict-config; fi
cd /game

exec /usr/local/bin/codex "$@" \
    -c 'model="gpt-6-luna"' \
    -c 'model_instructions_file="/opt/beidou-game-ai/instructions.md"' \
    -c 'developer_instructions=""' \
    -c 'project_doc_max_bytes=0' \
    -c 'check_for_update_on_startup=false' \
    -c 'web_search="disabled"' \
    -c 'agents.enabled=false' \
    -c 'skills.bundled.enabled=false' \
    -c "features.shell_tool=$shell_tool" \
    -c "features.code_mode.excluded_tool_namespaces=$excluded_namespaces" \
    -c 'features.sleep_tool=false' \
    -c 'features.apps=false' \
    -c 'features.multi_agent=false' \
    -c 'features.memories=false' \
    -c 'features.goals=false' \
    -c 'features.hooks=false' \
    -c 'features.plugins=false' \
    -c 'features.remote_plugin=false' \
    -c 'features.plugin_discovery_prefetch=false' \
    -c 'features.image_generation=false' \
    -c 'features.view_image=false' \
    -c 'features.skill_search=false' \
    -c 'features.skill_mcp_dependency_install=false' \
    -c 'features.default_mode_request_user_input=true' \
    -c 'analytics.enabled=false'
