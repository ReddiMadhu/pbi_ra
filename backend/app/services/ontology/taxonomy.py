"""Hierarchical ontology taxonomy: sector → subdomain."""

from __future__ import annotations

import os
import re

SECTORS = ("insurance", "banking", "finance", "operational")

# Canonical subdomain keys stored in DB (lowercase snake / underscore form).
# Insurance mirrors Excel "Applicability with Sheet Names":
#   Marketing, Distribution, Actuarial & Risk, underwriting,
#   Claims_Litigation, Service & Operations, CX & Digital
SUBDOMAINS_BY_SECTOR: dict[str, tuple[str, ...]] = {
    "insurance": (
        "marketing",
        "distribution",
        "actuarial_and_risk",
        "underwriting",
        "claims_litigation",
        "service_and_operations",
        "cx_and_digital",
    ),
    "banking": ("retail", "corporate", "risk", "shared"),
    "finance": ("accounting", "treasury", "fp_and_a", "shared"),
    "operational": ("supply_chain", "hr", "it_ops", "shared"),
}

# Pretty labels for UI / Excel export
SUBDOMAIN_DISPLAY_LABELS: dict[str, str] = {
    "marketing": "Marketing",
    "distribution": "Distribution",
    "actuarial_and_risk": "Actuarial & Risk",
    "underwriting": "underwriting",
    "claims_litigation": "Claims_Litigation",
    "service_and_operations": "Service & Operations",
    "cx_and_digital": "CX & Digital",
    "retail": "Retail",
    "corporate": "Corporate",
    "risk": "Risk",
    "shared": "Shared",
    "accounting": "Accounting",
    "treasury": "Treasury",
    "fp_and_a": "FP&A",
    "supply_chain": "Supply Chain",
    "hr": "HR",
    "it_ops": "IT Ops",
}

# Any human / Excel / typo form → canonical subdomain key
SUBDOMAIN_ALIASES: dict[str, str] = {
    # marketing
    "marketing": "marketing",
    # distribution
    "distribution": "distribution",
    "distiribution": "distribution",  # typo
    # actuarial & risk
    "actuarial_and_risk": "actuarial_and_risk",
    "actuarial & risk": "actuarial_and_risk",
    "actuarial and risk": "actuarial_and_risk",
    "acturial & risk": "actuarial_and_risk",
    "acutrial & risk": "actuarial_and_risk",
    "acturial and risk": "actuarial_and_risk",
    "actuarial": "actuarial_and_risk",
    "actuarial risk": "actuarial_and_risk",
    # underwriting
    "underwriting": "underwriting",
    "underwrite": "underwriting",
    "uw": "underwriting",
    # claims litigation
    "claims_litigation": "claims_litigation",
    "claims litigation": "claims_litigation",
    "claims & litigation": "claims_litigation",
    "claims and litigation": "claims_litigation",
    "claimns_ligtation": "claims_litigation",  # typo
    "claims": "claims_litigation",
    "litigation": "claims_litigation",
    # service & operations — keep these specific; do NOT map bare "service"/"operations"
    # alone (too broad — caused many KPI sheets to land in Service & Operations)
    "service_and_operations": "service_and_operations",
    "service & operations": "service_and_operations",
    "service and operations": "service_and_operations",
    "service operations": "service_and_operations",
    "service_operations": "service_and_operations",
    # cx & digital
    "cx_and_digital": "cx_and_digital",
    "cx & digital": "cx_and_digital",
    "cx and digital": "cx_and_digital",
    "cx digital": "cx_and_digital",
    "cx&digital": "cx_and_digital",
    "cx & diigtal": "cx_and_digital",  # typo
    "cx diigtal": "cx_and_digital",
    "customer experience": "cx_and_digital",
    "customer experience & digital": "cx_and_digital",
    "digital": "cx_and_digital",
    "digital cx": "cx_and_digital",
    # legacy short names → closest new subdomain
    "shared": "service_and_operations",
}

# Legacy dashboard domain_classification → suggested subdomain
LEGACY_DOMAIN_TO_SUBDOMAIN: dict[str, tuple[str, str]] = {
    "claims & risk": ("insurance", "claims_litigation"),
    "claims and risk": ("insurance", "claims_litigation"),
    "customer service": ("insurance", "service_and_operations"),
    "new business ops": ("insurance", "underwriting"),
    "sales & pipeline": ("insurance", "marketing"),
    "sales and pipeline": ("insurance", "marketing"),
    "product level performance": ("insurance", "actuarial_and_risk"),
    "product-level performance": ("insurance", "actuarial_and_risk"),
    "marketing": ("insurance", "marketing"),
    "distribution": ("insurance", "distribution"),
    "actuarial & risk": ("insurance", "actuarial_and_risk"),
    "claims_litigation": ("insurance", "claims_litigation"),
    "service & operations": ("insurance", "service_and_operations"),
    "cx & digital": ("insurance", "cx_and_digital"),
    "cx and digital": ("insurance", "cx_and_digital"),
}

# Excel applicability sheet string → (sector, subdomain) — identity map via aliases
APPLICABILITY_SHEET_TO_SCOPE: dict[str, tuple[str, str]] = {
    alias: ("insurance", canonical)
    for alias, canonical in SUBDOMAIN_ALIASES.items()
    if canonical in SUBDOMAINS_BY_SECTOR["insurance"]
}

DEFAULT_SECTOR = "insurance"
DEFAULT_SUBDOMAIN = "service_and_operations"
PENDING_SUBDOMAIN = "pending_scope"


def _norm_label(value: str) -> str:
    text = value.strip().lower().replace("_", " ")
    text = re.sub(r"[()\[\]{}]", " ", text)
    text = re.sub(r"\s*&\s*", " & ", text)
    return " ".join(text.split())


def canonicalize_subdomain(raw: str | None) -> str | None:
    """Map any alias / display label to a canonical subdomain key."""
    if not raw:
        return None
    key = _norm_label(str(raw))
    if key in SUBDOMAIN_ALIASES:
        return SUBDOMAIN_ALIASES[key]
    # Also try underscore form: "claims litigation" already handled; "claims_litigation"
    underscored = key.replace(" & ", "_and_").replace(" ", "_")
    if underscored in SUBDOMAIN_ALIASES:
        return SUBDOMAIN_ALIASES[underscored]
    if underscored in {s for subs in SUBDOMAINS_BY_SECTOR.values() for s in subs}:
        return underscored
    return None


def suggest_scope_from_applicability(applicability: str | None) -> tuple[str, str]:
    """
    Infer (sector, subdomain) from comma-separated sheet applicability names.
    Uses the sheet name itself as the subdomain (via aliases).
    If multiple distinct subdomains appear → first match (not collapsed away).
    """
    if not applicability:
        return DEFAULT_SECTOR, DEFAULT_SUBDOMAIN
    parts = [
        p.strip()
        for p in str(applicability).replace("|", ",").replace(";", ",").split(",")
        if p.strip()
    ]
    if not parts:
        return DEFAULT_SECTOR, DEFAULT_SUBDOMAIN

    scopes: list[tuple[str, str]] = []
    for part in parts:
        canonical = canonicalize_subdomain(part)
        if canonical and canonical in SUBDOMAINS_BY_SECTOR["insurance"]:
            scopes.append(("insurance", canonical))
            continue
        key = _norm_label(part)
        hit = APPLICABILITY_SHEET_TO_SCOPE.get(key)
        if not hit:
            hit = APPLICABILITY_SHEET_TO_SCOPE.get(key.replace(" & ", " and "))
        if hit:
            scopes.append(hit)

    if not scopes:
        return DEFAULT_SECTOR, DEFAULT_SUBDOMAIN
    # Prefer first listed sheet as primary subdomain (preserve user order)
    return scopes[0]


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
    canonical = canonicalize_subdomain(subdomain) or subdomain.strip().lower()
    allowed = SUBDOMAINS_BY_SECTOR.get(sec, ())
    return canonical if canonical in allowed else None


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
            sec, sub = hint[0], hint[1]
        else:
            # Try treating legacy_domain as an applicability / sheet name
            inferred = canonicalize_subdomain(legacy_domain)
            if inferred:
                sec, sub = DEFAULT_SECTOR, inferred

    if not sec:
        sec = DEFAULT_SECTOR
    if not sub:
        # Last chance: subdomain raw might be an alias even without sector
        sub = validate_subdomain(sec, subdomain) or DEFAULT_SUBDOMAIN
    return sec, sub


def suggest_from_legacy_domain(domain_classification: str | None) -> tuple[str, str]:
    if not domain_classification:
        return DEFAULT_SECTOR, DEFAULT_SUBDOMAIN
    hint = LEGACY_DOMAIN_TO_SUBDOMAIN.get(domain_classification.strip().lower())
    if hint:
        return hint
    inferred = canonicalize_subdomain(domain_classification)
    if inferred and inferred in SUBDOMAINS_BY_SECTOR[DEFAULT_SECTOR]:
        return DEFAULT_SECTOR, inferred
    return DEFAULT_SECTOR, DEFAULT_SUBDOMAIN


def get_taxonomy_for_api() -> dict:
    return {
        "sectors": list(SECTORS),
        "active_sectors": get_active_sectors(),
        "subdomains_by_sector": {k: list(v) for k, v in SUBDOMAINS_BY_SECTOR.items()},
        "subdomain_display_labels": dict(SUBDOMAIN_DISPLAY_LABELS),
    }
