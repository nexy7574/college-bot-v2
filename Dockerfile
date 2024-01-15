# FROM python:3.11-bookworm
FROM ubuntu:latest

WORKDIR /app

RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y \
    traceroute \
    iputils-ping \
    dnsutils \
    net-tools \
    git \
    # chromium \
    # chromium-driver \
    # chromium-sandbox \
    # chromium-shell \
    ffmpeg \
    imagemagick \
    whois \
    wget \
    curl \
    htop \
    python3 \
    python3-pip \
    python3-dev \
    python3-virtualenv

RUN virtualenv /app/venv
RUN /app/venv/bin/pip install --upgrade --no-input pip wheel setuptools

COPY requirements.txt /tmp/requirements.txt
RUN /app/venv/bin/pip install -Ur /tmp/requirements.txt --no-input

COPY ./src/ /app/
COPY ./src/cogs/ /app/cogs/

CMD ["/app/venv/bin/python", "main.py"]
