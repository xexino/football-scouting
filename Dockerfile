FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 INIT_ON_STARTUP=false
WORKDIR /srv/raja-scout

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend

RUN useradd --system --uid 10001 raja && chown -R raja /srv/raja-scout
USER raja
WORKDIR /srv/raja-scout/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.getenv('PORT','8000'))" || exit 1
# One-off bootstrap (tables + optional demo data), then the server. PORT is set by most hosts.
CMD ["sh", "-c", "python -m app.cli bootstrap && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips='*'"]
