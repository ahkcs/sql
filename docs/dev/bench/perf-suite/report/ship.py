#!/usr/bin/env python3
"""Ship a finished run to the observability sink (plan §3.4 Tier 2 / §3.5 Tier 1).

Runs only at the end — no partial results are ever published — and is idempotent
by `run_id`: re-shipping the same run overwrites its documents instead of
duplicating them (doc `_id` = "<run_id>:<n>").

Index layout (§3.4): one daily index per pillar,
`ppl-testresults-{perf,load,usecase}-YYYY-MM-DD`, matched by the
`ppl-testresults-*` ISM policy (hot 90 days, then delete).

Row types, all carrying the §3.4 run header (run_id, timestamp, tier, git_sha,
schema_version, wlm_policy_version):
  perf     — one row per query x time range, plus correctness rows
  load     — one row per L1 rung / L2 rung / L3 run
  usecase  — one row per scenario (U1-U7)
  *        — cluster-metric snapshots (baseline / mid_run / final) + deltas

Usage:
  SINK_URL=http://localhost:9201 python3 report/ship.py results/local-perf.json
  python3 report/ship.py results/tier2-team-full/*.json --sink https://SINK --auth admin:PW
  python3 report/ship.py results/perf.json --dry-run        # print rows, no HTTP
  python3 report/ship.py --sink ... --ensure-policy         # ISM only, no rows
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from suite.runner import make_http  # noqa: E402

INDEX_PREFIX = "ppl-testresults"
POLICY_ID = "ppl-testresults-retention"
HOT_DAYS = 90

ISM_POLICY = {
    "policy": {
        "description": "PPL benchmark results: hot %d days, then delete (plan §3.4)" % HOT_DAYS,
        "default_state": "hot",
        "states": [
            {"name": "hot", "actions": [],
             "transitions": [{"state_name": "delete",
                              "conditions": {"min_index_age": "%dd" % HOT_DAYS}}]},
            {"name": "delete", "actions": [{"delete": {}}], "transitions": []},
        ],
        "ism_template": [{"index_patterns": ["%s-*" % INDEX_PREFIX], "priority": 100}],
    }
}


def _header(data, path):
    """Run header, reconstructed for older results files that predate suite/runinfo."""
    run = data.get("run") or {}
    if "run_id" in run:
        keys = ("run_id", "pillar", "timestamp", "host", "tier", "git_sha",
                "schema_version", "wlm_policy_version")
        return {k: run[k] for k in keys if k in run}
    pillar = ("perf" if "perf" in data else
              "load" if any(k.startswith("l") and "_" in k for k in data) else "usecase")
    host = data.get("host") or run.get("host")
    parts = [p for p in (os.path.basename(os.path.dirname(os.path.abspath(path))),
                         os.path.basename(path).rsplit(".", 1)[0]) if p and p != "results"]
    import datetime
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc)
    return {"run_id": "-".join([pillar] + [p for p in parts if p != pillar]),
            "pillar": pillar,
            "timestamp": mtime.isoformat(timespec="seconds"),
            "host": host,
            "tier": "tier2" if ".es.amazonaws.com" in str(host) else "tier1",
            "note": "header backfilled from path + mtime (pre-runinfo results file)"}


def _metric_rows(data):
    cm = data.get("cluster_metrics") or {}
    rows = []
    for phase in ("baseline", "final"):
        if cm.get(phase):
            rows.append({"row_type": "cluster_metrics", "phase": phase, **cm[phase]})
    for i, snap in enumerate(cm.get("mid_run") or []):
        rows.append({"row_type": "cluster_metrics", "phase": "mid_run", "seq": i, **snap})
    if cm.get("deltas"):
        rows.append({"row_type": "cluster_metrics", "phase": "deltas", **cm["deltas"]})
    return rows


def rows_for(data, path):
    """(header, [row, ...]) — one flat doc per measurement."""
    hdr = _header(data, path)
    pillar, rows = hdr["pillar"], []

    if pillar == "perf":
        rows += [{"row_type": "query", **r} for r in data.get("perf", [])]
        rows += [{"row_type": "correctness", **r} for r in data.get("correctness", [])]
    elif pillar == "load":
        rows += [{"row_type": "load_rung", "test": "l1", **r} for r in data.get("l1_ladder", [])]
        l2 = data.get("l2_ramp") or {}
        rows += [{"row_type": "load_rung", "test": "l2",
                  "breaking_point": l2.get("breaking_point"), **r} for r in l2.get("rungs", [])]
        if data.get("l3_sustained"):
            rows.append({"row_type": "load_run", "test": "l3", **data["l3_sustained"]})
    else:
        for r in data.get("results", []):
            row = {"row_type": "scenario", **{k: v for k, v in r.items() if k != "phases"}}
            if "phases" in r:                      # U7: keep the off/on detail as one blob
                row["phases"] = json.dumps(r["phases"])
            rows.append(row)
    rows += _metric_rows(data)
    return hdr, rows


def ship(http, index, hdr, rows, dry_run=False):
    lines = []
    for i, row in enumerate(rows):
        doc = dict(hdr, **row)
        lines.append(json.dumps({"index": {"_index": index, "_id": "%s:%d" % (hdr["run_id"], i)}}))
        lines.append(json.dumps(doc))
    if dry_run:
        print("\n".join(lines))
        return True, "dry-run"
    status, body = http("POST", "/_bulk?refresh=true&filter_path=took,errors",
                        "\n".join(lines) + "\n")
    ok = status == 200 and not json.loads(body).get("errors")
    return ok, body[:400]


def ensure_policy(http):
    status, body = http("GET", "/_plugins/_ism/policies/%s" % POLICY_ID)
    if status == 200:
        return True, "exists"
    status, body = http("PUT", "/_plugins/_ism/policies/%s" % POLICY_ID, json.dumps(ISM_POLICY))
    return status in (200, 201), body[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="results/*.json produced by the runners")
    ap.add_argument("--sink", default=os.environ.get("SINK_URL", "http://localhost:9201"),
                    help="observability sink (env SINK_URL; Tier-1 default is the local one)")
    ap.add_argument("--auth")
    ap.add_argument("--ensure-policy", action="store_true", help="create the ISM retention policy")
    ap.add_argument("--dry-run", action="store_true", help="print bulk body, send nothing")
    args = ap.parse_args()

    http = make_http(args.sink, args.auth)
    if args.ensure_policy and not args.dry_run:
        ok, detail = ensure_policy(http)
        print("ism policy %s: %s (%s)" % (POLICY_ID, "ok" if ok else "FAILED", detail))
        if not ok:
            return 1

    failed = 0
    for path in args.files:
        with open(path) as f:
            data = json.load(f)
        hdr, rows = rows_for(data, path)
        date = (hdr.get("timestamp") or "")[:10] or "undated"
        index = "%s-%s-%s" % (INDEX_PREFIX, hdr["pillar"], date)
        ok, detail = ship(http, index, hdr, rows, args.dry_run)
        failed += 0 if ok else 1
        print("%-40s -> %s  %d rows  run_id=%s  %s"
              % (path, index, len(rows), hdr["run_id"], "ok" if ok else "FAILED: %s" % detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
