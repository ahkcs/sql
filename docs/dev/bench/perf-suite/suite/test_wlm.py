#!/usr/bin/env python3
"""WLM policy + U7 validation against a fake cluster.

These cover the off/on comparison logic without a cluster, so the scenario can
be changed safely: group/rule provisioning, the
`workload_group` vs `query_group` naming probe, per-group stats deltas, every
skip path, and a full solo/off/on run whose gates must pass.

Run: python -m suite.test_wlm    (from perf-suite/) -- no deps, no cluster.
Also pytest-compatible (test_* functions).
"""
import json
import time

from . import usecase_runner, wlm


class FakeCluster:
    """Minimal _wlm / _rules / _security / _ppl stub.

    `naming` picks the endpoint spelling; `throttle_when_enabled` makes the ad-hoc
    identity get 429s once wlm mode is `enabled`, which is what U7 gates on.
    """

    def __init__(self, naming="workload_group", has_wlm=True, throttle_when_enabled=True):
        self.naming, self.has_wlm = naming, has_wlm
        self.throttle = throttle_when_enabled
        self.groups, self.rules, self.security = {}, [], {}
        self.mode = "disabled"
        self.counters = {}                       # group id -> completions/rejections
        self.ppl_calls = 0

    def client(self, _host, auth):
        """A make_http-compatible client bound to an identity."""
        user = (auth or "admin:x").split(":")[0]

        def http(method, path, body=None):
            return self._route(method, path, body, user)
        return http

    # -- routing ---------------------------------------------------------------
    def _route(self, method, path, body, user):
        p = path.split("?")[0]
        if p.startswith("/_wlm") or p.startswith("/_rules"):
            if not self.has_wlm or (self.naming not in p and p != "/_wlm/stats"):
                return 400, "no handler found for uri [%s]" % p
        if p == "/_wlm/%s" % self.naming:
            if method == "GET":
                return 200, json.dumps({"%ss" % self.naming: list(self.groups.values())})
            g = json.loads(body)
            gid = "id-%s" % g["name"]
            self.groups[g["name"]] = dict(g, _id=gid)
            self.counters.setdefault(gid, {"completions": 0, "rejections": 0, "cancellations": 0})
            return 200, json.dumps(self.groups[g["name"]])
        if p == "/_wlm/stats":
            if not self.has_wlm:
                return 400, "no handler"
            return 200, json.dumps({"node-1": {"workload_groups": {
                gid: {"total_completions": c["completions"],
                      "total_rejections": c["rejections"],
                      "total_cancellations": c["cancellations"]}
                for gid, c in self.counters.items()}}})
        if p == "/_rules/%s" % self.naming:
            self.rules.append(json.loads(body))
            return 200, "{}"
        if p == "/_cluster/settings":
            self.mode = json.loads(body)["persistent"]["wlm.%s.mode" % self.naming]
            return 200, "{}"
        if p.startswith("/_plugins/_security/api/"):
            self.security[p.rsplit("/api/", 1)[1]] = json.loads(body)
            return 200, "{}"
        if p == "/_plugins/_ppl":
            return self._ppl(user)
        if p == "/_cluster/health":
            return 200, json.dumps({"status": "green", "active_shards": 12})
        return 404, "{}"

    def _ppl(self, user):
        self.ppl_calls += 1
        time.sleep(0.005)                        # give the p95 ratios a stable floor
        gid = "id-adhoc" if user == "adhoc_user" else "id-dashboards"
        c = self.counters.setdefault(gid, {"completions": 0, "rejections": 0, "cancellations": 0})
        if user == "adhoc_user" and self.mode == "enabled" and self.throttle:
            c["rejections"] += 1
            return 429, json.dumps({"error": {"type": "workload_group_rejection"}})
        c["completions"] += 1
        return 200, json.dumps({"schema": [], "datarows": [], "size": 0})


def _provision(fc):
    http = fc.client("h", "admin:pw")
    group_path, rules_path, mode_setting = wlm.paths(http)
    rep = wlm.provision(http, group_path, rules_path, mode_setting,
                        {"dash_user": "d", "adhoc_user": "a"}, verbose=False)
    return http, rep


def test_paths_probes_both_namings():
    assert wlm.paths(FakeCluster(naming="workload_group").client("h", None))[0] \
        == "/_wlm/workload_group"
    assert wlm.paths(FakeCluster(naming="query_group").client("h", None))[0] \
        == "/_wlm/query_group"
    assert wlm.paths(FakeCluster(has_wlm=False).client("h", None)) is None


def test_provision_loads_full_policy():
    fc = FakeCluster()
    _, rep = _provision(fc)
    assert set(fc.groups) == {"dashboards", "adhoc"}, fc.groups
    assert fc.groups["adhoc"]["resiliency_mode"] == "enforced"      # 429s are testable
    assert fc.groups["dashboards"]["resource_limits"] == {"cpu": 0.6, "memory": 0.6}
    assert rep["rules"] == {"dashboards_role": 200, "adhoc_role": 200}, rep["rules"]
    assert [r["workload_group"] for r in fc.rules] == ["id-dashboards", "id-adhoc"]
    assert fc.rules[0]["principal"] == {"role": ["dashboards_role"]}
    for key in ("internalusers/dash_user", "roles/dashboards_role",
                "rolesmapping/dashboards_role", "internalusers/adhoc_user"):
        assert key in fc.security, (key, sorted(fc.security))
    assert fc.mode == "enabled"


def test_provision_skips_users_without_passwords():
    fc = FakeCluster()
    http = fc.client("h", "admin:pw")
    gp, rp, ms = wlm.paths(http)
    rep = wlm.provision(http, gp, rp, ms, {}, verbose=False)
    assert "skipped" in str(rep["users"]["dash_user"]), rep["users"]
    assert "internalusers/dash_user" not in fc.security


def test_stats_delta_sums_nodes():
    fc = FakeCluster()
    http, _ = _provision(fc)
    pre = wlm.stats(http)
    fc.counters["id-adhoc"]["rejections"] += 7
    fc.counters["id-dashboards"]["completions"] += 3
    d = wlm.delta(pre, wlm.stats(http))
    assert d["id-adhoc"]["rejections"] == 7, d
    assert d["id-dashboards"]["completions"] == 3, d
    assert d["id-adhoc"]["completions"] == 0, d


def test_u7_skips_when_wlm_absent():
    fc = FakeCluster(has_wlm=False)
    r = usecase_runner.u7("h", fc.client("h", "admin:pw"), 1, "dash_user:d", "adhoc_user:a",
                          http_factory=fc.client)
    assert r["verdict"] == "SKIPPED" and "_wlm" in r["reason"], r


def test_u7_skips_without_identities():
    fc = FakeCluster()
    _provision(fc)
    r = usecase_runner.u7("h", fc.client("h", "admin:pw"), 1, None, None, http_factory=fc.client)
    assert r["verdict"] == "SKIPPED" and "PPL_DASH_AUTH" in r["reason"], r


def test_u7_skips_when_groups_not_loaded():
    fc = FakeCluster()
    r = usecase_runner.u7("h", fc.client("h", "admin:pw"), 1, "dash_user:d", "adhoc_user:a",
                          http_factory=fc.client)
    assert r["verdict"] == "SKIPPED" and "wlm --provision" in r["reason"], r


def test_u7_three_phases_and_gates():
    fc = FakeCluster()
    admin, _ = _provision(fc)
    r = usecase_runner.u7("h", admin, 0.4, "dash_user:d", "adhoc_user:a", http_factory=fc.client)
    assert set(r["phases"]) == {"solo", "wlm_off", "wlm_on"}, r["phases"]
    assert r["phases"]["solo"]["adhoc_user"] is None            # solo = dashboards only
    assert r["phases"]["wlm_off"]["adhoc_user"]["n"] > 0
    assert r["phases"]["wlm_on"]["adhoc_user"]["throttled_429"] > 0
    assert r["adhoc_group_delta"]["rejections"] > 0
    assert r["gates"]["adhoc_rejections_delta_gt_0"] and r["gates"]["adhoc_not_starved"]
    assert r["gates"]["dash_errors_wlm_on_is_zero"]
    assert r["verdict"] == "PASS", r["gates"]
    assert fc.mode == "enabled"                                 # left on after the run


def test_u7_fails_when_wlm_does_not_throttle():
    """No Δ rejections on `adhoc` means the policy is not doing anything (§4.4)."""
    fc = FakeCluster(throttle_when_enabled=False)
    admin, _ = _provision(fc)
    r = usecase_runner.u7("h", admin, 0.4, "dash_user:d", "adhoc_user:a", http_factory=fc.client)
    assert r["verdict"] == "FAIL" and not r["gates"]["adhoc_rejections_delta_gt_0"], r["gates"]


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
