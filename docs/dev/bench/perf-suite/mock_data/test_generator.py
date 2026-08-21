#!/usr/bin/env python3
"""Generator validation: observed distributions within +/-2% of declared,
severityNumber banding, timestamp window, determinism, per-format shape.

Run: python -m mock_data.test_generator   (from perf-suite/)  -- no deps, no cluster.
Also pytest-compatible (test_* functions).
"""
from collections import Counter

from . import distributions as dist
from . import generator
from .expected import get_path

N = 300_000
TOL = 0.02  # absolute proportion tolerance


def _proportions(field_path, n=N, sourcetype=None):
    c = Counter()
    for doc in generator.generate(n, seed=7, sourcetype=sourcetype):
        c[get_path(doc, field_path)] += 1
    return {k: v / n for k, v in c.items()}, c


def test_severity_text():
    props, _ = _proportions("severityText")
    for level, want in dist.SEVERITY_TEXT.items():
        assert abs(props.get(level, 0) - want) <= TOL, (level, props.get(level), want)


def test_regions_uniform():
    props, _ = _proportions("resource.attributes.cloud.region")
    want = 1.0 / len(dist.REGIONS)
    for r in dist.REGIONS:
        assert abs(props.get(r, 0) - want) <= TOL, (r, props.get(r), want)


def test_namespaces_uniform_and_complete():
    props, c = _proportions("resource.attributes.k8s.namespace.name")
    assert set(c) == set(dist.K8S_NAMESPACES), set(dist.K8S_NAMESPACES) - set(c)
    want = 1.0 / len(dist.K8S_NAMESPACES)
    for ns in dist.K8S_NAMESPACES:
        assert abs(props.get(ns, 0) - want) <= TOL, (ns, props.get(ns), want)


def test_sourcetype_mix():
    props, _ = _proportions("resource.attributes.sourcetype")   # multi-format
    for st, want in dist.SOURCETYPES.items():
        assert abs(props.get(st, 0) - want) <= TOL, (st, props.get(st), want)


def test_criticality():
    props, _ = _proportions("resource.attributes.criticality_code")
    for code, want in dist.CRITICALITY.items():
        assert abs(props.get(code, 0) - want) <= TOL, (code, props.get(code), want)


def test_http_status_on_http_sourcetype():
    props, _ = _proportions("log.status", n=100_000, sourcetype="json-http")
    for code, want in dist.HTTP_STATUS.items():
        assert abs(props.get(code, 0) - want) <= TOL, (code, props.get(code), want)


def test_severity_number_bands():
    for doc in generator.generate(20_000, seed=11):
        lo, hi = dist.SEVERITY_NUMBER_BANDS[doc["severityText"]]
        assert lo <= doc["severityNumber"] <= hi


def test_timestamp_in_window():
    for doc in generator.generate(20_000, seed=11):
        assert dist.WINDOW_START_MS <= doc["@timestamp"] < dist.ANCHOR_MS


def test_determinism():
    a = list(generator.generate(500, seed=99, sourcetype="kv"))
    b = list(generator.generate(500, seed=99, sourcetype="kv"))
    assert a == b


def test_service_zipf_is_skewed():
    _, c = _proportions("resource.attributes.service.name")
    top = c.most_common(1)[0][1] / N
    assert top > 0.05, top                        # svc-alpha-000 ~9%
    assert len(c) <= dist.SERVICE_CARDINALITY


def test_per_format_shape():
    # json-http must carry log.status/method; json-spring carries log.log.logger
    http = next(generator.generate(1, seed=1, sourcetype="json-http"))
    assert get_path(http, "log.status") in dist.HTTP_STATUS
    assert get_path(http, "log.method")
    spring = next(generator.generate(1, seed=1, sourcetype="json-spring"))
    assert get_path(spring, "log.log.logger")
    assert get_path(spring, "log.process.thread.name")


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print("PASS %s" % t.__name__)
        except AssertionError as e:
            failed += 1
            print("FAIL %s: %s" % (t.__name__, e))
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return failed


if __name__ == "__main__":
    import sys
    sys.exit(1 if _run() else 0)
