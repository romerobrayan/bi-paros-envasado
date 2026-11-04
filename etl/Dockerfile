# One image, three services (etl, simulator, alert-sink) selected by `command`.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY etl ./etl

# non-root user: the container only needs to read /data/raw and talk to the DB
RUN useradd --create-home --uid 1000 etl
USER etl

CMD ["python", "-m", "etl.main"]
