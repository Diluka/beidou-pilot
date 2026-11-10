FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS download

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# The first harness image targets the same Linux amd64 platform as its CI job.
# Keep the release's executable companions together, including its Code Mode host.
RUN test "$(dpkg --print-architecture)" = amd64 \
    && curl --fail --location --retry 3 \
        https://registry.npmjs.org/@openai/codex/-/codex-0.167.0-linux-x64.tgz \
        --output /tmp/codex.tgz \
    && echo '14d73b75a9df52783d4a9eb0f8587b9287cd1c766903a54cc8d296b16ad2dcec07972ebd832c1359e8aec2b50f5e9252868f037f8c6a46c1df1d13f38fbcd842  /tmp/codex.tgz' | sha512sum --check --strict \
    && mkdir -p /package /runtime/bin /runtime/licenses/codex \
    && tar --extract --gzip --file /tmp/codex.tgz --directory /package --strip-components=1 \
    && install -m 755 /package/vendor/x86_64-unknown-linux-musl/bin/* /runtime/bin/ \
    && cp /package/package.json /runtime/licenses/codex/npm-package.json \
    && cp /package/vendor/x86_64-unknown-linux-musl/codex-package.json /runtime/licenses/codex/release.json \
    && curl --fail --location --retry 3 \
        https://raw.githubusercontent.com/openai/codex/086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a/LICENSE \
        --output /runtime/licenses/codex/LICENSE \
    && curl --fail --location --retry 3 \
        https://raw.githubusercontent.com/openai/codex/086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a/NOTICE \
        --output /runtime/licenses/codex/NOTICE \
    && echo 'd17f227e4df5da1600391338865ce0f3055211760a36688f816941d58232d8dc  /runtime/licenses/codex/LICENSE' | sha256sum --check --strict \
    && echo '9d71575ecfd9a843fc1677b0efb08053c6ba9fd686a0de1a6f5382fd3c220915  /runtime/licenses/codex/NOTICE' | sha256sum --check --strict

FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin game \
    && install -d -o 1000 -g 1000 /game /home/game/.codex /run/game-ai

COPY --from=download /runtime/bin/ /usr/local/bin/
COPY --from=download /runtime/licenses/ /usr/share/licenses/
COPY LICENSE /usr/share/licenses/beidou-pilot/LICENSE
COPY --chmod=755 entrypoint.sh /opt/beidou-game-ai/entrypoint.sh
COPY instructions.md /opt/beidou-game-ai/instructions.md

LABEL org.opencontainers.image.title="beidou-pilot-game-ai" \
      org.opencontainers.image.description="Isolated Codex app-server for bounded game decisions" \
      org.opencontainers.image.licenses="AGPL-3.0-only AND Apache-2.0" \
      org.opencontainers.image.source="https://github.com/Diluka/beidou-pilot" \
      io.beidou.codex.version="0.167.0" \
      io.beidou.codex.source-revision="086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a"

ENV HOME=/home/game LANG=C.UTF-8
USER 1000:1000
WORKDIR /game
STOPSIGNAL SIGTERM
ENTRYPOINT ["/opt/beidou-game-ai/entrypoint.sh"]
CMD ["app-server", "--stdio", "--strict-config"]
