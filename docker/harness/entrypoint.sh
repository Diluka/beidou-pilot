#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
set -eu
umask 077

# This is the image user's own default Codex home, never a host development home.
mkdir -p /home/game/.codex
if [ -f /run/game-ai/provider.toml ]; then
    cp /run/game-ai/provider.toml /home/game/.codex/config.toml
else
    : > /home/game/.codex/config.toml
fi
if [ -f /run/game-ai/auth.json ] && [ ! -f /home/game/.codex/auth.json ]; then
    cp /run/game-ai/auth.json /home/game/.codex/auth.json
fi

exec /usr/local/bin/codex "$@" \
    -c 'model="gpt-6-luna"' \
    -c 'model_instructions_file="/opt/beidou-game-ai/instructions.md"' \
    -c 'developer_instructions=""' \
    -c 'project_doc_max_bytes=0' \
    -c 'check_for_update_on_startup=false' \
    -c 'web_search="disabled"' \
    -c 'agents.enabled=false' \
    -c 'skills.bundled.enabled=false' \
    -c 'features.shell_tool=false' \
    -c 'features.code_mode.excluded_tool_namespaces=["functions","clock"]' \
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
