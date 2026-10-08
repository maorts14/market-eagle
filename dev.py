"""Portable developer commands for the local Market Eagle services and checks."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INFRA = ROOT / "infra"
ENV = INFRA / ".env"
COMPOSE = ["docker", "compose", "--env-file", str(ENV), "-f", str(INFRA / "compose.yaml")]
BACKEND = ROOT / "backend"


def run(*command: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def local_env() -> dict[str, str]:
    if not ENV.exists():
        shutil.copyfile(INFRA / ".env.example", ENV)
        print(f"Created {ENV} from the local development example", flush=True)
    values = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, separator, value = line.partition("=")
            if not separator:
                raise ValueError(f"Invalid line in {ENV}: {line}")
            values[key] = value
    return values


def compose(*args: str) -> None:
    local_env()
    run(*COMPOSE, *args)


def database_url() -> str:
    values = local_env()
    from urllib.parse import quote

    return (
        f"postgresql+psycopg://{quote(values['APP_DB_USER'])}:"
        f"{quote(values['APP_DB_PASSWORD'])}@127.0.0.1:"
        f"{values.get('APP_DB_PORT', '55432')}/{quote(values['APP_DB_NAME'])}"
    )


def check() -> None:
    values = local_env()
    compose("exec", "-T", "app-db", "psql", "-U", values["APP_DB_USER"], "-d", values["APP_DB_NAME"], "-Atc", "select 1")
    compose("exec", "-T", "temporal-db", "psql", "-U", values["TEMPORAL_DB_USER"], "-d", "postgres", "-Atc", "select 1 / (count(*) / 2) from pg_database where datname in ('temporal', 'temporal_visibility')")
    compose("exec", "-T", "temporal", "temporal", "operator", "namespace", "describe", "--namespace", "default")
    with urllib.request.urlopen(f"http://127.0.0.1:{values.get('TEMPORAL_UI_PORT', '8080')}", timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Temporal UI returned {response.status}")
    print("Local services are ready", flush=True)


def fixture_check() -> None:
    source = ROOT / "fixtures" / "synthetic-v1"
    with tempfile.TemporaryDirectory() as temp:
        replica = Path(temp) / "synthetic-v1"
        shutil.copytree(source, replica)
        run(sys.executable, str(replica / "generate.py"))
        run(sys.executable, str(replica / "expectations.py"))
        for filename in ("sessions.csv", "catalog.csv", "bars.csv", "manifest.json", "expected-results.json"):
            if (source / filename).read_text(encoding="utf-8") != (replica / filename).read_text(encoding="utf-8"):
                raise RuntimeError(f"Committed fixture differs from deterministic regeneration: {filename}")
    print("Synthetic fixture matches its generators", flush=True)


def backend_checks(*, integration: bool) -> None:
    if not (BACKEND / "pyproject.toml").exists():
        print("Backend not present yet; backend checks await its implementation", flush=True)
        return
    run(sys.executable, "-m", "ruff", "format", "--check", "backend")
    run(sys.executable, "-m", "ruff", "check", "backend")
    if integration:
        if not (BACKEND / "alembic.ini").exists():
            raise RuntimeError("Backend needs backend/alembic.ini for the migration gate")
        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url()
        run(sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head", env=environment)
        run(sys.executable, "-m", "pytest", "backend", "-m", "synthetic_integration", env=environment)
    else:
        run(sys.executable, "-m", "pytest", "backend", "-m", "not synthetic_integration")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("up", "down", "check", "tools", "verify", "integration"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    if options.command == "up":
        compose("up", "-d", "--wait")
        check()
    elif options.command == "down":
        compose("down")
    elif options.command == "check":
        check()
    elif options.command == "tools":
        compose("exec", "-T", "temporal", "temporal", *options.args)
    elif options.command == "verify":
        fixture_check()
        backend_checks(integration=False)
    else:
        fixture_check()
        compose("up", "-d", "--wait")
        check()
        backend_checks(integration=True)


if __name__ == "__main__":
    main()
