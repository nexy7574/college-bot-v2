# FROM python:3.11-bookworm
FROM ubuntu:latest

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
    python3-dev

RUN pip install --upgrade --break-system-packages pip wheel setuptools

COPY requirements.txt /tmp/requirements.txt
RUN pip install -Ur /tmp/requirements.txt --break-system-packages --no-input

WORKDIR /app
COPY ./src/ /app/
COPY ./src/cogs/ /app/cogs/

CMD ["python", "main.py"]
