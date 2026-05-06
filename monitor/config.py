from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def save_config(cfg: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    with open(path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)


def load_secrets() -> dict[str, str | None]:
    """Pull secrets from environment. None if absent."""
    return {
        "TICKETMASTER_API_KEY": os.getenv("TICKETMASTER_API_KEY"),
        "SEATGEEK_CLIENT_ID": os.getenv("SEATGEEK_CLIENT_ID"),
        "SEATGEEK_CLIENT_SECRET": os.getenv("SEATGEEK_CLIENT_SECRET"),
        "NTFY_TOPIC": os.getenv("NTFY_TOPIC"),
        "SMTP_HOST": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "SMTP_PORT": os.getenv("SMTP_PORT", "587"),
        "SMTP_USER": os.getenv("SMTP_USER"),
        "SMTP_PASS": os.getenv("SMTP_PASS"),
        "SMTP_TO": os.getenv("SMTP_TO"),
    }
