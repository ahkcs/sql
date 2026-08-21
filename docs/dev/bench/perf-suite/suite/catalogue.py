"""PPL query catalogue — 11 categories (plan §2.4) over the mock-* indices,
using the real obs-pi field paths. Queries are templates; the runner injects a
time-range WHERE clause and repeats per time range.

Not a literal 1:1 of the customer's 984-query set (that lives in Ryan's runner);
this is a representative, field-accurate catalogue we can grow. `known_slow`
marks the intentional stressors (high-cardinality group-by, rex on body,
cross-index sweeps). A few unfiltered aggregations carry a `correctness` spec
checked against mock_data.expected.
"""
from collections import namedtuple
from datetime import datetime, timezone

from mock_data import distributions as dist

QueryTest = namedtuple("QueryTest", "id category source template known_slow correctness")

# seconds per time-range key
TIME_RANGES = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
WIDE_RANGES = {"3d": 259200, "7d": 604800}

SEV = "severityText"
NS = "resource.attributes.k8s.namespace.name"
SVC = "resource.attributes.service.name"
REGION = "resource.attributes.cloud.region"
POD = "resource.attributes.k8s.pod.name"          # ~10.8M cardinality -> stressor
APP = "resource.attributes.applicationid"
STATUS = "log.status"


def time_where(tr):
    """WHERE clause (with leading '| ' and trailing space) for a time-range key,
    or '' for an unfiltered (full-index) query. Lower bound = anchor - range."""
    if tr is None:
        return ""
    secs = TIME_RANGES.get(tr) or WIDE_RANGES.get(tr) or {"6h": 21600}[tr]
    lb_ms = dist.ANCHOR_MS - secs * 1000
    lb = datetime.fromtimestamp(lb_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return "| where @timestamp >= '%s' " % lb


def full_query(qt, tr):
    return qt.template.format(source=qt.source, tw=time_where(tr))


def build_catalogue():
    """Return the list of QueryTest templates (time range applied by the runner)."""
    q = []

    def add(cat, id_, source, rest, known_slow=False, correctness=None):
        q.append(QueryTest(id_, cat, source, "source={source} {tw}" + rest,
                           known_slow, correctness))

    # simple-search
    add("simple-search", "search_error", "mock-kv-pi", "| where %s='ERROR'" % SEV)
    add("simple-search", "search_body_like", "mock-mixed-pi", "| where like(body, '%timeout%')")

    # browse-table
    add("browse-table", "browse_head", "mock-kv-pi",
        "| fields @timestamp, severityText, serviceName, body | head 100")

    # stats-aggregate  (severity carries a correctness check, unfiltered)
    add("stats-aggregate", "stats_by_severity", "mock-kv-pi", "| stats count() by %s" % SEV,
        correctness={"kind": "count_by", "index": "mock-kv-pi", "field": "severityText"})
    add("stats-aggregate", "stats_by_region", "mock-kv-pi", "| stats count() by %s" % REGION,
        correctness={"kind": "count_by", "index": "mock-kv-pi", "field": "region"})
    add("stats-aggregate", "stats_by_namespace", "mock-json-http", "| stats count() by %s" % NS,
        correctness={"kind": "count_by", "index": "mock-json-http", "field": "k8s_namespace"})
    add("stats-aggregate", "stats_by_pod_HIGHCARD", "mock-kv-pi",
        "| stats count() by %s" % POD, known_slow=True)

    # eval-stats
    add("eval-stats", "eval_sevhi", "mock-kv-pi",
        "| eval sev_hi = severityNumber >= 13 | stats count() by sev_hi")
    add("eval-stats", "eval_avg_bodylen", "mock-kv-pi",
        "| stats avg(attributes.obs_body_length) as avg_len by %s" % REGION)

    # field-extract
    add("field-extract", "fx_http_status", "mock-json-http",
        "| fields %s, %s | stats count() by %s" % (SVC, STATUS, STATUS))

    # rex
    add("rex", "rex_http_method", "mock-json-http",
        r'| rex field=body "\"(?<method>\w+) " | stats count() by method')
    add("rex", "rex_body_word_HIGH", "mock-mixed-pi",
        r'| rex field=body "(?<w>\w+)" | stats count() by w', known_slow=True)

    # timechart
    add("timechart", "tc_count_1h", "mock-kv-pi", "| stats count() by span(@timestamp, 1h)")
    add("timechart", "tc_count_by_sev", "mock-kv-pi",
        "| stats count() by span(@timestamp, 1h), %s" % SEV)

    # dedup
    add("dedup", "dedup_service", "mock-kv-pi", "| dedup %s" % SVC)
    add("dedup", "dedup_pod_HIGHCARD", "mock-kv-pi", "| dedup %s" % POD, known_slow=True)

    # top-n
    add("top-n", "top_service", "mock-kv-pi", "| top 10 %s" % SVC)
    add("top-n", "top_namespace", "mock-json-http", "| top 10 %s" % NS)

    # stacked  (multi-dimension group-by)
    add("stacked", "stacked_sev_region", "mock-kv-pi",
        "| stats count() by %s, %s" % (SEV, REGION))
    add("stacked", "stacked_ns_status", "mock-json-http",
        "| stats count() by %s, %s" % (NS, STATUS))

    # bad-queries  (intentional stressors)
    add("bad-queries", "cross_index_pod_HIGHCARD", "mock-*",
        "| stats count() by %s" % POD, known_slow=True)
    add("bad-queries", "big_sort_head", "mock-kv-pi",
        "| sort %s | head 1000" % POD, known_slow=True)

    return q
