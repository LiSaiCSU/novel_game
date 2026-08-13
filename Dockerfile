FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY engine ./engine
COPY database ./database
COPY apps ./apps
COPY prompts ./prompts
COPY content ./content
COPY alembic.ini ./
RUN pip install --no-cache-dir ".[postgres,redis,object-store]"
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
