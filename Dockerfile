FROM python:3.12-slim

WORKDIR /app

# Install runtime deps. Pinned conservatively; bump when needed.
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32" \
    "icmplib>=3.0" \
    "jinja2>=3.1"

COPY app /app/app

ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
