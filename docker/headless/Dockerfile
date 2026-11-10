FROM debian:bookworm-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ gcc make binutils liblz4-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /source
COPY headless/Makefile headless/Makefile
COPY headless/src/ headless/src/
COPY shared/lua-runtime/ shared/lua-runtime/
COPY third_party/maplestory-client/ third_party/maplestory-client/
COPY third_party/json/single_include/nlohmann/json.hpp third_party/json/single_include/nlohmann/json.hpp
COPY third_party/lua/ third_party/lua/
COPY LICENSE NOTICE /licenses/
COPY third_party/maplestory-client/LICENSE /licenses/maplestory-client.LICENSE
COPY third_party/json/LICENSE.MIT /licenses/json.LICENSE
COPY third_party/maplestory-client/includes/glfw-3.3.2.bin.WIN64/LICENSE.md /licenses/glfw.LICENSE
COPY third_party/maplestory-client/includes/NoLifeNx/nlnx/includes/lz4_v1_8_2_win32/include/lz4.h /licenses/lz4-header.LICENSE

ARG BUILD_JOBS=2
RUN make -C headless -j"${BUILD_JOBS}" \
        CXXFLAGS='-std=c++20 -O2 -DNDEBUG -ffunction-sections -fdata-sections' \
    && strip headless/build/beidou-headless

FROM debian:bookworm-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 liblz4-1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data /bridge
COPY --from=build /source/headless/build/beidou-headless /bin/beidou-headless
COPY --from=build /licenses/ /usr/share/licenses/beidou-pilot/
LABEL org.opencontainers.image.title="beidou-pilot" \
      org.opencontainers.image.description="Persistent native headless game client instance" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENV LANG=C.UTF-8
USER 65532:65532
WORKDIR /data
STOPSIGNAL SIGTERM
ENTRYPOINT ["/bin/beidou-headless"]
CMD ["--config", "/run/headless-config.json"]
