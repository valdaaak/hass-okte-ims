ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1
RUN apk add --no-cache python3 py3-pip \
    && pip3 install --no-cache-dir --break-system-packages requests websockets tzdata

COPY okte_auto.py parse_ims.py import_to_ha.py run.py /app/
WORKDIR /app

CMD ["python3", "run.py"]
