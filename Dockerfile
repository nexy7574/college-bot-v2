FROM python:3.11-bookworm

RUN DEBIAN_FRONTEND=noninteractive apt-get update
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y traceroute iputils-ping dnsutils net-tools git chromium chromium-driver chromium-sandbox chromium-shell

RUN pip install --upgrade --break-system-packages pip wheel setuptools

COPY requirements.txt /tmp/requirements.txt
RUN pip install -Ur /tmp/requirements.txt --break-system-packages --no-input

WORKDIR /app
COPY main.py /app
COPY cookies.txt /app
COPY cogs/ /app/cogs/

CMD ["python", "main.py"]
