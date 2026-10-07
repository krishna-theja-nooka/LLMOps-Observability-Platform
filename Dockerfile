FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && useradd --uid 10001 --create-home gateway \
    && mkdir /app/data && chown gateway:gateway /app/data
COPY pyproject.toml README.md ./
COPY app ./app
RUN python -m pip install --no-cache-dir --no-deps .
USER gateway
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
