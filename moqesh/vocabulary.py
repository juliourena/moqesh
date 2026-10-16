"""Pools de vocabulario genericos por tema.

Port fiel de `Moqesh.TokenExhaust.Vocabulary` (C#). Nada esta atado a un sitio
concreto: el generador elige un tema segun el seed (o el indicado) y, en modo
Mimic, mezclaria el vocabulario del perfil real.
"""

from __future__ import annotations

from .rng import SeededRandom

THEMES = ["corporate", "devops", "saas", "ecommerce"]

_DIR_WORDS = {
    "corporate": [
        "ops",
        "internal",
        "shared",
        "docs",
        "reports",
        "finance",
        "hr",
        "legal",
        "projects",
        "archive",
        "teams",
        "assets",
        "vendors",
        "contracts",
    ],
    "devops": [
        "infra",
        "deploy",
        "ci",
        "pipelines",
        "clusters",
        "secrets",
        "ansible",
        "terraform",
        "helm",
        "registry",
        "runners",
        "backups",
        "monitoring",
        "k8s",
    ],
    "saas": [
        "tenants",
        "billing",
        "accounts",
        "api",
        "webhooks",
        "integrations",
        "admin",
        "console",
        "usage",
        "exports",
        "jobs",
        "queues",
        "features",
        "config",
    ],
    "ecommerce": [
        "catalog",
        "orders",
        "customers",
        "inventory",
        "shipping",
        "payments",
        "promotions",
        "returns",
        "warehouse",
        "suppliers",
        "reports",
        "admin",
        "cart",
        "checkout",
    ],
}

_RESOURCE_WORDS = {
    "corporate": [
        "handbook",
        "policy",
        "org-chart",
        "roadmap",
        "budget",
        "onboarding",
        "review",
        "meeting-notes",
        "proposal",
        "audit",
    ],
    "devops": [
        "cluster",
        "node",
        "service",
        "ingress",
        "secret",
        "configmap",
        "runner",
        "artifact",
        "image",
        "release",
        "rollout",
        "manifest",
    ],
    "saas": [
        "tenant",
        "subscription",
        "invoice",
        "api-key",
        "webhook",
        "connector",
        "session",
        "export",
        "job",
        "quota",
        "flag",
        "plan",
    ],
    "ecommerce": [
        "product",
        "sku",
        "order",
        "customer",
        "shipment",
        "payment",
        "coupon",
        "refund",
        "supplier",
        "batch",
        "listing",
        "variant",
    ],
}

_BRAND_ROOTS = [
    "northwind",
    "acme",
    "helix",
    "vertex",
    "apex",
    "lumen",
    "quanta",
    "orbit",
    "nexus",
    "meridian",
    "cobalt",
    "sable",
    "atlas",
    "cinder",
    "halcyon",
    "argon",
    "vanta",
    "ridge",
]

_BRAND_SUFFIXES = ["systems", "labs", "cloud", "works", "io", "corp", "dynamics", "platform", "tech", "group"]

_SERVER_BANNERS = [
    "nginx",
    "nginx/1.25.3",
    "nginx/1.24.0",
    "Apache/2.4.58 (Ubuntu)",
    "Apache",
    "cloudflare",
    "Microsoft-IIS/10.0",
    "caddy",
    "openresty/1.25.3.1",
    "LiteSpeed",
]

_POWERED_BY = ["Express", "PHP/8.2.12", "Next.js", "ASP.NET", "Django", "Ruby on Rails", "", "Phusion Passenger"]


def theme_for(rng: SeededRandom, requested: str) -> str:
    return requested if requested in THEMES else THEMES[rng.below(len(THEMES))]


def dirs(theme: str) -> list[str]:
    return _DIR_WORDS.get(theme, _DIR_WORDS["corporate"])


def resources(theme: str) -> list[str]:
    return _RESOURCE_WORDS.get(theme, _RESOURCE_WORDS["corporate"])


def _cap(s: str) -> str:
    return s if not s else s[0].upper() + s[1:]


def brand(rng: SeededRandom) -> str:
    return _cap(rng.pick(_BRAND_ROOTS)) + " " + _cap(rng.pick(_BRAND_SUFFIXES))


def server_banner(rng: SeededRandom) -> str:
    return rng.pick(_SERVER_BANNERS)


def powered_by_header(rng: SeededRandom) -> str:
    return rng.pick(_POWERED_BY)
