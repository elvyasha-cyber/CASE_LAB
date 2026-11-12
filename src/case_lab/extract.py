"""Извлечение JSON. По умолчанию — контрольные фикстуры. Боевой вызов включается явно и не нужен для кейса."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

from pydantic import ValidationError

from case_lab.config import get_settings
from case_lab.domain import Catalog, Policy, Registry
from case_lab.schemas import Cassette, Extraction, InboundEmail
from case_lab.textutil import sha256_text, shorten

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "order_extract_v4.txt"


@dataclass
class ExtractResult:
    model: str
    prompt_version: str
    prompt_sha256: str
    extraction: Extraction | None
    error_code: str | None = None
    error_detail: str | None = None


def load_prompt_template(policy: Policy, path: Path = PROMPT_PATH) -> str:
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0].strip()
    expected = f"PROMPT_VERSION: {policy.prompt_version}"
    if first != expected:
        raise ValueError(f"Версия промпта {first!r} не совпадает с политикой ({expected}).")
    return text


def render_prompt(template: str, email: InboundEmail, catalog: Catalog, registry: Registry) -> tuple[str, str, str]:
    system = template.replace("{{CATALOG}}", _catalog_brief(catalog)).replace("{{CLIENTS}}", _client_brief(registry))
    user = (
        f"received_at: {email.received_at.isoformat()}\n"
        f"from: {email.sender}\n"
        f"subject: {email.subject}\n\n"
        f"{email.body}"
    )
    digest = sha256_text(system + "\n---\n" + user)
    return system, user, digest


def parse_model_json(content: str) -> dict:
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("Ожидался JSON-объект", text, 0)
    return payload


class ReplayExtractor:
    """Ответ берётся из контрольной фикстуры. Промпт всё равно собирается и попадает в аудит отпечатком."""

    def __init__(self, cassette_dir: Path, policy: Policy) -> None:
        self.cassette_dir = cassette_dir
        self.policy = policy
        self.template = load_prompt_template(policy)

    def extract(self, email: InboundEmail, catalog: Catalog, registry: Registry) -> ExtractResult:
        _system, _user, digest = render_prompt(self.template, email, catalog, registry)
        path = self.cassette_dir / f"{email.id}.json"
        base = ExtractResult("missing", self.policy.prompt_version, digest, None)
        if not path.exists():
            base.error_code = "extractor_unavailable"
            base.error_detail = f"Нет контрольного ответа для {email.id}."
            return base
        try:
            cassette = Cassette.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            base.error_code = "schema_invalid"
            base.error_detail = shorten(str(exc))
            return base
        return ExtractResult(cassette.model, self.policy.prompt_version, digest, cassette.extraction)


class LiveExtractor:
    """Вызов LLM через Proxy API (OpenAI-совместимый chat completions). Temperature из политики (0.2)."""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.template = load_prompt_template(policy)
        settings = get_settings()
        self.api_key = settings.api_key
        self.base_url = settings.base_url
        self.model_name = settings.model
        if not self.api_key:
            raise RuntimeError(
                "CASE_LLM=live требует OPENAI_API_KEY в .env (ключ Proxy API). "
                "Чтобы не вызывать модель, оставьте CASE_LLM=replay."
            )

    def extract(self, email: InboundEmail, catalog: Catalog, registry: Registry) -> ExtractResult:
        system, user, digest = render_prompt(self.template, email, catalog, registry)
        body = {
            "model": self.model_name,
            "temperature": self.policy.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            extraction = Extraction.model_validate(parse_model_json(content))
        except (error.URLError, json.JSONDecodeError, ValidationError, KeyError, TimeoutError) as exc:
            return ExtractResult(
                self.model_name,
                self.policy.prompt_version,
                digest,
                None,
                error_code="schema_invalid",
                error_detail=shorten(str(exc)),
            )
        return ExtractResult(self.model_name, self.policy.prompt_version, digest, extraction)


def build_extractor(cassette_dir: Path, policy: Policy, mode: str | None = None) -> ReplayExtractor | LiveExtractor:
    settings = get_settings()
    selected = (mode or settings.case_llm).strip().lower()
    if selected == "live":
        return LiveExtractor(policy)
    if selected == "replay":
        return ReplayExtractor(cassette_dir, policy)
    raise RuntimeError("CASE_LLM должен быть replay или live.")


def _catalog_brief(catalog: Catalog) -> str:
    lines = []
    for item in catalog.items:
        synonyms = "; ".join(item.synonyms)
        lines.append(f"{item.sku} — {item.name} — единица: {item.unit} — синонимы: {synonyms}")
    return "\n".join(lines)


def _client_brief(registry: Registry) -> str:
    lines = []
    for client in registry.clients:
        addresses = "; ".join(address.full for address in client.addresses)
        lines.append(f"{client.id} — {client.legal_name} — ИНН {client.inn} — адреса: {addresses}")
    return "\n".join(lines)
