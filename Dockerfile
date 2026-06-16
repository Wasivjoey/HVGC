FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATABASE_PATH=/data/avteam.db \
    UPLOAD_PATH=/data/uploads

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persisted SQLite lives on a mounted volume so data survives redeploys.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# gunicorn serves the WSGI app created by create_app().
CMD ["gunicorn", "app:create_app()", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60"]
