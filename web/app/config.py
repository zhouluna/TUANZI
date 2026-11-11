"""Environment-only settings. Secrets are never given defaults that look real."""

from __future__ import annotations

import os
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_ROOT.parent
ASSETS = REPO_ROOT / "assets"
DATA_DIR = WEB_ROOT / ".data"

NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODELS_CATALOG = "https://endpoint-desk-luna.vercel.app/api/models"


def database_url() -> str:
    configured = os.environ.get("DATABASE_URL", "").strip()
    if configured:
        if configured.startswith("postgres://"):
            return "postgresql+psycopg://" + configured[len("postgres://"):]
        if configured.startswith("postgresql://") and "+psycopg" not in configured.split("://", 1)[0]:
            return "postgresql+psycopg://" + configured[len("postgresql://"):]
        return configured
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + (DATA_DIR / "tuanzi.db").as_posix()


def access_password() -> str:
    return os.environ.get("TUANZI_ACCESS_PASSWORD", "")


def nvidia_api_key() -> str:
    return os.environ.get("NVIDIA_API_KEY", "").strip()


def nvidia_base_url() -> str:
    return os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")


def models_catalog_url() -> str:
    return os.environ.get("TUANZI_MODELS_URL", DEFAULT_MODELS_CATALOG).strip()


def dev_open() -> bool:
    return os.environ.get("TUANZI_DEV_OPEN", "") == "1"


def probe_limit() -> int:
    try:
        return max(1, min(6, int(os.environ.get("TUANZI_PROBE_LIMIT", "4"))))
    except ValueError:
        return 4
