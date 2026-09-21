#!/usr/bin/env python3
"""Render a Perf-pillar results.json into report.md (plan §2.1 deliverables).

Emits: run header, verdict distribution, (1) per-query latency curve table
[p95 per range], (2) per-format aggregate [mean p95 by body format], (3)
known-slow sheet, (4) wide-range 1d->7d movers, per-command p95 table, and (5)
cluster-metrics snapshots (baseline/mid/final + deltas). Unsupported-on-build
commands are noted if present in the run payload.

Usage: python3 report/make_report.py results/fidelity-1d/perf.json [> report.md]
"""
import json
import statistics
import sys
from collections import defaultdict, Counter, OrderedDict

RANGES = ["5m", "15m", "1h", "1d", "3d", "7d"]


def _fmt(x, nd=3):
    return "-" if x is None else (("%%.%df" % nd) % x if isinstance(x, float) else str(x))


def fmt_of(source):
    """Body-format label from an index name (mock-json-dd -> json-dd)."""
    return source.replace("mock-", "") if source else source


def main():
    data = json.load(open(sys.argv[1]))
    run = data.get("run", {})
    perf = data.get("perf", [])
    cm = data.get("cluster_metrics", {})
    out = []

    out.append("# PPL Perf Report — per-query latency isolation (plan §2.1)\n")
    out.append("| Field | Value |\n| --- | --- |")
    for k in ("run_id", "host", "tier", "git_sha", "reps", "warmup", "time_ranges", "loaded_docs"):
        if k in run:
            out.append("| %s | %s |" % (k, run[k]))
    out.append("| templates | %d | " % len({r["id"] for r in perf}))
    out.append("| measured points | %d |" % len(perf))
    out.append("")

    vc = Counter(r["verdict"] for r in perf)
    out.append("## Latency verdicts\n")
    out.append("| Verdict | Count |\n| --- | ---: |")
    for v in ("FAST", "ACCEPTABLE", "SLOW", "TIMEOUT", "ERROR"):
        if vc.get(v):
            out.append("| %s | %d |" % (v, vc[v]))
    out.append("")

    # index p95 by (id, range)
    p95 = {(r["id"], r["time_range"]): r["p95_s"] for r in perf}
    meta = {r["id"]: r for r in perf}          # any row per id, for category/source/known_slow
    ids_by_group = defaultdict(list)
    for i in sorted(meta):
        ids_by_group[meta[i]["category"]].append(i)

    # (1) per-query latency curve — p95 per range
    out.append("## (1) Per-query latency curve — p95 seconds per time range\n")
    hdr = "| Query | group | " + " | ".join(RANGES) + " |"
    out.append(hdr + "\n| " + " --- |" * (len(RANGES) + 2))
    ordered = ["command", "format", "scenario"] + [g for g in sorted(ids_by_group)
                                                    if g not in ("command", "format", "scenario")]
    for grp in ordered:
        for i in ids_by_group.get(grp, []):
            cells = [_fmt(p95.get((i, tr))) for tr in RANGES]
            out.append("| %s | %s | %s |" % (i, grp, " | ".join(cells)))
    out.append("")

    # (2) per-format aggregate — mean p95 by body format (format-probe rows only)
    fmt_rows = [r for r in perf if r["category"] == "format"]
    if fmt_rows:
        by_fmt_probe = defaultdict(list)       # (format, probe) -> [p95...]
        by_fmt = defaultdict(list)
        for r in fmt_rows:
            probe = r["id"].split("_")[1]      # fmt_<probe>_<index>
            f = fmt_of(r["source"])
            by_fmt_probe[(f, probe)].append(r["p95_s"])
            by_fmt[f].append(r["p95_s"])
        probes = sorted({p for _, p in by_fmt_probe})
        out.append("## (2) Per-format aggregate — mean p95 (s) by body format\n")
        out.append("| Format | " + " | ".join(probes) + " | overall |")
        out.append("| --- |" + " ---: |" * (len(probes) + 1))
        for f in sorted(by_fmt):
            cells = [_fmt(statistics.mean(by_fmt_probe[(f, p)])) if (f, p) in by_fmt_probe else "-"
                     for p in probes]
            out.append("| %s | %s | %s |" % (f, " | ".join(cells),
                                             _fmt(statistics.mean(by_fmt[f]))))
        out.append("\n_Probes: sev=count-by-severity, pod=count-by-pod (high-card), "
                   "rex=rex-on-body, scan=filtered scan. Mean over all ranges._\n")

    # per-command p95 (command axis) at 1h and 1d
    cmd_rows = [r for r in perf if r["category"] == "command"]
    if cmd_rows:
        out.append("## Per-command p95 (s) — command axis\n")
        out.append("| Command | 5m | 15m | 1h | 1d | 3d | 7d | known_slow |")
        out.append("| --- |" + " ---: |" * 6 + " --- |")
        for i in ids_by_group.get("command", []):
            cmd = i[4:]
            cells = [_fmt(p95.get((i, tr))) for tr in RANGES]
            out.append("| %s | %s | %s |" % (cmd, " | ".join(cells), meta[i]["known_slow"]))
        out.append("")

    # (3) known-slow sheet
    ks = sorted([r for r in perf if r["known_slow"]], key=lambda z: -z["p95_s"])
    if ks:
        out.append("## (3) Known-slow sheet — p95 seconds\n")
        out.append("| Query | range | p95 | max | verdict |\n| --- | --- | ---: | ---: | --- |")
        for r in ks[:40]:
            out.append("| %s | %s | %s | %s | %s |"
                       % (r["id"], r["time_range"], _fmt(r["p95_s"]), _fmt(r.get("max_s")), r["verdict"]))
        out.append("")

    # (4) wide-range movers — 1d -> 7d
    out.append("## (4) Wide-range movers — p95 growth 1d -> 7d\n")
    out.append("| Query | 1d | 3d | 7d | 7d/1d |\n| --- | ---: | ---: | ---: | ---: |")
    movers = []
    for i in sorted(meta):
        d1, d7 = p95.get((i, "1d")), p95.get((i, "7d"))
        if d1 and d7:
            movers.append((d7 / d1 if d1 else 0, i, d1, p95.get((i, "3d")), d7))
    for ratio, i, d1, d3, d7 in sorted(movers, reverse=True)[:15]:
        out.append("| %s | %s | %s | %s | %.1fx |" % (i, _fmt(d1), _fmt(d3), _fmt(d7), ratio))
    out.append("")

    # errors, if any (unsupported / failing)
    errs = [r for r in perf if r["verdict"] == "ERROR"]
    if errs:
        out.append("## Errors (verdict=ERROR)\n")
        out.append("| Query | range | err_types |\n| --- | --- | --- |")
        for r in sorted(errs, key=lambda z: z["id"]):
            out.append("| %s | %s | %s |" % (r["id"], r["time_range"], ",".join(r.get("err_types") or [])))
        out.append("")
    if run.get("unsupported_commands"):
        out.append("_Commands documented but rejected by this build's grammar "
                   "(excluded from the run): %s._\n" % ", ".join(run["unsupported_commands"]))

    # (5) cluster-metrics snapshots
    out.append("## (5) Cluster metrics — baseline / mid-run / final\n")
    keys = ("cluster_status", "cpu_max_pct", "heap_max_pct", "search_active",
            "search_queue", "search_rejected", "old_gc_ms")
    out.append("| Phase | " + " | ".join(keys) + " |")
    out.append("| --- |" + " ---: |" * len(keys))
    def snaprow(label, snap):
        return "| %s | %s |" % (label, " | ".join(_fmt(snap.get(k)) for k in keys))
    if cm.get("baseline"):
        out.append(snaprow("baseline", cm["baseline"]))
    for j, s in enumerate(cm.get("mid_run") or []):
        out.append(snaprow("mid-%d" % j, s))
    if cm.get("final"):
        out.append(snaprow("final", cm["final"]))
    out.append("")
    if cm.get("deltas"):
        out.append("Deltas (post-pre): " + ", ".join("%s=%s" % (k, _fmt(v))
                                                      for k, v in cm["deltas"].items()))

    print("\n".join(out))


if __name__ == "__main__":
    main()
