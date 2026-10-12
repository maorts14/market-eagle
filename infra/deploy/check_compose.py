"""Validate the private Compose deployment without starting services or reading secrets."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infra" / "deploy" / "compose.yaml"
EXAMPLE_ENV = ROOT / "infra" / "deploy" / ".env.example"


def render(*profiles: str) -> dict:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(EXAMPLE_ENV),
        "-f",
        str(COMPOSE),
    ]
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(("config", "--format", "json"))
    return json.loads(subprocess.check_output(command, text=True))


def check() -> None:
    default = render()["services"]
    all_services = render("*")["services"]

    assert "ingestion" not in default, "collection must be opt-in"
    assert all_services["ingestion"]["profiles"] == ["collection"]
    assert "bootstrap-db" not in default, "maintenance must be opt-in"
    assert "temporal-ui" not in default, "operator UI must be opt-in"

    for name, service in all_services.items():
        ports = service.get("ports", [])
        if name in ("web", "temporal-ui"):
            assert len(ports) == 1, f"{name} needs one loopback port"
            assert ports[0]["host_ip"] == "127.0.0.1", f"{name} must bind loopback"
        else:
            assert not ports, f"{name} must not publish a host port"

    web_args = all_services["web"]["build"]["args"]
    assert web_args["VITE_AGENT_MODE"] == "api"
    assert web_args["VITE_EXPLORER_MODE"] == "api"
    assert "VITE_PILOT_START" in web_args
    assert "VITE_PILOT_END" in web_args
    assert all_services["api"]["environment"]["DATABASE_URL"].startswith(
        "postgresql://market_eagle_reader@postgres:"
    )
    assert all_services["agent"]["environment"]["AGENT_DATABASE_URL"].startswith(
        "postgresql://market_eagle_agent@postgres:"
    )
    for name in (
        "api",
        "agent",
        "ingestion",
        "migrate-app",
        "bootstrap-db",
        "bootstrap-grants",
    ):
        environment = all_services[name]["environment"]
        assert environment["MARKET_EAGLE_RUNTIME"] == "production"
        assert "MARKET_EAGLE_PRIVATE_SAMPLE_SNAPSHOT_ID" not in environment
    for name, expected in (
        ("api", {"market_reader_pgpass", "agent_store_pgpass"}),
        ("agent", {"market_reader_pgpass", "agent_store_pgpass", "openrouter_key"}),
        (
            "ingestion",
            {"app_ingest_pgpass", "alpaca_key_id", "alpaca_secret_key", "fmp_key"},
        ),
    ):
        mounted = {secret["source"] for secret in all_services[name]["secrets"]}
        assert mounted == expected, f"{name} has unexpected secret mounts"
    print("Private Compose profile, port, secret, and API-mode checks passed")


if __name__ == "__main__":
    check()
