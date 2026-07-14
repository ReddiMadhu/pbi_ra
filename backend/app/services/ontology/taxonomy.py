"""Hierarchical ontology taxonomy: sector → subdomain."""

from __future__ import annotations

import os

SECTORS = ("insurance", "banking", "finance", "operational")

SUBDOMAINS_BY_SECTOR: dict[str, tuple[str, ...]] = {
    "insurance": ("actuarial", "claims", "underwriting", "shared"),
    "banking": ("retail", "corporate", "risk", "shared"),
    "finance": ("accounting", "treasury", "fp_and_a", "shared"),
    "operational": ("supply_chain", "hr", "it_ops", "shared"),
}

# Legacy dashboard domain_classification → suggested subdomain (migration hints only)
LEGACY_DOMAIN_TO_SUBDOMAIN: dict[str, tuple[str, str]] = {
    "claims & risk": ("insurance", "claims"),
    "claims and risk": ("insurance", "claims"),
    "customer service": ("insurance", "shared"),
    "new business ops": ("insurance", "underwriting"),
    "sales & pipeline": ("insurance", "underwriting"),
    "sales and pipeline": ("insurance", "underwriting"),
    "product level performance": ("insurance", "actuarial"),
    "product-level performance": ("insurance", "actuarial"),
}

DEFAULT_SECTOR = "insurance"
DEFAULT_SUBDOMAIN = "shared"
PENDING_SUBDOMAIN = "pending_scope"


def get_active_sectors() -> list[str]:
    raw = os.getenv("ACTIVE_ONTOLOGY_SECTORS", "insurance")
    sectors = [s.strip().lower() for s in raw.split(",") if s.strip()]
    return [s for s in sectors if s in SECTORS] or [DEFAULT_SECTOR]


def is_sector_active(sector: str | None) -> bool:
    if not sector:
        return False
    return sector.lower() in get_active_sectors()


def validate_sector(sector: str | None) -> str | None:
    if not sector:
        return None
    s = sector.strip().lower()
    return s if s in SECTORS else None


def validate_subdomain(sector: str | None, subdomain: str | None) -> str | None:
    if not sector or not subdomain:
        return None
    sec = validate_sector(sector)
    if not sec:
        return None
    sub = subdomain.strip().lower()
    allowed = SUBDOMAINS_BY_SECTOR.get(sec, ())
    return sub if sub in allowed else None


def normalize_scope(
    sector: str | None,
    subdomain: str | None,
    *,
    legacy_domain: str | None = None,
) -> tuple[str, str]:
    """Return validated (sector, subdomain), with fallbacks."""
    sec = validate_sector(sector)
    sub = validate_subdomain(sec, subdomain) if sec else None

    if not sec and legacy_domain:
        hint = LEGACY_DOMAIN_TO_SUBDOMAIN.get(legacy_domain.strip().lower())
        if hint:
            sec, sub = hint

    if not sec:
        sec = DEFAULT_SECTOR
    if not sub:
        sub = DEFAULT_SUBDOMAIN
    return sec, sub


def suggest_from_legacy_domain(domain_classification: str | None) -> tuple[str, str]:
    if not domain_classification:
        return DEFAULT_SECTOR, DEFAULT_SUBDOMAIN
    hint = LEGACY_DOMAIN_TO_SUBDOMAIN.get(domain_classification.strip().lower())
    if hint:
        return hint
    return DEFAULT_SECTOR, DEFAULT_SUBDOMAIN


def get_taxonomy_for_api() -> dict:
    return {
        "sectors": list(SECTORS),
        "active_sectors": get_active_sectors(),
        "subdomains_by_sector": {k: list(v) for k, v in SUBDOMAINS_BY_SECTOR.items()},
    }
