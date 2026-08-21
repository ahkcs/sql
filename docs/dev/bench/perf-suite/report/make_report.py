#!/usr/bin/env python3
"""Render a perf results.json into report.md (plan §2.1 deliverables).

Usage: python3 report/make_report.py results/tier2-fraction.json [> report.md]
"""
import json
import statistics
import sys
from collections import Counter, defaultdict


def _fmt(x):
    return "-" if x is None else x


def main():
    data = json.load(open(sys.argv[1]))
    run = data.get("run", {})
    perf = data.get("perf", [])
    corr = data.get("correctness", [])
    cm = data.get("cluster_metrics", {})
    final = cm.get("final", {})
    out = []

    out.append("# PPL Perf Report\n")
    out.append("| Field | Value |")
    out.append("| --- | --- |")
    for k in ("host", "reps", "warmup", "time_ranges", "loaded_docs"):
        if k in run:
            out.append("| %s | %s |" % (k, run[k]))
    out.append("")

    # latency verdict distribution
    vc = Counter(r["verdict"] for r in perf)
    out.append("## Latency verdicts\n")
    out.append("| Verdict | Count |\n| --- | ---: |")
    for v in ("FAST", "ACCEPTABLE", "SLOW", "TIMEOUT", "ERROR"):
        if vc.get(v):
            out.append("| %s | %d |" % (v, vc[v]))
    out.append("")

    # per-category p95 summary (min/median/max across that category's runs)
    bycat = defaultdict(list)
    for r in perf:
        bycat[r["category"]].append(r["p95_s"])
    out.append("## p95 by category (seconds)\n")
    out.append("| Category | runs | min | median | max |\n| --- | ---: | ---: | ---: | ---: |")
    for cat in sorted(bycat):
        xs = sorted(bycat[cat])
        out.append("| %s | %d | %.3f | %.3f | %.3f |"
                   % (cat, len(xs), xs[0], statistics.median(xs), xs[-1]))
    out.append("")

    # slowest queries
    out.append("## Slowest 10 (by p95)\n")
    out.append("| Query | range | p95_s | verdict | known_slow |\n| --- | --- | ---: | --- | --- |")
    for r in sorted(perf, key=lambda z: -z["p95_s"])[:10]:
        out.append("| %s | %s | %.3f | %s | %s |"
                   % (r["id"], r["time_range"], r["p95_s"], r["verdict"], r["known_slow"]))
    out.append("")

    # correctness
    if corr:
        cc = Counter(c["verdict"] for c in corr)
        out.append("## Correctness: %s\n" % dict(cc))
        out.append("| Query | index | field | verdict |\n| --- | --- | --- | --- |")
        for c in corr:
            out.append("| %s | %s | %s | %s |"
                       % (c.get("id"), c.get("index"), c.get("field"), c["verdict"]))
        out.append("")

    # cluster
    out.append("## Cluster metrics (final)\n")
    out.append("| Metric | Value |\n| --- | --- |")
    for k in ("cluster_status", "cpu_max_pct", "heap_max_pct", "search_queue", "active_shards"):
        out.append("| %s | %s |" % (k, _fmt(final.get(k))))
    for k, v in (cm.get("deltas") or {}).items():
        out.append("| %s | %s |" % (k, _fmt(v)))

    print("\n".join(out))


if __name__ == "__main__":
    main()
