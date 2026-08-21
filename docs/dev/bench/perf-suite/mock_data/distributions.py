"""Canonical field value distributions for synthetic mock-* data.

Stdlib-only so generator.py / expected.py / tests can import it with no deps.
`schemas/distributions.yaml` mirrors this for humans + provenance (schema_version).

Provenance: obs-pi prod VALUES are guardrail-blocked; overlapping-field shapes are
sampled from ppl-repro-os35 (which runs de-customerized synthetic data), obs-pi-only
fields are synthesized. See schemas/distributions.yaml.
"""

SCHEMA_VERSION = "0.2.0"

# Fixed 7-day window ending at the plan's anchor (UTC), as epoch milliseconds.
# 2026-04-11 00:00:00 UTC == 1775865600 s.
ANCHOR_MS = 1775865600 * 1000
WINDOW_MS = 7 * 24 * 3600 * 1000
WINDOW_START_MS = ANCHOR_MS - WINDOW_MS

# --- verified from os35 (logs-pr172502-2026.04.07, 539.8M docs) ---

SEVERITY_TEXT = {"INFO": 0.80, "WARN": 0.12, "ERROR": 0.06, "DEBUG": 0.02}

# OTel severity-number bands per level (min, max inclusive). Observed min5 max17 avg9.88.
SEVERITY_NUMBER_BANDS = {
    "DEBUG": (5, 8),
    "INFO": (9, 12),
    "WARN": (13, 16),
    "ERROR": (17, 20),
}

REGIONS = ["us-west-2", "us-east-2", "us-east-1", "eu-west-1"]        # uniform
CLUSTER_ENVS = ["staging", "dev", "prod"]                            # uniform

K8S_NAMESPACES = [                                                   # 17, uniform
    "checkout", "risk", "tax", "inventory", "ledger", "search",
    "sessions", "fraud", "auth", "shipping", "billing", "accounts",
    "gateway", "payments", "catalog", "pricing", "notifications",
]

SERVICE_CARDINALITY = 120        # svc-<word>-<NNN>, Zipf-distributed
_SVC_WORDS = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
    "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
    "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
    "xray", "yankee", "zulu",
]
SERVICE_NAMES = [
    f"svc-{_SVC_WORDS[i % len(_SVC_WORDS)]}-{i:03d}" for i in range(SERVICE_CARDINALITY)
]
SERVICE_ZIPF_S = 1.2             # top svc-alpha-000 ~9%; long tail (59% beyond top-20)

# --- synthesized (obs-pi-only; absent/unpopulated on os35) ---

# one sourcetype per body format the catalogue exercises (weights ~ per-format query counts)
SOURCETYPES = {
    "kv": 0.18, "kv-quoted": 0.11, "mixed": 0.10,
    "json-dd": 0.11, "json-ecs": 0.11, "json-spring": 0.11,
    "json-fid": 0.10, "json-http": 0.10, "nested": 0.08,
}

APP_CARDINALITY = 50             # resource.attributes.applicationid, app-NNN, Zipf
APP_IDS = [f"app-{i:03d}" for i in range(APP_CARDINALITY)]
APP_ZIPF_S = 1.0

PRODUCT_CARDINALITY = 200        # resource.attributes.productid, prod-NNNN, Zipf
PRODUCT_IDS = [f"prod-{i:04d}" for i in range(PRODUCT_CARDINALITY)]
PRODUCT_ZIPF_S = 0.8

CRITICALITY = {"C1": 0.10, "C2": 0.20, "C3": 0.40, "C4": 0.30}

# HTTP status for the json-http sourcetype (obs-pi carries it as log.status text)
HTTP_STATUS = {"200": 0.82, "404": 0.06, "500": 0.05, "301": 0.03, "403": 0.02, "400": 0.02}

CIO_ORGS = ["retail", "aws", "devices", "ads", "ops"]                # uniform-ish
LOG_TIERS = ["standard", "critical"]                                # 0.85 / 0.15
LOG_TIER_WEIGHTS = [0.85, 0.15]


def zipf_weights(n, s):
    """Unnormalized Zipf weights w_i = 1/(i+1)**s for i in [0, n)."""
    return [1.0 / ((i + 1) ** s) for i in range(n)]


def weighted_keys(dist):
    """(keys, weights) from a {value: prob} dict, order-stable."""
    keys = list(dist.keys())
    return keys, [dist[k] for k in keys]
