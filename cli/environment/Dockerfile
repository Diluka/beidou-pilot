ARG WINE_BASE=scottyhardy/docker-wine@sha256:a8aaee5b8559a391f06b923367078284ee86adcf913f0e3c497356567526a237
FROM ${WINE_BASE}
USER root
ARG http_proxy
ARG https_proxy
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    iptables iproute2 xdotool x11-utils x11-apps imagemagick fonts-wqy-microhei procps \
    libgl1 libgl1:i386 libegl1 libegl1:i386 libgl1-mesa-dri libgl1-mesa-dri:i386 mesa-utils \
    libxtst6:i386 libxv1:i386 && rm -rf /var/lib/apt/lists/*
RUN localedef -i zh_CN -f UTF-8 zh_CN.UTF-8
RUN if ! getent passwd 1000 >/dev/null; then useradd --uid 1000 --create-home --shell /bin/bash v17client; fi
COPY virtualgl_3.1.5_amd64.deb virtualgl32_3.1.5_amd64.deb /opt/installers/
RUN dpkg -i /opt/installers/virtualgl_3.1.5_amd64.deb /opt/installers/virtualgl32_3.1.5_amd64.deb && rm -r /opt/installers
ENTRYPOINT ["/bin/bash"]
