"""The 10 mock indices: name -> (sourcetype, Tier-1 doc count).

sourcetype None == the heterogeneous multi-format index (sourcetype drawn per doc).
Tier-1 counts are from the plan's §3.2; load.py scales them down for dev via
--scale-divisor (or overrides with --docs-per-index).
"""

# name -> (sourcetype, tier1_docs)
INDICES = {
    "mock-kv-pi":         ("kv",          50_000_000),
    "mock-mixed-pi":      ("mixed",       15_000_000),
    "mock-nested-cape":   ("nested",      10_000_000),
    "mock-json-dd":       ("json-dd",      5_000_000),
    "mock-json-ecs":      ("json-ecs",     5_000_000),
    "mock-json-spring":   ("json-spring",    800_000),
    "mock-kv-quoted-wi":  ("kv-quoted",      500_000),
    "mock-json-fid":      ("json-fid",       500_000),
    "mock-json-http":     ("json-http",      150_000),
    "mock-multi-format":  (None,           1_000_000),
}


def seed_for(index, base=42):
    """Stable per-index seed so every index is an independent, reproducible stream.
    Position-based (not enumeration-based) so --only subsetting can't shift it."""
    return base + list(INDICES).index(index) * 1000


def index_docs(divisor=1, docs_per_index=None):
    """Resolve per-index doc counts for a run.
    docs_per_index overrides everything (flat count); else Tier-1 // divisor."""
    out = {}
    for name, (st, n) in INDICES.items():
        out[name] = (st, docs_per_index if docs_per_index else max(1, n // divisor))
    return out
