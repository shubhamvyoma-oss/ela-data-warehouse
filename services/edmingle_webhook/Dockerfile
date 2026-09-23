FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN addgroup --system webhook && adduser --system --ingroup webhook webhook

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/buffer /app/data/failed /app/data/archive /app/logs \
    && chown -R webhook:webhook /app

USER webhook

EXPOSE 5100

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python scripts/healthcheck.py

CMD ["gunicorn", "-b", "0.0.0.0:5100", "--workers", "2", "--threads", "4", "--timeout", "30", "--graceful-timeout", "30", "wsgi:app"]
