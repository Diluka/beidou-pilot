FROM node:24.22.2-bookworm-slim

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
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o 1000 -g 1000 /game /home/game /home/game/.codex /run/game-ai

COPY LICENSE /usr/share/licenses/beidou-pilot/LICENSE
COPY --chmod=755 entrypoint.sh /opt/beidou-game-ai/entrypoint.sh
COPY instructions.md /opt/beidou-game-ai/instructions.md

LABEL org.opencontainers.image.title="beidou-pilot-game-ai" \
      org.opencontainers.image.description="Isolated Codex app-server for bounded game decisions" \
      org.opencontainers.image.licenses="AGPL-3.0-only AND Apache-2.0" \
      org.opencontainers.image.source="https://github.com/Diluka/beidou-pilot" \
      io.beidou.codex.version="${CODEX_VERSION}" \
      io.beidou.codex.source-tag="rust-v${CODEX_VERSION}"

ENV HOME=/home/game LANG=C.UTF-8
USER 1000:1000
WORKDIR /game
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/beidou-game-ai/entrypoint.sh"]
CMD ["app-server", "--stdio", "--strict-config"]
