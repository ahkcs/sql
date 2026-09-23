#!/usr/bin/env python3
"""Workload-management policy (plan §3.3) — provisioning, mode switching, stats.

Loads the canonical policy: two workload groups, two users + roles, and two
principal-based rules routing each role to its group. Used by U7 (noisy-neighbor
isolation), which runs the same scenario with the policy off and on.

API surface (verified against OpenSearch core `main`):

    PUT  _wlm/workload_group        {"name","resiliency_mode","resource_limits":{"cpu","memory"}}
    GET  _wlm/workload_group        list (carries the generated group `_id`)
    GET  _wlm/stats                 per-node -> workload_groups -> total_completions/_rejections/_cancellations
    PUT  _rules/workload_group      {"description","principal":{"role":[...]},"workload_group":"<id>"}
    PUT  _cluster/settings          persistent wlm.workload_group.mode = enabled|monitor_only|disabled

Naming: OpenSearch >= 3.1 uses `workload_group`; 2.18-3.0 called the same thing
`query_group`. `paths()` probes and returns whichever the cluster answers on.

Available on Amazon OpenSearch Service (verified on a 3.5 domain 2026-09-18:
`_wlm/workload_group`, `_wlm/stats` and `_rules/workload_group` all answer, and
`wlm.workload_group.mode` is accepted by `_cluster/settings`). The AWS
"supported operations" doc page omits these endpoints but is stale for 3.5.
Tier 1 works too, with the security plugin enabled so the two users exist.

Plan mapping: §3.3 says "priority high/normal", which is not a WLM field. The
equivalent knob is `resiliency_mode`: `dashboards` is `soft` (may burst above
its limit when the cluster is idle), `adhoc` is `enforced` (gets rejected /
cancelled once it exceeds its limit) — that is what makes U7's 429 testable.

Usage:
    python3 -m suite.wlm --host https://localhost:9200 --auth admin:PW --provision
    python3 -m suite.wlm --host ... --auth ... --mode enabled|disabled|monitor_only
    python3 -m suite.wlm --host ... --auth ... --show
"""
import argparse
import json

from . import identities

GROUPS = [
    {"name": "dashboards", "resiliency_mode": "soft",
     "resource_limits": {"cpu": 0.6, "memory": 0.6}},
    {"name": "adhoc", "resiliency_mode": "enforced",
     "resource_limits": {"cpu": 0.3, "memory": 0.3}},
]

# (identity, security role, workload group) — plan §3.3
PROFILES = [("dash_user", "dashboards_role", "dashboards"),
            ("adhoc_user", "adhoc_role", "adhoc")]

# PPL needs the cluster-level PPL action plus read + mapping access on mock-*.
ROLE_BODY = {
    "cluster_permissions": ["cluster:admin/opensearch/ppl", "cluster_composite_ops_ro",
                            "cluster:monitor/health", "cluster:monitor/nodes/stats"],
    "index_permissions": [{"index_patterns": ["mock-*"],
                           "allowed_actions": ["read", "indices:admin/mappings/get",
                                               "indices:admin/mappings/fields/get*",
                                               "indices:monitor/settings/get"]}],
}

MODES = ("enabled", "monitor_only", "disabled")


def paths(http):
    """Return (wlm_group_path, rules_path, mode_setting) for this cluster, or None
    if workload management is not exposed (managed service, or plugin absent)."""
    for name in ("workload_group", "query_group"):
        s, _ = http("GET", "/_wlm/%s" % name)
        if s == 200:
            return ("/_wlm/%s" % name, "/_rules/%s" % name, "wlm.%s.mode" % name)
    return None


def available(http):
    return paths(http) is not None


def group_ids(http, group_path):
    """{group name: group _id} — rules reference the id, not the name."""
    s, body = http("GET", group_path)
    if s != 200:
        return {}
    j = json.loads(body)
    groups = j.get("workload_groups") or j.get("query_groups") or []
    return {g["name"]: g.get("_id", g.get("id")) for g in groups}


def set_mode(http, mode, setting="wlm.workload_group.mode"):
    """Flip the policy off/on for U7's two-phase comparison."""
    if mode not in MODES:
        raise SystemExit("mode must be one of %s" % (MODES,))
    s, body = http("PUT", "/_cluster/settings",
                   json.dumps({"persistent": {setting: mode}}))
    return s == 200, body


def stats(http):
    """Per-group counters summed across nodes: {group_id: {completions, rejections,
    cancellations}}. Raw counters are monotonic, so only deltas are meaningful."""
    s, body = http("GET", "/_wlm/stats")
    if s != 200:
        return {}
    out = {}
    for node in json.loads(body).values():
        if not isinstance(node, dict):
            continue
        for gid, g in (node.get("workload_groups") or {}).items():
            acc = out.setdefault(gid, {"completions": 0, "rejections": 0, "cancellations": 0})
            acc["completions"] += g.get("total_completions", 0)
            acc["rejections"] += g.get("total_rejections", 0)
            acc["cancellations"] += g.get("total_cancellations", 0)
    return out


def delta(pre, post):
    """post - pre per group (§4.4 U7 gates on Δ rejections, not the raw counter)."""
    out = {}
    for gid in set(pre) | set(post):
        a, b = pre.get(gid, {}), post.get(gid, {})
        out[gid] = {k: b.get(k, 0) - a.get(k, 0)
                    for k in ("completions", "rejections", "cancellations")}
    return out


def provision(http, group_path, rules_path, mode_setting, passwords, verbose=True):
    """Idempotent load of the §3.3 policy. `passwords`: {identity: password}.
    Returns a report dict; every step records its HTTP status so a partial
    provision is visible rather than silent.

    Mode is enabled FIRST: creating a workload group while
    `wlm.workload_group.mode` is `disabled` fails with a 500, which silently left
    `group_ids` empty and skipped every rule.

    GROUPS must also keep total cpu and total memory <= 1.0 across all groups, or
    the create is rejected with "Total resource allocation for <res> will go above
    the max limit of 1.0" -- including any groups left over from earlier runs.
    """
    rep = {"groups": {}, "users": {}, "roles": {}, "rolesmappings": {}, "rules": {}}

    ok, body = set_mode(http, "enabled", mode_setting)
    rep["mode_enabled"] = ok if ok else body[:200]

    for g in GROUPS:
        s, body = http("PUT", group_path, json.dumps(g))
        if s != 200 and "exists" in body:          # already loaded -> update limits
            s, body = http("PUT", "%s/%s" % (group_path, g["name"]),
                           json.dumps({k: v for k, v in g.items() if k != "name"}))
        rep["groups"][g["name"]] = s

    ids = group_ids(http, group_path)
    rep["group_ids"] = ids

    for user, role, group in PROFILES:
        pw = passwords.get(user)
        if pw:
            s, _ = http("PUT", "/_plugins/_security/api/internalusers/%s" % user,
                        json.dumps({"password": pw}))
            rep["users"][user] = s
        else:
            rep["users"][user] = "skipped (no password; set %s)" % identities.ENV_BY_NAME[user]
        s, _ = http("PUT", "/_plugins/_security/api/roles/%s" % role, json.dumps(ROLE_BODY))
        rep["roles"][role] = s
        s, _ = http("PUT", "/_plugins/_security/api/rolesmapping/%s" % role,
                    json.dumps({"users": [user]}))
        rep["rolesmappings"][role] = s

        gid = ids.get(group)
        if gid:
            s, body = http("PUT", rules_path, json.dumps({
                "description": "route %s -> %s workload group (plan §3.3)" % (role, group),
                "principal": {"role": [role]},
                "workload_group": gid}))
            rep["rules"][role] = s if s == 200 else "%s %s" % (s, body[:200])
        else:
            rep["rules"][role] = "skipped (no id for group %r)" % group

    if verbose:
        print(json.dumps(rep, indent=2))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--auth", help="admin user:pass (default: --as-user admin from env)")
    ap.add_argument("--as-user", dest="as_user", default="admin")
    ap.add_argument("--provision", action="store_true", help="load the §3.3 policy")
    ap.add_argument("--mode", choices=MODES, help="flip wlm.<group>.mode")
    ap.add_argument("--show", action="store_true", help="print groups + stats")
    args = ap.parse_args()

    from .runner import make_http
    auth = args.auth or identities.auth_for(args.as_user, None)
    http = make_http(args.host, auth)

    p = paths(http)
    if p is None:
        raise SystemExit(
            "workload management not exposed by %s.\n"
            "Amazon OpenSearch Service does not support _wlm / _rules; run U7 on Tier 1\n"
            "(infra/local, security plugin enabled)." % args.host)
    group_path, rules_path, mode_setting = p

    if args.provision:
        pws = {}
        for user, _, _ in PROFILES:
            u, pw = identities.split(identities.auth_for(user, ""))
            if pw:
                pws[u or user] = pw
        provision(http, group_path, rules_path, mode_setting, pws)
    if args.mode:
        ok, body = set_mode(http, args.mode, mode_setting)
        print("mode=%s ok=%s %s" % (args.mode, ok, "" if ok else body[:200]))
    if args.show or not (args.provision or args.mode):
        print("groups: %s" % json.dumps(group_ids(http, group_path)))
        print("stats:  %s" % json.dumps(stats(http), indent=2))


if __name__ == "__main__":
    main()
