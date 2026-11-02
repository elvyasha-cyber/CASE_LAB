"""Чтение файлов кейса. Корень — каталог, где лежит data/catalog.json."""

from __future__ import annotations

import json
from pathlib import Path

from case_lab.domain import Catalog, Policy, Registry, build_catalog, build_registry
from case_lab.schemas import Golden, InboundEmail


class SourceProblem:
    def __init__(self, source_id: str, detail: str) -> None:
        self.id = source_id
        self.detail = detail


def project_root() -> Path:
    starts = [Path(__file__).resolve(), Path.cwd().resolve()]
    seen: set[Path] = set()
    for start in starts:
        for parent in [start, *start.parents]:
            if parent in seen:
                continue
            seen.add(parent)
            if (parent / "data" / "catalog.json").exists():
                return parent
    raise FileNotFoundError("Не найден корень кейса: data/catalog.json.")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_policy(path: Path) -> Policy:
    from case_lab.domain import CONFIDENCE_RANK

    raw = read_json(path)
    min_confidence = str(raw["min_confidence"])
    if min_confidence not in CONFIDENCE_RANK:
        raise ValueError("min_confidence должен быть low, medium или high.")
    temperature = float(raw.get("temperature", 0.2))
    if temperature < 0 or temperature > 1:
        raise ValueError("temperature должна быть от 0 до 1.")
    horizon = int(raw["max_horizon_days"])
    max_qty = int(raw["max_qty_default"])
    if horizon < 0 or max_qty < 1:
        raise ValueError("Горизонт даты или лимит количества заданы неверно.")
    return Policy(
        version=raw["version"],
        prompt_version=raw["prompt_version"],
        min_confidence=min_confidence,
        temperature=temperature,
        max_horizon_days=horizon,
        max_qty_default=max_qty,
    )


def load_catalog(path: Path) -> Catalog:
    return build_catalog(read_json(path))


def load_registry(path: Path) -> Registry:
    return build_registry(read_json(path))


def load_inbox(folder: Path) -> list[InboundEmail | SourceProblem]:
    from pydantic import ValidationError

    from case_lab.textutil import shorten

    items: list[InboundEmail | SourceProblem] = []
    for path in sorted(folder.glob("*.json")):
        try:
            items.append(InboundEmail.model_validate(read_json(path)))
        except (json.JSONDecodeError, ValidationError, OSError) as exc:
            items.append(SourceProblem(path.stem, shorten(str(exc))))
    return sorted(items, key=lambda item: item.id)


def load_goldens(folder: Path) -> list[Golden]:
    goldens = [Golden.model_validate(read_json(path)) for path in sorted(folder.glob("*.json"))]
    goldens.sort(key=lambda item: item.message_id)
    return goldens


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
