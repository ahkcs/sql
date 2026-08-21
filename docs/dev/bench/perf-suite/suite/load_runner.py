#!/usr/bin/env python3
"""Load pillar (plan §2.2 / L1-L3): steady-state cluster behaviour under concurrency.

L1 concurrency ladder (N in {5,10,20}) · L2 stress ramp (find breaking point) ·
L3 sustained load. Concurrency via threads (HTTP is I/O-bound). A background
Sampler polls cluster metrics so we capture peak CPU/heap/search-queue and the
rejections delta that §4.3 gates on.

Usage (sandbox validation, small):
  python3 -m suite.load_runner --host https://EP --auth admin:PW \
      --tests l1,l2,l3 --levels 2,4 --ramp-max 8 --duration 60 --out results/load.json
Full (Tier-2):
  python3 -m suite.load_runner --host https://EP --auth admin:PW --tests l1,l2,l3
"""
import argparse
import json
import os
import random
import statistics
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import catalogue, metrics, verdicts
from .runner import make_http, pct, run_ppl


class Sampler(threading.Thread):
    """Polls cluster metrics on an interval during a load phase."""

    def __init__(self, http, interval=3.0):
        super().__init__(daemon=True)
        self.http, self.interval = http, interval
        self.samples, self._stopevt = [], threading.Event()

    def run(self):
        while not self._stopevt.is_set():
            self.samples.append(metrics.snapshot(self.http))
            self._stopevt.wait(self.interval)

    def stop(self):
        self._stopevt.set()
        self.join(timeout=self.interval * 3)

    def peaks(self):
        def mx(k):
            vals = [s[k] for s in self.samples if s.get(k) is not None]
            return max(vals) if vals else None
        return {"cpu_max_pct": mx("cpu_max_pct"), "heap_max_pct": mx("heap_max_pct"),
                "search_queue_peak": mx("search_queue")}


def _stats(recs):
    lat = [r["s"] for r in recs]
    ok = sum(1 for r in recs if r["ok"])
    n = len(recs) or 1
    errtimeout = sum(1 for r in recs if not r["ok"] or r["s"] >= verdicts.TIMEOUT_S)
    return {"n": len(recs), "ok": ok, "pass_rate": round(ok / n, 4),
            "err_timeout_rate": round(errtimeout / n, 4),
            "avg_s": round(statistics.mean(lat), 3) if lat else None,
            "p95_s": round(pct(lat, 95), 3) if lat else None,
            "max_s": round(max(lat), 3) if lat else None}


def _run_pass(http, work, concurrency):
    """One pass over `work` with `concurrency` threads."""
    def one(item):
        r = run_ppl(http, item["ppl"])
        return {"category": item["category"], "s": r["s"], "ok": r["ok"], "err": r["err"]}
    recs = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for fut in as_completed([ex.submit(one, w) for w in work]):
            recs.append(fut.result())
    return recs


def _measured(http, work, concurrency):
    s = Sampler(http)
    pre = metrics.snapshot(http)
    s.start()
    recs = _run_pass(http, work, concurrency)
    s.stop()
    post = metrics.snapshot(http)
    out = _stats(recs)
    out.update(concurrency=concurrency, **s.peaks(),
               rejected_delta=metrics.delta(pre, post)["search_rejected_delta"])
    return out


def l1_ladder(http, work, levels):
    return [_measured(http, work, n) for n in levels]


def l2_ramp(http, work, ramp_max, sample):
    rungs, breaking = [], None
    for n in range(5, ramp_max + 1, 5):
        w = random.sample(work, min(sample, len(work)))
        r = _measured(http, w, n)
        rungs.append(r)
        if breaking is None and (r["err_timeout_rate"] > 0.30 or (r["avg_s"] or 0) > 60):
            breaking = n
    return {"rungs": rungs, "breaking_point": breaking}


def l3_sustained(http, work, concurrency, duration_s):
    recs, lock, end = [], threading.Lock(), time.time() + duration_s
    s = Sampler(http, interval=5.0)
    s.start()

    def loop():
        while time.time() < end:
            r = run_ppl(http, random.choice(work)["ppl"])
            with lock:
                recs.append({"t": time.time(), "s": r["s"], "ok": r["ok"]})
    threads = [threading.Thread(target=loop, daemon=True) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    s.stop()
    # drift: first-third avg vs last-third avg
    recs.sort(key=lambda r: r["t"])
    third = max(1, len(recs) // 3)
    first = statistics.mean(r["s"] for r in recs[:third])
    last = statistics.mean(r["s"] for r in recs[-third:])
    heaps = [x["heap_max_pct"] for x in s.samples if x.get("heap_max_pct") is not None]
    return {"concurrency": concurrency, "duration_s": duration_s, **_stats(recs),
            "latency_drift_pct": round((last - first) / first * 100, 1) if first else None,
            "heap_growth_pct": round(heaps[-1] - heaps[0], 1) if len(heaps) > 1 else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--auth")
    ap.add_argument("--tests", default="l1,l2,l3")
    ap.add_argument("--levels", default="5,10,20")
    ap.add_argument("--ramp-max", type=int, default=50)
    ap.add_argument("--ramp-sample", type=int, default=30)
    ap.add_argument("--sustained-n", type=int, default=10)
    ap.add_argument("--duration", type=int, default=1800, help="L3 seconds (default 30m)")
    ap.add_argument("--time-range", default="1h")
    ap.add_argument("--out", default="results/load.json")
    args = ap.parse_args()

    http = make_http(args.host, args.auth)
    work = [{"id": q.id, "category": q.category, "ppl": catalogue.full_query(q, args.time_range)}
            for q in catalogue.build_catalogue()]
    tests = set(args.tests.split(","))
    result = {"host": args.host, "time_range": args.time_range, "work_size": len(work)}

    if "l1" in tests:
        result["l1_ladder"] = l1_ladder(http, work, [int(x) for x in args.levels.split(",")])
        for r in result["l1_ladder"]:
            print("L1 N=%-3d pass=%.0f%% avg=%ss p95=%ss cpu=%s heap=%s queue=%s rej_d=%s"
                  % (r["concurrency"], r["pass_rate"] * 100, r["avg_s"], r["p95_s"],
                     r["cpu_max_pct"], r["heap_max_pct"], r["search_queue_peak"], r["rejected_delta"]))
    if "l2" in tests:
        result["l2_ramp"] = l2_ramp(http, work, args.ramp_max, args.ramp_sample)
        print("L2 breaking_point=%s" % result["l2_ramp"]["breaking_point"])
    if "l3" in tests:
        result["l3_sustained"] = l3_sustained(http, work, args.sustained_n, args.duration)
        r = result["l3_sustained"]
        print("L3 N=%d %ds: pass=%.0f%% drift=%s%% heap_growth=%s%%"
              % (r["concurrency"], r["duration_s"], r["pass_rate"] * 100,
                 r["latency_drift_pct"], r["heap_growth_pct"]))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
