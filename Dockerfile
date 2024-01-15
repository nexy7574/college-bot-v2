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
    ffmpeg \
    imagemagick \
    whois \
    wget \
    curl \
    htop \
    python3 \
    python3-pip \
    python3-dev \
    python3-virtualenv \
    # libglib2.0-0=2.50.3-2 \
    # libnss3=2:3.26.2-1.1+deb9u1 \
    # libgconf-2-4=3.2.6-4+b1 \
    # libfontconfig1=2.11.0-6.7+b1
    libglib2.0-0 \
    libnss3 \
    libgconf-2-4 \
    libfontconfig1

RUN virtualenv /app/venv
RUN /app/venv/bin/pip install --upgrade --no-input pip wheel setuptools

COPY requirements.txt /tmp/requirements.txt
RUN /app/venv/bin/pip install -Ur /tmp/requirements.txt --no-input

COPY ./src/ /app/
COPY ./src/cogs/ /app/cogs/

CMD ["/app/venv/bin/python", "main.py"]
