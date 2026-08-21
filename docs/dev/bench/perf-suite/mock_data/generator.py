"""Deterministic synthetic OTel-log document generator.

Emits documents matching schemas/mock-index-template.json (the obs-pi OTel schema):
one shared envelope + resource.attributes / attributes dimensions, with body-format
variation carried by `body` + the `log.*` object, one emitter per sourcetype.

Deterministic: seed the RNG and the same (seed, n, sourcetype) yields the same stream,
so expected.py can tally exact ground truth without a cluster.
"""
import hashlib
import json
import random

from . import distributions as dist
from . import wide_schema

METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
URIS = ["/", "/checkout", "/cart", "/api/v1/orders", "/api/v1/users", "/health",
        "/search", "/login", "/payments/authorize", "/inventory/reserve"]
LOGGERS = ["c.a.OrderController", "c.a.PaymentService", "c.a.InventoryDao",
           "c.a.AuthFilter", "o.s.web.DispatcherServlet"]
ERROR_TYPES = ["NullPointerException", "TimeoutException", "IllegalStateException",
               "SQLException", "ConnectException"]
USER_AGENTS = ["Mozilla/5.0", "curl/8.4.0", "okhttp/4.11", "python-requests/2.31"]

# cache Zipf weight vectors (recomputing per-doc would be wasteful)
_SVC_W = dist.zipf_weights(dist.SERVICE_CARDINALITY, dist.SERVICE_ZIPF_S)
_APP_W = dist.zipf_weights(dist.APP_CARDINALITY, dist.APP_ZIPF_S)
_PROD_W = dist.zipf_weights(dist.PRODUCT_CARDINALITY, dist.PRODUCT_ZIPF_S)
_SEV_K, _SEV_W = dist.weighted_keys(dist.SEVERITY_TEXT)
_ST_K, _ST_W = dist.weighted_keys(dist.SOURCETYPES)
_HTTP_K, _HTTP_W = dist.weighted_keys(dist.HTTP_STATUS)
_CRIT_K, _CRIT_W = dist.weighted_keys(dist.CRITICALITY)


def _hex(rng, nbytes):
    return "%0*x" % (nbytes * 2, rng.getrandbits(nbytes * 8))


def _draw_dimensions(rng, sourcetype=None):
    sev = rng.choices(_SEV_K, _SEV_W)[0]
    lo, hi = dist.SEVERITY_NUMBER_BANDS[sev]
    region = rng.choice(dist.REGIONS)
    ns = rng.choice(dist.K8S_NAMESPACES)
    svc = rng.choices(dist.SERVICE_NAMES, _SVC_W)[0]
    st = sourcetype or rng.choices(_ST_K, _ST_W)[0]
    return {
        "ts": rng.randrange(dist.WINDOW_START_MS, dist.ANCHOR_MS),
        "sev_text": sev,
        "sev_num": rng.randint(lo, hi),
        "region": region,
        "az": region + rng.choice("abc"),
        "env": rng.choice(dist.CLUSTER_ENVS),
        "namespace": ns,
        "pod": "%s-%s" % (ns, _hex(rng, 6)),
        "node": "ip-10-%d-%d-%d" % (rng.randrange(256), rng.randrange(256), rng.randrange(256)),
        "service": svc,
        "appid": rng.choices(dist.APP_IDS, _APP_W)[0],
        "productid": rng.choices(dist.PRODUCT_IDS, _PROD_W)[0],
        "criticality": rng.choices(_CRIT_K, _CRIT_W)[0],
        "cio": rng.choice(dist.CIO_ORGS),
        "log_tier": rng.choices(dist.LOG_TIERS, dist.LOG_TIER_WEIGHTS)[0],
        "sourcetype": st,
        "dur": rng.randint(1, 2000),
    }


# --- per-sourcetype emitters: (rng, dims) -> (body_str, log_obj) ---

def _emit_kv(rng, d):
    body = ("ts=%d level=%s service=%s ns=%s msg=request_handled dur_ms=%d"
            % (d["ts"], d["sev_text"], d["service"], d["namespace"], d["dur"]))
    return body, {"message": "request_handled", "log": {"level": d["sev_text"]}}


def _emit_kv_quoted(rng, d):
    body = ('ts="%d" level="%s" service="%s" msg="request handled for %s" latency="%dms"'
            % (d["ts"], d["sev_text"], d["service"], d["appid"], d["dur"]))
    return body, {"message": "request handled", "log": {"level": d["sev_text"]}}


def _emit_mixed(rng, d):
    body = ("%d [%s] %s: handled id=%s took %dms"
            % (d["ts"], d["sev_text"], d["service"], _hex(rng, 4), d["dur"]))
    return body, {"message": "handled", "log": {"level": d["sev_text"]}}


def _emit_json_dd(rng, d):
    log = {"message": "request handled", "status": d["sev_text"].lower(),
           "log": {"level": d["sev_text"]}}
    return json.dumps({"ddsource": "java", "service": d["service"], **log}), log


def _emit_json_ecs(rng, d):
    log = {"ecs": {"version": "1.6.0"}, "log": {"level": d["sev_text"]},
           "message": "request handled"}
    if d["sev_text"] == "ERROR":
        log["error"] = {"type": rng.choice(ERROR_TYPES), "message": "boom",
                        "stack_trace": "at c.a.X(X.java:1)"}
    return json.dumps(log), log


def _emit_json_spring(rng, d):
    thread = "http-nio-8080-exec-%d" % rng.randint(1, 50)
    logger = rng.choice(LOGGERS)
    log = {"log": {"level": d["sev_text"], "logger": logger},
           "process": {"thread": {"name": thread}},
           "mdc": {"traceId": _hex(rng, 8)}, "message": "request handled"}
    body = "%d %s [%s] %s - request handled" % (d["ts"], d["sev_text"], thread, logger)
    return body, log


def _emit_json_fid(rng, d):
    log = {"headers": {"fid-log-tracking-id": _hex(rng, 8), "fsreqid": _hex(rng, 6),
                       "AppId": d["appid"], "User-Agent": rng.choice(USER_AGENTS),
                       "Referer": "https://example.aws/" + d["namespace"]},
           "message": "request handled"}
    return json.dumps(log), log


def _emit_json_http(rng, d):
    status = rng.choices(_HTTP_K, _HTTP_W)[0]
    method = rng.choice(METHODS)
    uri = rng.choice(URIS)
    ip = "%d.%d.%d.%d" % tuple(rng.randrange(256) for _ in range(4))
    clen = rng.randint(0, 65536)
    log = {"status": status, "method": method, "uri": uri, "protocol": "HTTP/1.1",
           "remoteAddress": ip, "remoteHost": ip, "contentLength": str(clen),
           "requestTime": str(d["dur"]), "serverName": d["service"]}
    body = '%s - - [%d] "%s %s HTTP/1.1" %s %d' % (ip, d["ts"], method, uri, status, clen)
    return body, log


def _emit_nested(rng, d):
    log = {"message": "request handled", "log": {"level": d["sev_text"]}}
    if d["sev_text"] == "ERROR":
        log["error"] = {"type": rng.choice(ERROR_TYPES), "message": "boom",
                        "stack_trace": "at c.a.X(X.java:1)\n at c.a.Y(Y.java:2)"}
    body = json.dumps({"svc": d["service"], "ns": d["namespace"], "region": d["region"],
                       "detail": {"pod": d["pod"], "app": d["appid"]}})
    return body, log


EMITTERS = {
    "kv": _emit_kv, "kv-quoted": _emit_kv_quoted, "mixed": _emit_mixed,
    "json-dd": _emit_json_dd, "json-ecs": _emit_json_ecs, "json-spring": _emit_json_spring,
    "json-fid": _emit_json_fid, "json-http": _emit_json_http, "nested": _emit_nested,
}


def build_doc(rng, sourcetype=None):
    d = _draw_dimensions(rng, sourcetype)
    body, log = EMITTERS[d["sourcetype"]](rng, d)
    return {
        "@timestamp": d["ts"],
        "@version": "1",
        "observedTimestamp": d["ts"],
        "time": d["ts"],
        "body": body,
        "severityText": d["sev_text"],
        "severityNumber": d["sev_num"],
        "serviceName": d["service"],
        "traceId": _hex(rng, 16),
        "spanId": _hex(rng, 8),
        "flags": 0,
        "droppedAttributesCount": 0,
        "schemaUrl": "https://opentelemetry.io/schemas/1.20.0",
        "instrumentationScope": {"droppedAttributesCount": 0},
        "log": log,
        "attributes": {
            "cluster": {"env": d["env"], "name": "cape-" + d["region"], "region": d["region"]},
            "logtag": "F",
            "stream": "stdout",
            "obs_body_length": len(body),
        },
        "resource": {
            "attributes": {
                "applicationid": d["appid"],
                "cio_organization": d["cio"],
                "cloud": {"account": {"id": "%012d" % rng.randrange(10 ** 12)},
                          "availability_zone": d["az"], "region": d["region"]},
                "criticality_code": d["criticality"],
                "host": {"id": _hex(rng, 8), "name": d["node"]},
                "k8s": {"namespace": {"name": d["namespace"]},
                        "pod": {"name": d["pod"]},
                        "node": {"name": d["node"]},
                        "container": {"name": d["service"]}},
                "log_tier": d["log_tier"],
                "obs_namespace": d["namespace"],
                "productid": d["productid"],
                "service": {"name": d["service"]},
                "sourcetype": d["sourcetype"],
            }
        },
    }


def _set_path(doc, path, value):
    """Set a dotted path into a nested doc dict, creating intermediate objects."""
    node = doc
    for part in path.split(".")[:-1]:
        node = node.setdefault(part, {})
    node[path.split(".")[-1]] = value


def build_doc_at(seed, i, sourcetype=None, wide=True):
    """Deterministic doc for global index i under `seed`, independent of order.
    Seeding per-i (not one sequential RNG) lets parallel workers reproduce the
    exact same stream that expected.py tallies. The multiplier spaces per-index
    seeds far apart so no (seed, i) pair collides at realistic scale.

    wide=True (DEFAULT) adds sparse synthetic columns under attributes.*/
    resource.attributes.* (the ~3000-field stress schema — the only variant we
    test); the RNG stream continues from build_doc so it stays deterministic.
    wide=False yields the 75-field base (kept only for the narrow escape hatch;
    base field values are identical either way, so correctness is unaffected)."""
    rng = random.Random(seed * 2_000_000_000 + i)
    doc = build_doc(rng, sourcetype)
    if wide:
        for path, val in wide_schema.draw_extras(rng).items():
            _set_path(doc, path, val)
    return doc


def generate(n, seed=42, sourcetype=None, wide=True):
    """Yield n deterministic docs. Fix sourcetype for a single-format index, or
    None for the multi-format index (sourcetype drawn per-doc). wide=True (DEFAULT)
    emits the ~3000-field sparse-attribute variant; wide=False = 75-field base."""
    for i in range(n):
        yield build_doc_at(seed, i, sourcetype, wide)
