from pathlib import Path

import pytest

from case_lab.domain import Policy
from case_lab.loaders import load_catalog, load_policy, load_registry, project_root


@pytest.fixture(autouse=True)
def _default_replay_mode(monkeypatch):
    """Тесты и локальный прогон эталона не должны зависеть от чужого .env с CASE_LLM=live."""

    monkeypatch.setenv("CASE_LLM", "replay")


@pytest.fixture
def root() -> Path:
    return project_root()


@pytest.fixture
def policy(root: Path) -> Policy:
    return load_policy(root / "data" / "policy.json")


@pytest.fixture
def catalog(root: Path):
    return load_catalog(root / "data" / "catalog.json")


@pytest.fixture
def registry(root: Path):
    return load_registry(root / "data" / "clients.json")

