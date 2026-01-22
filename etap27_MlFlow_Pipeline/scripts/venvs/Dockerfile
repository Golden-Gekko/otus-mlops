FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt update && \
    apt install -y python3.8 python3.8-venv python3.8-dev build-essential curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

RUN python3.8 -m venv venv && \
    venv/bin/pip install --upgrade pip setuptools wheel && \
    venv/bin/pip install -r requirements.txt && \
    venv/bin/pip install venv-pack

RUN venv/bin/venv-pack -o venv.tar.gz