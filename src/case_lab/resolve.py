"""Закрытые справочники. Можно подтвердить однозначное совпадение. Нельзя достроить пустое поле."""

from __future__ import annotations

from dataclasses import dataclass

from case_lab.domain import Address, Catalog, Client, Registry, sender_domain
from case_lab.schemas import OrderFields
from case_lab.textutil import norm, normalize_inn


@dataclass(frozen=True)
class ClientResolution:
    status: str
    client: Client | None
    detail: str


def match_skus(raw_name: str, catalog: Catalog) -> list[str]:
    """Побеждает самый длинный синоним. Ничья — неоднозначность, даже если модель уже выбрала артикул."""

    padded = f" {norm(raw_name)} "
    best: dict[str, int] = {}
    for item in catalog.items:
        length = 0
        for synonym in item.synonyms:
            token = norm(synonym)
            if len(token) < 3:
                continue
            if f" {token} " in padded:
                length = max(length, len(token))
        if length:
            best[item.sku] = length
    if not best:
        return []
    top = max(best.values())
    return sorted(sku for sku, length in best.items() if length == top)


def resolve_client(sender: str, order: OrderFields | None, registry: Registry) -> ClientResolution:
    raw_inn = order.client_inn.strip() if order and order.client_inn else ""
    inn = normalize_inn(raw_inn) if raw_inn else None
    malformed_inn = bool(raw_inn) and inn is None
    name = order.client_name if order else None
    domain = sender_domain(sender)

    inn_hit = registry.by_inn.get(inn) if inn else None
    domain_hit = registry.by_domain.get(domain) if domain else None
    name_key = norm(name) if name else ""
    name_hit = registry.by_alias.get(name_key) if name_key else None

    if malformed_inn and (domain_hit or name_hit):
        return ClientResolution(
            "conflict",
            None,
            "В письме указан ИНН, но в нём нет цифр. Автопривязка по домену остановлена.",
        )
    if inn and inn_hit is None and (domain_hit or name_hit):
        return ClientResolution(
            "conflict",
            None,
            "ИНН из письма нет в реестре, хотя домен или название совпали с карточкой. Автопривязка остановлена.",
        )

    hits: list[Client] = []
    for client in (inn_hit, domain_hit, name_hit):
        if client is not None and all(client.id != existing.id for existing in hits):
            hits.append(client)
    if len(hits) > 1:
        names = ", ".join(client.id for client in hits)
        return ClientResolution("conflict", None, f"Сигналы указывают на разных клиентов: {names}.")
    if len(hits) == 1:
        return ClientResolution("ok", hits[0], hits[0].legal_name)
    return ClientResolution(
        "unresolved",
        None,
        "Клиент не найден по ИНН, домену отправителя и точному названию.",
    )


def match_address(client: Client, raw_address: str) -> tuple[str, Address | None, str]:
    text = norm(raw_address)
    if not text:
        return "missing", None, "Адрес доставки пуст."
    padded = f" {text} "
    found: dict[str, Address] = {}
    for address in client.addresses:
        for hint in address.hints:
            token = norm(hint)
            if token and f" {token} " in padded:
                found[address.id] = address
                break
    if len(found) == 1:
        address = next(iter(found.values()))
        return "ok", address, address.full
    if not found:
        return "unresolved", None, f"«{raw_address}» нет среди точек доставки {client.legal_name}."
    options = ", ".join(sorted(found))
    return "ambiguous", None, f"Подходят несколько адресов: {options}."
