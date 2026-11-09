FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS build

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

RUN set -eu; \
    mkdir -p /runtime/bin /runtime/data /runtime/bridge /runtime/run /runtime/usr/share/licenses/beidou-pilot /licenses/system; \
    cp headless/build/beidou-headless /runtime/bin/beidou-headless; \
    ldd headless/build/beidou-headless > /licenses/runtime-libraries.txt; \
    for library in $(sed -n 's/.*=> \(\/[^ ]*\).*/\1/p;s/^[[:space:]]*\(\/[^ ]*\) (.*/\1/p' /licenses/runtime-libraries.txt); do \
        cp --parents --dereference "$library" /runtime; \
        owner="$(dpkg-query --search "*/$(basename "$library")")"; \
        printf '%s\n' "$owner" | sed 's/: \/.*//' >> /licenses/runtime-packages.txt; \
    done; \
    sort -u /licenses/runtime-packages.txt -o /licenses/runtime-packages.txt; \
    for package in $(cat /licenses/runtime-packages.txt); do \
        cp --dereference "/usr/share/doc/${package%%:*}/copyright" "/licenses/system/${package%%:*}.copyright"; \
    done; \
    for license in /usr/share/common-licenses/*; do \
        if grep --fixed-strings --quiet "$license" /licenses/system/*.copyright; then \
            cp --dereference "$license" /licenses/system/; \
        fi; \
    done; \
    multiarch="$(gcc -print-multiarch)"; \
    mkdir -p "/runtime/usr/lib/${multiarch}"; \
    cp -a "/usr/lib/${multiarch}/gconv" "/runtime/usr/lib/${multiarch}/gconv"; \
    cp -a /licenses/. /runtime/usr/share/licenses/beidou-pilot/


FROM scratch AS runtime
COPY --from=build /runtime/ /
LABEL org.opencontainers.image.title="beidou-pilot" \
      org.opencontainers.image.description="Persistent native headless game client instance" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENV LANG=C.UTF-8
USER 65532:65532
WORKDIR /data
STOPSIGNAL SIGTERM
ENTRYPOINT ["/bin/beidou-headless"]
CMD ["--config", "/run/headless-config.json"]
