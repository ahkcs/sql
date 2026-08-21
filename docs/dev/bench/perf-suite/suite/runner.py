#!/usr/bin/env python3
"""Perf-pillar runner (plan §2.1 / P1).

Per query x time-range: 1 warmup + N measured reps, p50/p95/max, latency verdict,
optional correctness vs mock_data.expected, plus baseline/mid/final cluster-metric
snapshots. Writes results.json.

Usage (against the pilot once active):
  EP=$(aws cloudformation describe-stacks --stack-name ppl-perf-tier2-pilot \
        --query "Stacks[0].Outputs[?OutputKey=='DomainEndpoint'].OutputValue" --output text)
  python3 -m suite.runner --host "https://$EP" \
      --auth "admin:$(cat ~/.ppl-perf-tier2-pilot.secret)" --loaded-docs 5000 --out results/pilot.json

  python3 -m suite.runner --list          # print the catalogue, no cluster
"""
import argparse
import base64
import json
import os
import statistics
import time
import urllib.error
import urllib.request

from mock_data import expected
from . import catalogue, metrics, verdicts


def make_http(host, auth):
    hdr = {"Content-Type": "application/json"}
    if auth:
        hdr["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()

    def http(method, path, body=None):
        data = body.encode() if isinstance(body, str) else body
        r = urllib.request.Request(host + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(r, timeout=310) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except Exception as e:  # noqa: BLE001
            return -1, str(e)
    return http


def run_ppl(http, ppl):
    t0 = time.perf_counter()
    status, resp = http("POST", "/_plugins/_ppl", json.dumps({"query": ppl}))
    elapsed = time.perf_counter() - t0
    rows, warn, err, schema, datarows = None, False, None, None, None
    try:
        j = json.loads(resp)
        if status == 200:
            rows = j.get("size", j.get("total"))
            warn = bool(j.get("warnings"))
            schema, datarows = j.get("schema"), j.get("datarows")
        else:
            err = (j.get("error") or {}).get("type") or j.get("type")
    except Exception:  # noqa: BLE001
        pass
    return {"s": elapsed, "status": status, "ok": status == 200, "rows": rows,
            "warn": warn, "err": err, "schema": schema, "datarows": datarows}


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def check_correctness(http, spec, loaded_docs):
    """Run the aggregation unfiltered and compare group counts to expected ground truth."""
    idx, field = spec["index"], spec["field"]
    path = expected.FIELD_PATHS[field]
    r = run_ppl(http, "source=%s | stats count() by %s" % (idx, path))
    if not r["ok"] or r["datarows"] is None:
        return {"verdict": "ERROR", "detail": "status=%s err=%s" % (r["status"], r["err"])}
    names = [c["name"] for c in (r["schema"] or [])]
    try:
        gi = names.index(path)
    except ValueError:
        return {"verdict": "ERROR", "detail": "group col %r not in %s" % (path, names)}
    ci = next((i for i, n in enumerate(names) if n != path), 1 - gi)
    observed = {row[gi]: row[ci] for row in r["datarows"]}
    want = dict(expected.counts_by(idx, field, n=loaded_docs))
    mism = {k: (want.get(k), observed.get(k)) for k in set(want) | set(observed)
            if want.get(k) != observed.get(k)}
    return {"verdict": "PASS" if not mism else "FAIL",
            "groups": len(want), "mismatches": dict(list(mism.items())[:10])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--auth")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--time-ranges", default="5m,15m,1h,1d")
    ap.add_argument("--wide", action="store_true", help="also 3d,7d")
    ap.add_argument("--category", action="append", help="restrict to categories")
    ap.add_argument("--loaded-docs", type=int, default=5000,
                    help="docs loaded per index (must match load.py) for correctness")
    ap.add_argument("--out", default="results/perf.json")
    ap.add_argument("--list", action="store_true", help="print catalogue and exit")
    ap.add_argument("--skip-correctness", action="store_true",
                    help="skip the expected.py re-tally (slow + redundant at full scale)")
    args = ap.parse_args()

    cat = catalogue.build_catalogue()
    if args.category:
        cat = [q for q in cat if q.category in set(args.category)]

    if args.list:
        for q in cat:
            print("[%-14s] %-26s slow=%-5s corr=%-5s  %s"
                  % (q.category, q.id, q.known_slow, bool(q.correctness),
                     catalogue.full_query(q, "1h")))
        print("\n%d query templates across %d categories"
              % (len(cat), len({q.category for q in cat})))
        return
    if not args.host:
        ap.error("--host required (or use --list)")

    trs = args.time_ranges.split(",")
    if args.wide:
        trs += list(catalogue.WIDE_RANGES)
    http = make_http(args.host, args.auth)

    result = {"run": {"host": args.host, "reps": args.reps, "warmup": args.warmup,
                      "time_ranges": trs, "loaded_docs": args.loaded_docs},
              "cluster_metrics": {}, "perf": [], "correctness": []}

    base = metrics.snapshot(http)
    result["cluster_metrics"]["baseline"] = base
    mids, done = [], 0

    # correctness pass (unfiltered) for flagged queries
    for q in cat:
        if q.correctness and not args.skip_correctness:
            cc = check_correctness(http, q.correctness, args.loaded_docs)
            cc.update(id=q.id, **q.correctness)
            result["correctness"].append(cc)
            print("  correctness %-26s %s (%s)" % (q.id, cc["verdict"], cc.get("mismatches", "")))

    # latency sweep
    for q in cat:
        for tr in trs:
            ppl = catalogue.full_query(q, tr)
            for _ in range(args.warmup):
                run_ppl(http, ppl)
            samples, oks, errs = [], 0, set()
            for _ in range(args.reps):
                r = run_ppl(http, ppl)
                samples.append(r["s"])
                oks += r["ok"]
                if r["err"]:
                    errs.add(r["err"])
            ok_all = oks == args.reps
            p95 = pct(samples, 95)
            rec = {"id": q.id, "category": q.category, "source": q.source, "time_range": tr,
                   "known_slow": q.known_slow, "ppl": ppl,
                   "p50_s": round(pct(samples, 50), 3), "p95_s": round(p95, 3),
                   "max_s": round(max(samples), 3), "mean_s": round(statistics.mean(samples), 3),
                   "ok": ok_all, "errors": args.reps - oks, "err_types": sorted(errs),
                   "verdict": verdicts.latency_verdict(p95, ok_all)}
            result["perf"].append(rec)
            done += 1
            if done % 50 == 0:
                mids.append(metrics.snapshot(http))
    result["cluster_metrics"]["mid_run"] = mids
    final = metrics.snapshot(http)
    result["cluster_metrics"]["final"] = final
    result["cluster_metrics"]["deltas"] = metrics.delta(base, final)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    # summary
    from collections import Counter
    vc = Counter(r["verdict"] for r in result["perf"])
    cc = Counter(c["verdict"] for c in result["correctness"])
    print("\n== %d runs: %s ==" % (len(result["perf"]), dict(vc)))
    print("== correctness: %s ==" % dict(cc))
    print("== cluster: status=%s cpu_max=%s heap_max=%s rej_delta=%s ==" % (
        final["cluster_status"], final["cpu_max_pct"], final["heap_max_pct"],
        result["cluster_metrics"]["deltas"]["search_rejected_delta"]))
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
