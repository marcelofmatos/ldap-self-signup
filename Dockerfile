FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
CMD ["pytest", "-q"]

FROM base AS prod
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} DATA_DIR=/data TEMPLATE_DIR=/template
RUN useradd --system --uid 10001 app && mkdir -p /data /template && chown app /data
COPY app ./app
COPY docker-entrypoint.sh /docker-entrypoint.sh
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
ENTRYPOINT ["/docker-entrypoint.sh"]
