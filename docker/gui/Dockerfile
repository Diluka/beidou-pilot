ARG WINE_BASE=scottyhardy/docker-wine:stable-11.0-20261025
FROM ${WINE_BASE}
USER root

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl iptables iproute2 xdotool x11-utils x11-apps xvfb xfwm4 \
    imagemagick fonts-wqy-microhei locales python3 util-linux \
    libgl1 libgl1:i386 libegl1 libegl1:i386 libgl1-mesa-dri libgl1-mesa-dri:i386 mesa-utils \
    libxtst6 libxtst6:i386 libxv1 libxv1:i386 libglu1-mesa libglu1-mesa:i386 \
    && curl --fail --location --retry 3 \
        https://github.com/VirtualGL/virtualgl/releases/download/3.1.5/virtualgl_3.1.5_amd64.deb \
        --output /tmp/virtualgl.deb \
    && curl --fail --location --retry 3 \
        https://github.com/VirtualGL/virtualgl/releases/download/3.1.5/virtualgl32_3.1.5_amd64.deb \
        --output /tmp/virtualgl32.deb \
    && dpkg -i /tmp/virtualgl.deb /tmp/virtualgl32.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/virtualgl.deb /tmp/virtualgl32.deb \
    && localedef -i zh_CN -f UTF-8 zh_CN.UTF-8 \
    && useradd --uid 1000 --create-home --shell /bin/bash v17client \
    && install -d -o 1000 -g 1000 /work \
    && install -d -m 1777 /tmp/.X11-unix

COPY --chmod=755 docker/gui/entrypoint.sh docker/gui/bootstrap.sh docker/gui/prepare-client.sh /opt/beidou/
COPY docker/gui/chinese-fontlink.reg /opt/beidou/
COPY LICENSE NOTICE /usr/share/licenses/beidou-pilot/
COPY third_party/detours/LICENSE.md /usr/share/licenses/beidou-pilot/detours.LICENSE.md
COPY third_party/lua/lua.h /usr/share/licenses/beidou-pilot/lua.LICENSE.h
COPY cli/beidou-pilot cli/runtime-ui.py /opt/beidou-pilot/cli/
COPY cli/beidou_pilot/ /opt/beidou-pilot/cli/beidou_pilot/
COPY shared/scripts/ /opt/beidou-pilot/shared/scripts/
COPY docker/runtime/entrypoint.py /opt/beidou-pilot/entrypoint.py
COPY build-input/ijl15.dll build-input/manifest.json /opt/beidou-pilot/native/
ARG SOURCE_REVISION=unversioned
RUN printf '%s\n' "$SOURCE_REVISION" > /opt/beidou-pilot/REVISION \
    && ln -s /opt/beidou-pilot/cli/beidou-pilot /usr/local/bin/beidou-pilot \
    && chmod -R a+rX /opt/beidou-pilot /usr/share/licenses/beidou-pilot

LABEL org.opencontainers.image.title="beidou-pilot-gui" \
      org.opencontainers.image.description="Persistent GUI game client and its control CLI" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.revision=$SOURCE_REVISION \
      beidou.backend=beidou
ENV LANG=zh_CN.UTF-8 DISPLAY=:97 WINEPREFIX=/work/runtime/prefix WINEARCH=win32 \
    CLIENT_ROOT=/work MAPLE_BACKEND=beidou MAPLE_RESOURCES_CONFIG=/work/config/resources.json \
    PYTHONPATH=/opt/beidou-pilot/cli PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
STOPSIGNAL SIGTERM
ENTRYPOINT ["python3", "/opt/beidou-pilot/entrypoint.py"]
