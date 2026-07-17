FROM debian:12-slim

ARG QBT_URL=https://github.com/userdocs/qbittorrent-nox-static/releases/download/release-5.1.4_v2.0.11/x86_64-qbittorrent-nox

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl wget tini \
    && wget -q "$QBT_URL" -O /usr/local/bin/qbittorrent-nox \
    && chmod +x /usr/local/bin/qbittorrent-nox \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080 6881/tcp 6881/udp
VOLUME ["/config"]
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
