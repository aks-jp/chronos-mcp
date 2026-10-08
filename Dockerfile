FROM python:3.12.15-alpine3.24

# PYTHONTZPATH="" makes zoneinfo ignore the OS zone files and use only
# the pinned tzdata package from requirements.txt.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONTZPATH=""

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt \
    && adduser -S -D -H -u 10001 mcp

COPY server.py .
USER mcp

EXPOSE 8765
CMD ["python", "server.py"]
