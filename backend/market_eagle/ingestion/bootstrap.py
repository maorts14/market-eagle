"""Bootstrap the private deployment databases, then grant application access."""

from __future__ import annotations

import argparse
from pathlib import Path

import psycopg
from psycopg import sql

APP_DATABASE = "market_eagle"
TEMPORAL_DATABASES = ("temporal", "temporal_visibility")
ROLE_SECRETS = {
    "app_migrator": "app_migrator_pgpass",
    "app_ingest": "app_ingest_pgpass",
    "market_eagle_reader": "market_reader_pgpass",
    "market_eagle_agent": "agent_store_pgpass",
}
MARKET_READ_TABLES = (
    "catalog_current",
    "universe_snapshot",
    "data_source",
    "universe_member",
    "security",
    "sector",
    "listing_period",
    "trading_session",
    "selected_daily_bar",
)
AGENT_TABLES = (
    "agent_conversation",
    "agent_turn",
    "agent_evidence",
    "agent_turn_trace",
)
AGENT_SEQUENCES = ("agent_turn_sequence_id_seq", "agent_turn_trace_id_seq")
INGEST_TABLES = (
    "security",
    "security_symbol",
    "sector",
    "universe_snapshot",
    "universe_member",
    "catalog_current",
    "listing_period",
    "trading_session",
    "data_source",
    "ingest_batch",
    "daily_bar_revision",
    "daily_bar_current",
    "catalog_stage",
    "catalog_stage_member",
    "alpaca_collection_preparation",
    "alpaca_preparation_asset",
    "alpaca_preparation_session",
    "alpaca_alias_approval",
    "ongoing_collection_approval",
)


def _password(name: str) -> str:
    value = (Path("/run/secrets") / name).read_text(encoding="utf-8").rstrip("\r\n")
    if not value or "\n" in value or "\r" in value:
        raise ValueError(f"{name} must contain one nonempty line")
    return value


def _pgpass_password(name: str, role: str) -> str:
    line = _password(name)
    fields: list[str] = []
    part = ""
    escaped = False
    for character in line:
        if escaped:
            part += character
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append(part)
            part = ""
        else:
            part += character
    fields.append(part)
    if (
        escaped
        or fields[:4] != ["postgres", "5432", APP_DATABASE, role]
        or len(fields) != 5
        or not fields[4]
    ):
        raise ValueError(f"{name} must be one pgpass entry for {role}")
    return fields[4]


def _admin_connection(database: str = "postgres") -> psycopg.Connection:
    return psycopg.connect(
        host="postgres",
        port=5432,
        dbname=database,
        user="postgres",
        password=_password("postgres_admin_password"),
        autocommit=True,
        connect_timeout=5,
    )


def _ensure_role(conn: psycopg.Connection, role: str, password: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    if exists:
        inherited = conn.execute(
            "SELECT 1 FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = %s)",
            (role,),
        ).fetchone()
        if inherited:
            raise RuntimeError(f"Role {role} has unexpected role memberships")
        conn.execute(
            sql.SQL(
                "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )
    else:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(password))
        )


def _ensure_database(conn: psycopg.Connection, name: str, owner: str) -> None:
    existing = conn.execute(
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (name,)
    ).fetchone()
    if existing is None:
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(name), sql.Identifier(owner)
            )
        )
    elif existing[0] != owner:
        raise RuntimeError(f"Database {name} has an unexpected owner")
    conn.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
    )


def initialize() -> None:
    passwords = {
        role: _pgpass_password(secret, role) for role, secret in ROLE_SECRETS.items()
    }
    passwords["temporal_service"] = _password("temporal_db_password")
    with _admin_connection() as conn:
        for role, password in passwords.items():
            _ensure_role(conn, role, password)
        _ensure_database(conn, APP_DATABASE, "app_migrator")
        for name in TEMPORAL_DATABASES:
            _ensure_database(conn, name, "temporal_service")
        for role in ("app_ingest", "market_eagle_reader", "market_eagle_agent"):
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(APP_DATABASE), sql.Identifier(role)
                )
            )
    print("Database roles and databases are ready")


def _identifiers(names: tuple[str, ...]) -> sql.SQL:
    return sql.SQL(", ").join(sql.Identifier(name) for name in names)


def grant_access() -> None:
    with _admin_connection(APP_DATABASE) as conn, conn.transaction():
        required = MARKET_READ_TABLES + AGENT_TABLES + INGEST_TABLES
        missing = [
            name
            for name in required
            if conn.execute("SELECT to_regclass(%s)", (f"public.{name}",)).fetchone()[0]
            is None
        ]
        if missing:
            raise RuntimeError(
                "Run all application migrations before granting service access"
            )
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        for role in ("app_ingest", "market_eagle_reader", "market_eagle_agent"):
            conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(role)
                )
            )
            conn.execute(
                sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
                    sql.Identifier(role)
                )
            )
            conn.execute(
                sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(
                    sql.Identifier(role)
                )
            )
        conn.execute(
            sql.SQL("GRANT SELECT ON {} TO market_eagle_reader").format(
                _identifiers(MARKET_READ_TABLES)
            )
        )
        conn.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO market_eagle_agent"
            ).format(_identifiers(AGENT_TABLES))
        )
        conn.execute(
            sql.SQL("GRANT USAGE ON SEQUENCE {} TO market_eagle_agent").format(
                _identifiers(AGENT_SEQUENCES)
            )
        )
        conn.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO app_ingest").format(
                _identifiers(INGEST_TABLES)
            )
        )
        conn.execute("GRANT SELECT ON selected_daily_bar TO app_ingest")
    print("Service-specific application grants are ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "grants"))
    args = parser.parse_args()
    if args.action == "init":
        initialize()
    else:
        grant_access()


if __name__ == "__main__":
    main()
