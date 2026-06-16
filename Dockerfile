FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pycryptodome==3.23.0 zstandard==0.25.0 Pillow==11.3.0

COPY memory ./memory
COPY web ./web
COPY ai ./ai
COPY status ./status
COPY agent_console ./agent_console
