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
    && apt-get install -y --no-install-recommends libstdc++6 liblz4-1 python3 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data /bridge
COPY --from=build /source/headless/build/beidou-headless /bin/beidou-headless
COPY --from=build /licenses/ /usr/share/licenses/beidou-pilot/
COPY cli/beidou-pilot cli/runtime-ui.py /opt/beidou-pilot/cli/
COPY cli/beidou_pilot/ /opt/beidou-pilot/cli/beidou_pilot/
COPY shared/scripts/ /opt/beidou-pilot/shared/scripts/
COPY docker/runtime/entrypoint.py /opt/beidou-pilot/entrypoint.py
COPY third_party/lua/lua.h /usr/share/licenses/beidou-pilot/lua.LICENSE.h
ARG SOURCE_REVISION=unversioned
RUN printf '%s\n' "$SOURCE_REVISION" > /opt/beidou-pilot/REVISION \
    && ln -s /opt/beidou-pilot/cli/beidou-pilot /usr/local/bin/beidou-pilot \
    && chmod -R a+rX /opt/beidou-pilot /usr/share/licenses/beidou-pilot
LABEL org.opencontainers.image.title="beidou-pilot" \
      org.opencontainers.image.description="Persistent native headless game client instance" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.revision=$SOURCE_REVISION \
      beidou.backend=headless
ENV LANG=C.UTF-8 CLIENT_ROOT=/work MAPLE_BACKEND=headless \
    MAPLE_RESOURCES_CONFIG=/work/config/resources.json \
    PYTHONPATH=/opt/beidou-pilot/cli PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
WORKDIR /work
STOPSIGNAL SIGTERM
ENTRYPOINT ["python3", "/opt/beidou-pilot/entrypoint.py"]
