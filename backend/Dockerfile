FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY etoro_bot ./etoro_bot
COPY alembic.ini ./

RUN pip install --no-cache-dir -e ".[api,rag]"

EXPOSE 8000

# Migrazioni all'avvio, poi API. Il kill switch resta azionabile anche a DB giù.
CMD ["sh", "-c", "alembic upgrade head && uvicorn etoro_bot.api.server:app --host 0.0.0.0 --port 8000"]
