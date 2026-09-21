"""PPL query catalogue — holistic Perf-pillar catalogue (plan §2.1).

Three groups, all validated live against the OS 3.5 Calcite build (2026-09-21):

- **command** — one representative query per supported PPL command, on the primary
  index `mock-kv-pi` (+ `mock-json-http` for spath, + `mock-lookup-sev` for
  join/lookup/subquery). Covers every documented command EXCEPT meta/ML ones
  (describe/explain/rest/index/makeresults/syntax/showdatasources/ad/kmeans/ml/
  graphlookup) and three documented-but-not-in-the-3.5-grammar commands:
  **xyseries, timewrap, foreach** (SyntaxCheckException — see UNSUPPORTED_ON_35).
- **format** — the same 4 probes on each of the 10 mock indices, using only fields
  present in every body format, so latency differences are attributable to the
  format (kv vs json vs nested), not the query.
- **scenario** — a few multi-clause stressors kept for continuity with prior
  findings (leading-wildcard LIKE on body, cross-index sweep, etc.).

`known_slow=True` marks whole-result-set / high-cardinality / full-scan stressors.
The runner injects the time-range WHERE via the literal `{tw}` marker
(str.replace, NOT str.format — grok patterns contain literal braces).
"""
from collections import namedtuple
from datetime import datetime, timezone

from mock_data import distributions as dist

QueryTest = namedtuple("QueryTest", "id category source template known_slow correctness")

TIME_RANGES = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
WIDE_RANGES = {"3d": 259200, "7d": 604800}

INDICES = ["mock-kv-pi", "mock-kv-quoted-wi", "mock-mixed-pi", "mock-json-dd",
           "mock-json-ecs", "mock-json-spring", "mock-json-fid", "mock-json-http",
           "mock-nested-cape", "mock-multi-format"]

SEV = "severityText"
REGION = "resource.attributes.cloud.region"
POD = "resource.attributes.k8s.pod.name"          # ~10.8M cardinality -> stressor


def time_where(tr):
    """WHERE clause (leading '| ', trailing space) for a time-range key, or '' for
    an unfiltered query. Lower bound = anchor - range."""
    if tr is None:
        return ""
    secs = TIME_RANGES.get(tr) or WIDE_RANGES.get(tr) or {"6h": 21600}[tr]
    lb_ms = dist.ANCHOR_MS - secs * 1000
    lb = datetime.fromtimestamp(lb_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return "| where @timestamp >= '%s' " % lb


def full_query(qt, tr):
    """Inject the time window. str.replace on `{tw}` (not str.format) so literal
    braces in grok patterns survive."""
    return qt.template.replace("{tw}", time_where(tr))


_KV = "source=mock-kv-pi {tw}"

# command, template (with {tw}), known_slow
COMMANDS = [
    ("search",      "search source=mock-kv-pi {tw}| where severityText='ERROR' | head 100", False),
    ("where",       _KV + "| where severityNumber>=13 | head 100", False),
    ("regex",       _KV + "| regex body='timeout' | head 100", True),
    ("fields",      _KV + "| fields severityText, serviceName, body | head 100", False),
    ("table",       _KV + "| table severityText, serviceName | head 100", False),
    ("rename",      _KV + "| rename severityText as sev | head 100", False),
    ("transpose",   _KV + "| stats count() by severityText | transpose", False),
    ("eval",        _KV + "| eval hi = severityNumber>=13 | head 100", False),
    ("convert",     _KV + "| convert num(severityNumber) as sn | head 100", False),
    ("fillnull",    _KV + "| fillnull with 0 in severityNumber | head 100", False),
    ("replace",     _KV + "| replace 'ERROR' with 'ERR' in severityText | head 100", False),
    ("fieldformat", _KV + "| fieldformat severityNumber = severityNumber + 0 | head 100", False),
    ("rex",         _KV + r'| rex field=body "(?<w>\w+)" | head 100', False),
    ("parse",       _KV + r'| parse body "(?<w>\w+)" | head 100', False),
    ("grok",        _KV + '| grok body "%{WORD:w}" | head 100', False),
    ("patterns",    _KV + "| patterns body | head 100", True),
    ("spath",       "source=mock-json-http {tw}| spath input=body | head 100", False),
    ("stats",       _KV + "| stats count() by severityText", False),
    ("eventstats",  _KV + "| eventstats count() as c by severityText | head 100", True),
    ("streamstats", _KV + "| streamstats count() as c | head 100", True),
    ("top",         _KV + "| top 10 serviceName", False),
    ("rare",        _KV + "| rare severityText", False),
    ("addtotals",   _KV + "| stats count() as c by severityText | addtotals", False),
    ("addcoltotals", _KV + "| stats count() as c by severityText | addcoltotals", False),
    ("bin",         _KV + "| bin severityNumber span=5 | stats count() by severityNumber", False),
    ("timechart",   _KV + "| timechart span=1h count()", False),
    ("chart",       _KV + "| chart count() by severityText", False),
    ("trendline",   _KV + "| timechart span=1h count() as c | trendline sma(2,c)", False),
    ("sort",        _KV + "| sort severityNumber | head 100", False),
    ("reverse",     _KV + "| head 100 | reverse", False),
    ("dedup",       _KV + "| dedup serviceName | head 100", False),
    ("head",        _KV + "| head 100", False),
    ("mvexpand",    _KV + "| eval arr = split(body,' ') | mvexpand arr | head 100", False),
    ("mvcombine",   _KV + "| fields severityText | head 50 | mvcombine severityText", False),
    ("nomv",        _KV + "| eval arr = split(body,' ') | nomv arr | head 100", False),
    ("expand",      _KV + "| eval arr = split(body,' ') | expand arr | head 100", False),
    ("flatten",     _KV + "| flatten resource | head 100", False),
    ("append",      _KV + "| stats count() as c | append [ search source=mock-kv-pi {tw}| stats count() as c ]", False),
    ("appendpipe",  _KV + "| stats count() as c by severityText | appendpipe [ | stats sum(c) as c ]", False),
    ("appendcol",   _KV + "| stats count() as c by `resource.attributes.service.name` | appendcol [ where severityText='ERROR' | stats count() as errs ]", False),
    ("union",       _KV + "| fields severityText | head 100 | union [ search source=mock-json-http {tw}| fields severityText | head 100 ]", False),
    ("multisearch", "| multisearch [ search source=mock-kv-pi {tw}| fields severityText ] [ search source=mock-mixed-pi {tw}| fields severityText ] | head 100", False),
    ("join",        _KV + "| head 1000 | join left=l right=r on l.severityText=r.severityText [ search source=mock-lookup-sev ] | head 100", True),
    ("lookup",      _KV + "| lookup mock-lookup-sev severityText | head 100", False),
    ("subquery",    _KV + "| where severityText in [ search source=mock-lookup-sev | fields severityText ] | head 100", False),
]

# probe id, op (after '{tw}'), known_slow — run against each of the 10 indices
FORMAT_PROBES = [
    ("sev",  "| stats count() by " + SEV, False),
    ("pod",  "| stats count() by " + POD, True),
    ("rex",  r'| rex field=body "(?<w>\w+)" | stats count() by w', True),
    ("scan", "| where severityText='ERROR' | head 100", False),
]

# id, template (with {tw}), known_slow — aggregation-function coverage on mock-kv-pi.
# Exercises the numeric/agg-function paths (avg/sum/min/max/percentile/dc/stddev/var)
# and the `long` field type (attributes.obs_body_length), which the command axis
# only ever hit with count().
AGG_FUNCS = [
    ("agg_numeric_longfield", _KV + "| stats avg(attributes.obs_body_length) as a, sum(attributes.obs_body_length) as s, min(attributes.obs_body_length) as mn, max(attributes.obs_body_length) as mx", False),
    ("agg_percentile",        _KV + "| stats percentile(attributes.obs_body_length, 95) as p95", False),
    ("agg_dc_HIGHCARD",       _KV + "| stats dc(resource.attributes.k8s.pod.name) as d", True),
    ("agg_dc_service",        _KV + "| stats dc(resource.attributes.service.name) as d", False),
    ("agg_stddev",            _KV + "| stats stddev_samp(attributes.obs_body_length) as sd", False),
    ("agg_var",               _KV + "| stats var_samp(attributes.obs_body_length) as v", False),
]

# id, source, template (with {tw}), known_slow — continuity stressors
SCENARIOS = [
    ("scn_body_like_LEADWILD", "mock-mixed-pi", "source=mock-mixed-pi {tw}| where like(body, '%timeout%')", True),
    ("scn_cross_index_pod",    "mock-*",        "source=mock-* {tw}| stats count() by " + POD, True),
    ("scn_stacked_sev_region", "mock-kv-pi",    _KV + "| stats count() by %s, %s" % (SEV, REGION), False),
    ("scn_eval_then_stats",    "mock-kv-pi",    _KV + "| eval hi = severityNumber>=13 | stats count() by hi", False),
    ("scn_big_sort_head",      "mock-kv-pi",    _KV + "| sort %s | head 1000" % POD, True),
]

# Documented in-repo but rejected by the deployed 3.5 PPL grammar (SyntaxCheckException).
UNSUPPORTED_ON_35 = ["xyseries", "timewrap", "foreach"]


def build_catalogue():
    q = []
    for cmd, template, slow in COMMANDS:
        src = "mock-json-http" if cmd == "spath" else "mock-kv-pi"
        q.append(QueryTest("cmd_%s" % cmd, "command", src, template, slow, None))
    for idx in INDICES:
        for probe, op, slow in FORMAT_PROBES:
            q.append(QueryTest("fmt_%s_%s" % (probe, idx), "format", idx,
                               "source=%s {tw}%s" % (idx, op), slow, None))
    for id_, template, slow in AGG_FUNCS:
        q.append(QueryTest(id_, "agg-func", "mock-kv-pi", template, slow, None))
    for id_, src, template, slow in SCENARIOS:
        q.append(QueryTest(id_, "scenario", src, template, slow, None))
    return q
