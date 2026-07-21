"""Fixture condivise. I test DB girano su Postgres effimero via Docker;
se Docker non è disponibile vengono saltati (i test di risk/safety restano puri).
"""

import os
import shutil
import subprocess
import time
import uuid

import pytest

PG_IMAGE = "postgres:18-alpine"
PG_PORT = 55433


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.fixture(scope="session")
def pg_url():
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield external
        return
    if not _docker_available():
        pytest.skip("docker non disponibile per il Postgres di test")
    name = f"etoro-bot-pytest-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", "POSTGRES_USER=bot", "-e", "POSTGRES_PASSWORD=bot",
            "-e", "POSTGRES_DB=etoro_bot",
            "-p", f"{PG_PORT}:5432", PG_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    url = f"postgresql+psycopg://bot:bot@localhost:{PG_PORT}/etoro_bot"
    try:
        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "bot"], capture_output=True
            )
            if ready.returncode == 0:
                time.sleep(0.5)  # pg_isready anticipa di poco l'accettazione reale
                break
            time.sleep(0.5)
        else:
            pytest.fail("Postgres di test non pronto")
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture()
def repo(pg_url):
    from sqlalchemy import text as sqltext

    from etoro_bot.db.models import Base
    from etoro_bot.db.repo import Repository, make_engine, make_session_factory

    engine = make_engine(pg_url)
    Base.metadata.create_all(engine)
    try:
        yield Repository(make_session_factory(engine))
    finally:
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(sqltext(f'TRUNCATE TABLE "{table.name}" CASCADE'))
        engine.dispose()
