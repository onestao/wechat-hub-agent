FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir pycryptodome==3.23.0 zstandard==0.25.0

COPY memory ./memory
COPY web ./web
COPY ai ./ai
COPY status ./status
COPY agent_console ./agent_console
