FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 career && chown career:career /app
COPY pyproject.toml .
COPY backend backend
RUN pip install --no-cache-dir .
COPY --chown=career:career migrations migrations
COPY --chown=career:career alembic.ini .
COPY --chown=career:career deploy deploy
COPY --chown=career:career scripts/deployment_preflight.py scripts/secure_supabase.py scripts/database_backup.py scripts/
COPY --chown=career:career evals/historical_cases.jsonl evals/historical_cases.jsonl
ENV PYTHONPATH=/app/backend PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8000
USER career
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()"
CMD ["python", "-m", "career.startup"]
