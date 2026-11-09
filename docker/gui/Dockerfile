ARG WINE_BASE=scottyhardy/docker-wine@sha256:a8aaee5b8559a391f06b923367078284ee86adcf913f0e3c497356567526a237
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
    && echo 'df3f7788ce41b182a47c0d298e5cd6d2d63579522cb41825970b7726e825485e  /tmp/virtualgl.deb' | sha256sum --check --strict \
    && echo '7dc63ecb47d7ab9cb486bb21a9a968dee853380da760cc7f36f616d09ec62b9e  /tmp/virtualgl32.deb' | sha256sum --check --strict \
    && dpkg -i /tmp/virtualgl.deb /tmp/virtualgl32.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/virtualgl.deb /tmp/virtualgl32.deb \
    && localedef -i zh_CN -f UTF-8 zh_CN.UTF-8 \
    && useradd --uid 1000 --create-home --shell /bin/bash v17client \
    && install -d -o 1000 -g 1000 /work \
    && install -d -m 1777 /tmp/.X11-unix

COPY --chmod=755 entrypoint.sh bootstrap.sh prepare-client.sh /opt/beidou/
COPY chinese-fontlink.reg /opt/beidou/

ENV LANG=zh_CN.UTF-8 DISPLAY=:97 WINEPREFIX=/work/prefix WINEARCH=win32
WORKDIR /work
ENTRYPOINT ["/opt/beidou/entrypoint.sh"]
