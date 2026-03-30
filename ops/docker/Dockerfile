FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/logs

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD python /app/bot_healthcheck.py || exit 1

STOPSIGNAL SIGTERM

CMD ["python", "bot.py"]
