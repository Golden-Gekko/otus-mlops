FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt update && \
    apt install -y python3.8 python3.8-venv python3.8-dev build-essential curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

ENV VIRTUAL_ENV=/app/venv
ENV PATH="/app/venv/bin:$PATH"

RUN python3.8 -m venv "$VIRTUAL_ENV" && \
    pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt && \
    pip install venv-pack && \
    venv-pack -p "$VIRTUAL_ENV" -o /app/venv.tar.gz
