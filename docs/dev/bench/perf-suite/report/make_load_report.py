#!/usr/bin/env python3
"""Render a Load-pillar results.json into report.md (plan §2.2 deliverables).

Emits: run header, (1) concurrency-ladder table, (2) latency-vs-concurrency per
category [p50/p95], (3) stress-ramp summary [breaking point + metric that broke
first], (4) sustained per-minute trend, (5) note on the full cluster-metrics
series carried in results.json (baseline + per-phase pre/post + sampler series).

Usage: python3 report/make_load_report.py results/fidelity-load/load.json [> report.md]
"""
import json
import sys
from collections import OrderedDict


def _f(x, nd=3):
    return "-" if x is None else (("%%.%df" % nd) % x if isinstance(x, float) else str(x))


def main():
    d = json.load(open(sys.argv[1]))
    run = d.get("run", {})
    out = []
    out.append("# PPL Load Report — steady-state under concurrency (plan §2.2)\n")
    out.append("| Field | Value |\n| --- | --- |")
    for k in ("run_id", "host", "tier", "git_sha", "time_range", "work_size",
              "ramp_work", "ramp_work_size", "ramp_max", "ramp_step", "levels", "seed"):
        if run.get(k) is not None:
            out.append("| %s | %s |" % (k, run[k]))
    out.append("")

    # (1) concurrency ladder
    lad = d.get("l1_ladder") or []
    if lad:
        out.append("## (1) Concurrency ladder\n")
        cols = ["N", "pass %", "err %", "avg s", "p95 s", "max s",
                "peak CPU %", "peak heap %", "peak queue", "Δ rej"]
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + " ---: |" * len(cols))
        for r in lad:
            out.append("| %d | %.0f | %.0f | %s | %s | %s | %s | %s | %s | %s |" % (
                r["concurrency"], r["pass_rate"] * 100, r["err_timeout_rate"] * 100,
                _f(r["avg_s"]), _f(r["p95_s"]), _f(r["max_s"]), _f(r["cpu_max_pct"]),
                _f(r["heap_max_pct"]), _f(r["search_queue_peak"]), _f(r["rejected_delta"])))
        out.append("")

        # (2) latency-vs-concurrency per category (p50/p95)
        cats = []
        for r in lad:
            for c in (r.get("by_category") or {}):
                if c not in cats:
                    cats.append(c)
        cats.sort()
        out.append("## (2) Latency vs concurrency — per category (p50 / p95 s)\n")
        hdr = "| Category | " + " | ".join("N=%d" % r["concurrency"] for r in lad) + " |"
        out.append(hdr)
        out.append("| --- |" + " ---: |" * len(lad))
        for c in cats:
            cells = []
            for r in lad:
                bc = (r.get("by_category") or {}).get(c)
                cells.append("%s / %s" % (_f(bc["p50_s"]), _f(bc["p95_s"])) if bc else "-")
            out.append("| %s | %s |" % (c, " | ".join(cells)))
        out.append("\n_Cell = p50 / p95 seconds. The category whose p95 climbs first is the "
                   "first to degrade under load._\n")

    # (3) stress-ramp summary
    ramp = d.get("l2_ramp")
    if ramp:
        out.append("## (3) Stress-ramp summary\n")
        bp = ramp.get("breaking_point")
        out.append("- **Breaking point:** %s (trigger: %s)"
                   % ("N=%d" % bp if bp else "not reached within ramp", ramp.get("break_trigger") or "-"))
        out.append("- **First metric to saturate:** %s" % (ramp.get("first_metric") or "none"))
        onset = ramp.get("saturation_onset") or {}
        if onset:
            out.append("- **Saturation onset (concurrency at first crossing):** %s"
                       % ", ".join("%s@N=%d" % (k, v) for k, v in sorted(onset.items(), key=lambda kv: kv[1])))
        out.append("- **Ramp slice:** %s (%d queries, %ss/rung, seed %s)"
                   % (run.get("ramp_work"), ramp.get("pool_size", 0),
                      ramp.get("rung_seconds"), ramp.get("seed")))
        out.append("")
        out.append("| N | pass % | err % | avg s | p95 s | peak CPU % | peak heap % | peak queue | Δ rej |")
        out.append("|" + " ---: |" * 9)
        for r in ramp.get("rungs") or []:
            out.append("| %d | %.0f | %.0f | %s | %s | %s | %s | %s | %s |" % (
                r["concurrency"], r["pass_rate"] * 100, r["err_timeout_rate"] * 100,
                _f(r["avg_s"]), _f(r["p95_s"]), _f(r["cpu_max_pct"]), _f(r["heap_max_pct"]),
                _f(r["search_queue_peak"]), _f(r["rejected_delta"])))
        # error-type breakdown at the breaking rung, if any
        brk = next((r for r in (ramp.get("rungs") or []) if r["concurrency"] == bp), None)
        if brk and brk.get("err_types"):
            out.append("\n_Error types at breaking rung (N=%d): %s_" % (bp, brk["err_types"]))
        out.append("")

    # (4) sustained per-minute trend
    sus = d.get("l3_sustained")
    if sus:
        out.append("## (4) Sustained load — per-minute trend (N=%d, %ds)\n"
                   % (sus["concurrency"], sus["duration_s"]))
        out.append("- pass %.0f%% · latency drift %s%% · heap growth %s%% · %d requests"
                   % (sus["pass_rate"] * 100, _f(sus["latency_drift_pct"]),
                      _f(sus["heap_growth_pct"]), sus["n"]))
        out.append("")
        out.append("| minute | reqs | p50 s | p95 s | heap % | CPU % |")
        out.append("|" + " ---: |" * 6)
        for t in sus.get("trend") or []:
            out.append("| %d | %d | %s | %s | %s | %s |" % (
                t["minute"], t["n"], _f(t["p50_s"]), _f(t["p95_s"]),
                _f(t["heap_max_pct"]), _f(t["cpu_max_pct"])))
        out.append("")

    # (5) series note
    nseries = sum(len(p.get("series") or []) for p in (lad or []))
    nseries += sum(len(r.get("series") or []) for r in ((ramp or {}).get("rungs") or []))
    nseries += len((sus or {}).get("series") or [])
    out.append("## (5) Cluster-metrics time series\n")
    out.append("Full timestamped series attached to results.json: baseline + final "
               "snapshots, per-phase pre/post, and %d sampler samples across all phases. "
               "Peak CPU/heap/queue and Δ rejections in the tables above are computed "
               "from this series (§4.3 exit criteria)." % nseries)
    print("\n".join(out))


if __name__ == "__main__":
    main()
