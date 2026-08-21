"""Analytical expected values for correctness verification.

Because generation is deterministic, ground truth == re-tally the same stream.
The runner (M3) compares live PPL results against these. No cluster needed.
"""
from collections import Counter

from . import generator
from .indices import INDICES, seed_for

# logical field -> dotted doc path (what `stats ... by <field>` groups on)
FIELD_PATHS = {
    "severityText": "severityText",
    "severityNumber": "severityNumber",
    "serviceName": "resource.attributes.service.name",
    "region": "resource.attributes.cloud.region",
    "cluster_region": "attributes.cluster.region",
    "cluster_env": "attributes.cluster.env",
    "k8s_namespace": "resource.attributes.k8s.namespace.name",
    "k8s_pod": "resource.attributes.k8s.pod.name",
    "applicationid": "resource.attributes.applicationid",
    "productid": "resource.attributes.productid",
    "criticality_code": "resource.attributes.criticality_code",
    "sourcetype": "resource.attributes.sourcetype",
    "log_tier": "resource.attributes.log_tier",
    "http_status": "log.status",
}


def get_path(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def counts_by(index, field, n=None):
    """Counter of value -> doc_count for `field` over the first n docs of `index`
    (n defaults to a small verification sample, not the full Tier count)."""
    path = FIELD_PATHS[field]
    st, full = INDICES[index]
    n = n or min(full, 50_000)
    c = Counter()
    for doc in generator.generate(n, seed=seed_for(index), sourcetype=st):
        c[get_path(doc, path)] += 1
    return c


def total(index, n=None):
    st, full = INDICES[index]
    return n if n is not None else full


def count_in_range(index, start_ms, end_ms, n=None):
    """Docs whose @timestamp falls in [start_ms, end_ms)."""
    st, full = INDICES[index]
    n = n or min(full, 50_000)
    hit = 0
    for doc in generator.generate(n, seed=seed_for(index), sourcetype=st):
        if start_ms <= doc["@timestamp"] < end_ms:
            hit += 1
    return hit
