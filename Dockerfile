FROM python:3.12-slim

ARG OCI_REVISION=""
ARG OCI_VERSION=""

LABEL org.opencontainers.image.source="https://github.com/onestao/wechat-hub-agent"
LABEL org.opencontainers.image.revision="${OCI_REVISION}"
LABEL org.opencontainers.image.version="${OCI_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

ENV WECHAT_CORE_URL=http://wechat-core:8080 \
    WECHAT_AGENT_DB=/data/wechat-agent.sqlite \
    WECHAT_AGENT_CONSUMER_ID=wechat-agent \
    WECHAT_AGENT_LEGACY_RUNTIME_DIR=/data/legacy-agent-console

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pycryptodome==3.23.0 zstandard==0.25.0 Pillow==11.3.0

COPY memory ./memory
COPY web ./web
COPY ai ./ai
COPY status ./status
COPY agent_console ./agent_console
COPY agent_service ./agent_service

RUN mkdir -p /data

VOLUME ["/data"]
EXPOSE 8091

CMD ["python", "-m", "agent_service.app", "--host", "0.0.0.0", "--port", "8091"]
