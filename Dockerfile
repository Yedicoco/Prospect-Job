# Image unifiée Yallah Services — bibliothèque standard Python uniquement (zéro dépendance pip)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    YALLAH_DB=/data/yallah.sqlite3 \
    YALLAH_ENABLE_LIVE=0 \
    YALLAH_AUTO_BACKUP=1

RUN groupadd -g 1000 yallah \
    && useradd -u 1000 -g yallah -m -s /usr/sbin/nologin yallah \
    && mkdir -p /app /data \
    && chown -R yallah:yallah /app /data \
    && chmod 700 /data

WORKDIR /app
COPY --chown=yallah:yallah . /app

USER yallah
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import os, urllib.request; p = os.getenv('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{p}/services', timeout=4).read()" || exit 1

CMD ["python3", "webapp.py"]
