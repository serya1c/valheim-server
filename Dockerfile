FROM python:3.12-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 HOME=/home/valheim
ARG APT_MAX_FUTURE_TIME=10
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Max-FutureTime=${APT_MAX_FUTURE_TIME} update && apt-get install -y --no-install-recommends \
    ca-certificates curl lib32gcc-s1 lib32stdc++6 libstdc++6 libatomic1 libpulse0 tar \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 valheim && mkdir -p /data /opt/steamcmd /app \
    && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar -xz -C /opt/steamcmd \
    && chown -R valheim:valheim /data /opt/steamcmd /app /home/valheim
WORKDIR /app
RUN python3 -m venv /app/venv && /app/venv/bin/pip install --no-cache-dir python-a2s==1.4.1
COPY --chown=valheim:valheim app/ /app/
USER valheim
EXPOSE 2456/udp 2457/udp 8080/tcp
CMD ["/app/venv/bin/python", "/app/server.py"]
