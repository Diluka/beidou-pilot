ARG CLIENT_IMAGE

FROM node:24.22.2-bookworm-slim AS codex
ARG CODEX_VERSION=0.167.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && npm install --global @openai/codex@${CODEX_VERSION} \
    && npm cache clean --force \
    && install -d /usr/share/licenses/codex \
    && curl --fail --location --retry 3 \
        https://raw.githubusercontent.com/openai/codex/rust-v${CODEX_VERSION}/LICENSE \
        --output /usr/share/licenses/codex/LICENSE \
    && curl --fail --location --retry 3 \
        https://raw.githubusercontent.com/openai/codex/rust-v${CODEX_VERSION}/NOTICE \
        --output /usr/share/licenses/codex/NOTICE \
    && rm -rf /var/lib/apt/lists/*

FROM ${CLIENT_IMAGE} AS runtime
ARG CLIENT_IMAGE
ARG CLIENT_USER=65532:65532
ARG CODEX_VERSION=0.167.0
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libatomic1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 755 /game /opt/beidou-game-ai/harness

COPY --from=codex /usr/local/ /usr/local/
COPY --from=codex /opt/ /opt/
COPY --from=codex /usr/share/licenses/codex/ /usr/share/licenses/codex/
COPY --chmod=755 docker/harness/entrypoint.sh /opt/beidou-game-ai/entrypoint.sh
COPY docker/harness/instructions.md /opt/beidou-game-ai/instructions.md
COPY --chmod=755 harness/game-ai /opt/beidou-game-ai/harness/game-ai
COPY harness/beidou_game_ai/ /opt/beidou-game-ai/harness/beidou_game_ai/
COPY .agents/skills/beidou-pilot-client/ /game/.agents/skills/beidou-pilot-client/
COPY .agents/skills/beidou-game-guide/ /game/.agents/skills/beidou-game-guide/
COPY README.md /game/README.md
COPY docs/CLI.md docs/LUA_API.md docs/PLAY_GUIDE.md docs/HARNESS.md /game/docs/
COPY docs/CONTROL.md docs/ARCHITECTURE.md docs/CLIENT_LIMITATIONS.md /game/docs/
COPY docker/harness/README.md /game/docker/harness/README.md
RUN ln -s /opt/beidou-game-ai/harness/game-ai /usr/local/bin/beidou-game-ai \
    && chmod -R a+rX /game /opt/beidou-game-ai /usr/share/licenses/codex

LABEL org.opencontainers.image.title="beidou-pilot-game-ai" \
      org.opencontainers.image.description="Client runtime with Codex, harness and the client CLI skill" \
      org.opencontainers.image.licenses="AGPL-3.0-only AND Apache-2.0" \
      org.opencontainers.image.source="https://github.com/Diluka/beidou-pilot" \
      beidou.harness="codex" \
      io.beidou.client.base="${CLIENT_IMAGE}" \
      io.beidou.codex.version="${CODEX_VERSION}" \
      io.beidou.codex.source-tag="rust-v${CODEX_VERSION}"

ENV PYTHONPATH=${PYTHONPATH}:/opt/beidou-game-ai/harness
USER ${CLIENT_USER}
