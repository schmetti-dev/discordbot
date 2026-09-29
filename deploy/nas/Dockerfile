# Container für den Betrieb auf einem NAS oder jedem anderen Docker-Host.
# Das Home-Assistant-Add-on nutzt weiter das Dockerfile im Repo-Root.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/buchclub.db \
    BACKUP_DIR=/backup \
    TZ=Europe/Berlin

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py database.py migrations.py ./
COPY cogs ./cogs
COPY services ./services
COPY assets ./assets

# Der Bot läuft nicht als root. Die Volumes müssen dieser Kennung gehören.
RUN useradd --uid 1000 --create-home buchclub && mkdir -p /data /backup && chown buchclub /data /backup
USER buchclub

CMD ["python", "bot.py"]
