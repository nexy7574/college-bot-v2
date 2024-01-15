FROM python:3.11-bookworm

WORKDIR /app

RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

# Install chrome dependencies
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
gconf-service \
libasound2 \
libatk1.0-0 \
libc6 \
libcairo2 \
libcups2 \
libdbus-1-3 \
libexpat1 \
libfontconfig1 \
libgcc1 \
libgconf-2-4 \
libgdk-pixbuf2.0-0 \
libglib2.0-0 \
libgtk-3-0 \
libnspr4 \
libpango-1.0-0 \
libpangocairo-1.0-0 \
libstdc++6 \
libx11-6 \
libx11-xcb1 \
libxcb1 \
libxcomposite1 \
libxcursor1 \
libxdamage1 \
libxext6 \
libxfixes3 \
libxi6 \
libxrandr2 \
libxrender1 \
libxss1 \
libxtst6 \
ca-certificates \
fonts-liberation \
libappindicator1 \
libnss3 \
lsb-release \
xdg-utils 

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
    python3-virtualenv

RUN virtualenv /app/venv
RUN /app/venv/bin/pip install --upgrade --no-input pip wheel setuptools

COPY requirements.txt /tmp/requirements.txt
RUN /app/venv/bin/pip install -Ur /tmp/requirements.txt --no-input

COPY ./src/ /app/

CMD ["/app/venv/bin/python", "main.py"]
