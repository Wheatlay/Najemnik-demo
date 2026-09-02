FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
# Dependencies only: the project itself is a hatchling package over core/ and
# routers/, which are not in the image yet at this layer.
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
# Now that the sources are present, install the project itself.
RUN uv sync --frozen --no-dev

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

CMD ["sh", "-c", "uv run --no-sync uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
