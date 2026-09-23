#!/usr/bin/env python3
"""Render a Use-case results.json into report.md (plan §2.3 deliverables).

Emits: run header, (1) per-scenario verdict cards, (2) U1 variant x index-pattern
table, (3) U2 per-refresh trend, (4) U3 step chart with missed-target markers,
(5) U4 cadence report, (6) U5 per-user vs solo baseline, (7) U6 latency curve,
(8) U7 WLM off/on comparison with per-group deltas, (9) cluster-metrics note.

Usage: python3 report/make_usecase_report.py results/usecase/usecase.json [> report.md]
"""
import json
import sys


def _f(x, nd=3):
    return "-" if x is None else (("%%.%df" % nd) % x if isinstance(x, float) else str(x))


def bar(v, hi, width=28):
    if not v or not hi:
        return ""
    return "#" * max(1, int(round(v / hi * width)))


def main():
    d = json.load(open(sys.argv[1]))
    run = d.get("run", {})
    res = {r.get("id"): r for r in d.get("results", [])}
    out = []

    out.append("# PPL Use-case Report — realistic user scenarios (plan §2.3)\n")
    out.append("| Field | Value |\n| --- | --- |")
    for k in ("run_id", "host", "tier", "git_sha", "cache_mode", "window_step_s",
              "identities", "dashboard_variants", "index_patterns"):
        if run.get(k) is not None:
            out.append("| %s | %s |" % (k, run[k]))
    out.append("")
    if run.get("cache_mode") == "rolling":
        out.append("_Rolling window: each iteration slides a constant-width window back by "
                   "`window_step_s`, so no refresh is served from the shard request cache. "
                   "(A literal `now-<range>` cannot be used — the dataset ends 2026-04-11.)_\n")
    else:
        out.append("_**fixed** cache mode: the window is pinned, so repeats are shard-request-cache "
                   "hits and these numbers are cache-warm, not representative of a live dashboard._\n")

    # (1) verdict cards
    out.append("## (1) Per-scenario verdict cards\n")
    out.append("| Scenario | verdict | median s | p95 s | max s | errors |")
    out.append("|" + " --- |" * 6)
    for k in ("u1", "u2", "u3", "u4", "u5", "u6", "u7"):
        r = res.get(k)
        if not r:
            continue
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            r["scenario"], r.get("verdict"), _f(r.get("median_s")), _f(r.get("p95_s")),
            _f(r.get("max_s")), _f(r.get("errors"))))
    out.append("\nUser-facing verdicts: GOOD <5s · ACCEPTABLE 5-10s · POOR >10s.\n")
    for k in ("u1", "u2", "u3", "u4", "u5", "u6", "u7"):
        if res.get(k, {}).get("reason"):
            out.append("- **%s skipped:** %s" % (k.upper(), res[k]["reason"]))
    out.append("")

    # (2) U1 table
    u1 = res.get("u1")
    if u1 and u1.get("rows"):
        out.append("## (2) U1 dashboard refresh — variant x index pattern\n")
        out.append("| variant | index pattern | panels | wall-clock s | avg panel s | "
                   "slowest panel s | errors | verdict |")
        out.append("|" + " --- |" * 8)
        for r in sorted(u1["rows"], key=lambda z: -z["wall_s"]):
            out.append("| %s | `%s` | %d | %s | %s | %s | %d | %s |" % (
                r["variant"], r["index_pattern"], r["panels"], _f(r["wall_s"]),
                _f(r["avg_panel_s"]), _f(r["slowest_panel_s"]), r["errors"], r["verdict"]))
        out.append("\n_Page load = slowest panel returning, so wall-clock is the user-facing number._\n")

    # (3) U2 trend
    u2 = res.get("u2")
    if u2 and u2.get("series"):
        s = u2["series"]
        hi = max(x["wall_s"] for x in s)
        out.append("## (3) U2 auto-refresh trend — wall-clock per refresh (cadence %ss)\n"
                   % u2.get("cadence_s"))
        out.append("| refresh | t+s | wall s | slowest panel s | errors | |")
        out.append("|" + " --- |" * 6)
        for x in s:
            out.append("| %d | %s | %s | %s | %d | `%s` |" % (
                x["refresh"], _f(x["t_offset_s"], 1), _f(x["wall_s"]),
                _f(x["slowest_panel_s"]), x["errors"], bar(x["wall_s"], hi)))
        first, last = s[0]["wall_s"], s[-1]["wall_s"]
        out.append("\nFirst refresh %ss -> last %ss (%s). %d refreshes, p95 %ss.\n" % (
            _f(first), _f(last),
            "degrading" if last > first * 1.2 else "stable",
            u2.get("refreshes", 0), _f(u2.get("p95_s"))))

    # (4) U3 step chart
    u3 = res.get("u3")
    if u3 and u3.get("steps"):
        hi = max(x["s"] for x in u3["steps"])
        out.append("## (4) U3 investigation session — latency per step\n")
        out.append("| step | action | s | verdict | missed <5s | |")
        out.append("|" + " --- |" * 6)
        for x in u3["steps"]:
            out.append("| %d | %s | %s | %s | %s | `%s` |" % (
                x["step"], x["label"], _f(x["s"]), x["verdict"],
                "**MISS**" if x["missed_target"] else "", bar(x["s"], hi)))
        miss = u3.get("steps_missing_target") or []
        out.append("\n%d of %d steps missed the <5s target%s.\n" % (
            len(miss), len(u3["steps"]), (": " + ", ".join(miss)) if miss else ""))

    # (5) U4 cadence
    u4 = res.get("u4")
    if u4:
        out.append("## (5) U4 alert-rule cadence\n")
        out.append("| cadence s | evaluations | within budget | missed | median s | p95 s | errors |")
        out.append("|" + " --- |" * 7)
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            _f(u4.get("cadence_s")), u4.get("evaluations"), u4.get("within_budget"),
            u4.get("missed"), _f(u4.get("median_s")), _f(u4.get("p95_s")), u4.get("errors")))
        out.append("")

    # (6) U5 per-user vs solo
    u5 = res.get("u5")
    if u5 and u5.get("users"):
        out.append("## (6) U5 multi-user mixed — per user vs solo baseline\n")
        out.append("| user | n | solo median s | mixed median s | median x | "
                   "solo p95 s | mixed p95 s | p95 x | verdict |")
        out.append("|" + " --- |" * 9)
        for k, v in sorted(u5["users"].items()):
            out.append("| %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
                k, v["n"], _f(v.get("solo_median_s")), _f(v["median_s"]),
                _f(v.get("median_degradation_x"), 2), _f(v.get("solo_p95_s")),
                _f(v["p95_s"]), _f(v.get("p95_degradation_x"), 2), v.get("verdict")))
        out.append("\n_x = mixed / solo; >1 means the user degraded under concurrent load._\n")

    # (7) U6 curve
    u6 = res.get("u6")
    if u6 and u6.get("curve"):
        hi = max(c["s"] for c in u6["curve"])
        out.append("## (7) U6 long-range latency curve — same query, widening range\n")
        out.append("| range | s | verdict | |")
        out.append("|" + " --- |" * 4)
        for c in u6["curve"]:
            out.append("| %s | %s | %s | `%s` |" % (c["range"], _f(c["s"]), c["verdict"],
                                                    bar(c["s"], hi)))
        out.append("\nGrowth 1h -> 7d: %sx.\n" % _f(u6.get("growth_1h_to_7d_x"), 1))

    # (8) U7 WLM comparison
    u7 = res.get("u7")
    if u7 and u7.get("phases"):
        ph = u7["phases"]
        out.append("## (8) U7 noisy-neighbor isolation — WLM off vs on\n")
        out.append("| phase | dashboards p95 s | dashboards median s | dash errors | "
                   "adhoc n | adhoc errors | adhoc 429 |")
        out.append("|" + " --- |" * 7)
        for name in ("solo", "wlm_off", "wlm_on"):
            p = ph.get(name)
            if not p:
                continue
            du, au = p["dashboards_user"], p.get("adhoc_user") or {}
            out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                name, _f(du["p95_s"]), _f(du["median_s"]), du["errors"],
                au.get("n", "-"), au.get("errors", "-"), au.get("throttled_429", "-")))
        out.append("")
        out.append("- dashboards-user p95 degradation vs solo: **WLM off %sx -> WLM on %sx**"
                   % (_f(u7.get("dash_degradation_wlm_off"), 2),
                      _f(u7.get("dash_degradation_wlm_on"), 2)))
        out.append("- adhoc group delta (from `_wlm/stats`): `%s`" % u7.get("adhoc_group_delta"))
        if u7.get("gates"):
            out.append("\n| gate | result |\n| --- | --- |")
            for g, v in u7["gates"].items():
                out.append("| %s | %s |" % (g, "PASS" if v else "FAIL"))
        out.append("")

    # (9) metrics
    out.append("## (9) Cluster metrics per scenario\n")
    out.append("| scenario | peak CPU % | peak heap % | peak search queue | Δ rejected | samples |")
    out.append("|" + " --- |" * 6)
    for k in ("u1", "u2", "u3", "u4", "u5", "u6", "u7"):
        r = res.get(k)
        m = (r or {}).get("metrics")
        if not m:
            continue
        pk = m.get("peaks", {})
        out.append("| %s | %s | %s | %s | %s | %d |" % (
            k.upper(), _f(pk.get("cpu_max_pct")), _f(pk.get("heap_max_pct")),
            _f(pk.get("search_queue_peak")),
            _f((m.get("deltas") or {}).get("search_rejected_delta")),
            len(m.get("series") or [])))
    out.append("\nFull timestamped series per scenario (plus pre/post snapshots, and for U7 the "
               "per-group `_wlm/stats` deltas) are attached to results.json.\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
