"""Справочники пилота. Индексы строятся при загрузке, чтобы гейты не искали линейно и не расходились."""

from __future__ import annotations

from dataclasses import dataclass

from case_lab.textutil import email_domain, norm, normalize_inn


@dataclass(frozen=True)
class Address:
    id: str
    full: str
    hints: tuple[str, ...]


@dataclass(frozen=True)
class Client:
    id: str
    legal_name: str
    inn: str
    email_domains: tuple[str, ...]
    aliases: tuple[str, ...]
    credit_limit_rub: int
    addresses: tuple[Address, ...]


@dataclass(frozen=True)
class Item:
    sku: str
    name: str
    unit: str
    price_rub: int
    max_qty: int
    synonyms: tuple[str, ...]


@dataclass
class Catalog:
    currency: str
    items: tuple[Item, ...]
    by_sku: dict[str, Item]


@dataclass
class Registry:
    clients: tuple[Client, ...]
    by_id: dict[str, Client]
    by_inn: dict[str, Client]
    by_domain: dict[str, Client]
    by_alias: dict[str, Client]


CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Policy:
    version: str
    prompt_version: str
    min_confidence: str
    temperature: float
    max_horizon_days: int
    max_qty_default: int

    def confidence_ok(self, value: str) -> bool:
        return CONFIDENCE_RANK[value] >= CONFIDENCE_RANK[self.min_confidence]


def build_catalog(payload: dict) -> Catalog:
    if payload.get("currency") != "RUB":
        raise ValueError("Пилот ведёт цены только в RUB.")
    items: list[Item] = []
    seen: set[str] = set()
    for raw in payload["items"]:
        sku = raw["sku"]
        if sku in seen:
            raise ValueError(f"Повторяется артикул {sku}.")
        seen.add(sku)
        price = int(raw["price_rub"])
        max_qty = int(raw["max_qty"])
        if price <= 0 or max_qty < 1:
            raise ValueError(f"Некорректная цена или лимит количества у {sku}.")
        synonyms = list(raw["synonyms"])
        synonyms.append(raw["name"])
        items.append(
            Item(
                sku=sku,
                name=raw["name"],
                unit=raw["unit"],
                price_rub=price,
                max_qty=max_qty,
                synonyms=tuple(synonyms),
            )
        )
    items.sort(key=lambda item: item.sku)
    return Catalog(payload["currency"], tuple(items), {item.sku: item for item in items})


def build_registry(rows: list[dict]) -> Registry:
    clients: list[Client] = []
    by_id: dict[str, Client] = {}
    by_inn: dict[str, Client] = {}
    by_domain: dict[str, Client] = {}
    by_alias: dict[str, Client] = {}
    for raw in rows:
        addresses = tuple(
            Address(id=item["id"], full=item["full"], hints=tuple(item["hints"]))
            for item in raw["addresses"]
        )
        client = Client(
            id=raw["id"],
            legal_name=raw["legal_name"],
            inn=normalize_inn(raw["inn"]) or "",
            email_domains=tuple(domain.lower() for domain in raw["email_domains"]),
            aliases=tuple(raw.get("aliases", [])),
            credit_limit_rub=int(raw["credit_limit_rub"]),
            addresses=addresses,
        )
        if not client.inn or client.credit_limit_rub < 0:
            raise ValueError(f"Карточка {client.id} без ИНН или с отрицательным лимитом.")
        if client.id in by_id:
            raise ValueError(f"Повторяется клиент {client.id}.")
        if client.inn in by_inn:
            raise ValueError(f"Повторяется ИНН {client.inn}.")
        by_id[client.id] = client
        by_inn[client.inn] = client
        for domain in client.email_domains:
            if domain in by_domain:
                raise ValueError(f"Домен {domain} привязан к двум клиентам.")
            by_domain[domain] = client
        for label in (client.legal_name, *client.aliases):
            key = norm(label)
            if not key:
                continue
            if key in by_alias and by_alias[key].id != client.id:
                raise ValueError(f"Название «{label}» указывает на разных клиентов.")
            by_alias[key] = client
        clients.append(client)
    clients.sort(key=lambda client: client.id)
    return Registry(tuple(clients), by_id, by_inn, by_domain, by_alias)


def sender_domain(sender: str) -> str:
    return email_domain(sender)
