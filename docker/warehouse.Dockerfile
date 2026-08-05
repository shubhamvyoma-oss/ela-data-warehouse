FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN addgroup --system warehouse && adduser --system --ingroup warehouse warehouse

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api_scripts ./api_scripts
COPY database ./database
COPY manual_imports ./manual_imports
COPY platform ./platform
COPY processing ./processing
COPY shared ./shared
COPY warehouse_cli.py ./warehouse_cli.py

RUN mkdir -p /app/data/imports /app/logs \
    && chown -R warehouse:warehouse /app

USER warehouse

CMD ["python", "platform/scheduler/runner.py"]
