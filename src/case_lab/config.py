"""Настройки из окружения и опционального файла .env. Секреты в репозиторий не кладём."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from case_lab.loaders import project_root

DEFAULT_PROXY_BASE_URL = "https://api.proxyapi.ru/v1"
DEFAULT_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class Settings:
    case_llm: str
    api_key: str
    base_url: str
    model: str
    input_mode: str
    notify_mode: str
    mail_host: str
    mail_user: str
    mail_password: str
    mail_folder: str
    manager_email: str
    smtp_host: str
    smtp_user: str
    smtp_password: str
    smtp_port: int


def load_dotenv(path: Path | None = None) -> None:
    """Подхватывает .env, не перезаписывая уже заданные переменные окружения."""

    env_path = path or (project_root() / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_settings(*, reload_env: bool = True) -> Settings:
    if reload_env:
        load_dotenv()
    return Settings(
        case_llm=os.environ.get("CASE_LLM", "replay").strip().lower() or "replay",
        api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        base_url=(os.environ.get("OPENAI_BASE_URL") or DEFAULT_PROXY_BASE_URL).rstrip("/"),
        model=(os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL).strip(),
        input_mode=os.environ.get("CASE_INPUT", "files").strip().lower() or "files",
        notify_mode=os.environ.get("CASE_NOTIFY", "file").strip().lower() or "file",
        mail_host=os.environ.get("MAIL_HOST", "").strip(),
        mail_user=os.environ.get("MAIL_USER", "").strip(),
        mail_password=os.environ.get("MAIL_PASSWORD", "").strip(),
        mail_folder=os.environ.get("MAIL_FOLDER", "INBOX").strip() or "INBOX",
        manager_email=os.environ.get("MANAGER_EMAIL", "").strip(),
        smtp_host=os.environ.get("SMTP_HOST", "").strip(),
        smtp_user=os.environ.get("SMTP_USER", "").strip(),
        smtp_password=os.environ.get("SMTP_PASSWORD", "").strip(),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
    )
