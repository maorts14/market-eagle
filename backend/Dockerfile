FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY app ./app
COPY tests ./tests
RUN pip install --no-cache-dir .[dev]
CMD ["python", "-m", "app.worker"]
