#!/usr/bin/env python3
"""Load pillar (plan §2.2 / L1-L3): steady-state cluster behaviour under concurrency.

L1 concurrency ladder (N in {5,10,20}) · L2 stress ramp (find breaking point) ·
L3 sustained load. Concurrency via threads (HTTP is I/O-bound). A background
Sampler polls cluster metrics so we capture the full time series (deliverable 5)
plus peak CPU/heap/search-queue and the rejections delta that §4.3 gates on.

Two load shapes:
  * L1 = one throughput pass over the full catalogue at each N (fixed body of work).
  * L2/L3 = WINDOWED: N worker threads pull from a query pool for a wall-clock
    window, so N requests stay in-flight continuously regardless of pool size.
    (A single pass would cap in-flight at len(pool) — a 27-query heavy slice could
    never reach N=50, defeating force-locate.)

Deliverables emitted (plan §2.2):
  1 concurrency-ladder record per level (pass/avg/p95/err%/peak cpu,heap,queue/rej)
  2 per-CATEGORY p50+p95 at each level (which category degrades first)
  3 stress-ramp breaking point + the metric that saturated first
  4 sustained per-MINUTE latency+heap trend (drift over 30 min)
  5 full cluster-metrics series (timestamped) attached to results.json

L2 uses ONE seeded pool for every rung, so concurrency is the only variable.

Usage (sandbox validation, small):
  python3 -m suite.load_runner --host https://EP --auth admin:PW \
      --tests l1,l2,l3 --levels 2,4 --ramp-max 8 --rung-seconds 20 --duration 60 --out results/load.json
Full (Tier-2, force-locate the break on the heavy slice past N=50):
  python3 -m suite.load_runner --host https://EP --auth admin:PW --tests l1,l2,l3 \
      --ramp-work heavy --ramp-max 100 --ramp-step 5 --rung-seconds 45
"""
import argparse
import json
import os
import random
import statistics
import threading
import time
from collections import Counter, defaultdict

from . import catalogue, identities, metrics, runinfo, verdicts
from .runner import make_http, pct, run_ppl
from concurrent.futures import ThreadPoolExecutor, as_completed

# Whole-result-set ops that trip the query memory breaker on their own at wide
# ranges (per the Perf baseline) — excluded from the "heavy" ramp slice so a break
# is attributable to concurrency, not to a single query that fails regardless of N.
MEM_BREAKER_IDS = {"cmd_eventstats", "cmd_streamstats"}

# §4.3 saturation thresholds, evaluated per rung to find which metric moved first.
HEAP_SAT_PCT, CPU_SAT_PCT = 85, 90


class Sampler(threading.Thread):
    """Polls cluster metrics on an interval during a load phase. Each sample is
    timestamped (`_t`) so it can be binned per-minute (deliverable 4)."""

    def __init__(self, http, interval=3.0):
        super().__init__(daemon=True)
        self.http, self.interval = http, interval
        self.samples, self._stopevt = [], threading.Event()

    def run(self):
        while not self._stopevt.is_set():
            snap = metrics.snapshot(self.http)
            snap["_t"] = time.time()
            self.samples.append(snap)
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


def _agg(recs):
    """Aggregate a phase: overall latency/pass stats, error-type breakdown, and
    per-category p50/p95 (deliverable 2)."""
    lat = [r["s"] for r in recs]
    ok = sum(1 for r in recs if r["ok"])
    n = len(recs) or 1
    errtimeout = sum(1 for r in recs if not r["ok"] or r["s"] >= verdicts.TIMEOUT_S)
    err_types = Counter(r["err"] for r in recs if r.get("err"))
    by_cat, cats = {}, defaultdict(list)
    for r in recs:
        cats[r["category"]].append(r)
    for c, rs in cats.items():
        cl = [x["s"] for x in rs]
        by_cat[c] = {"n": len(rs), "ok": sum(1 for x in rs if x["ok"]),
                     "p50_s": round(pct(cl, 50), 3), "p95_s": round(pct(cl, 95), 3)}
    return {"n": len(recs), "ok": ok, "pass_rate": round(ok / n, 4),
            "err_timeout_rate": round(errtimeout / n, 4),
            "avg_s": round(statistics.mean(lat), 3) if lat else None,
            "p50_s": round(pct(lat, 50), 3) if lat else None,
            "p95_s": round(pct(lat, 95), 3) if lat else None,
            "max_s": round(max(lat), 3) if lat else None,
            "err_types": dict(err_types), "by_category": by_cat}


def _run_pass(http, work, concurrency):
    """One throughput pass over `work` with `concurrency` threads (L1)."""
    def one(item):
        r = run_ppl(http, item["ppl"])
        return {"id": item["id"], "category": item["category"], "t": time.time(),
                "s": r["s"], "ok": r["ok"], "err": r["err"]}
    recs = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for fut in as_completed([ex.submit(one, w) for w in work]):
            recs.append(fut.result())
    return recs


def _run_window(http, pool, concurrency, window_s, seed):
    """`concurrency` worker threads each pull a random query from `pool` and fire
    it back-to-back until `window_s` elapses — holds N requests in-flight (L2/L3)."""
    recs, lock, end = [], threading.Lock(), time.time() + window_s

    def loop(tid):
        rng = random.Random(seed + tid)
        while time.time() < end:
            item = rng.choice(pool)
            r = run_ppl(http, item["ppl"])
            with lock:
                recs.append({"id": item["id"], "category": item["category"], "t": time.time(),
                             "s": r["s"], "ok": r["ok"], "err": r["err"]})
    threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return recs


def _phase(http, concurrency, run_fn):
    """Run run_fn() under a metrics Sampler; return (agg, recs, series, pre, post, t0)."""
    s = Sampler(http)
    pre = metrics.snapshot(http)
    t0 = time.time()
    s.start()
    recs = run_fn()
    s.stop()
    post = metrics.snapshot(http)
    d = metrics.delta(pre, post)
    agg = _agg(recs)
    agg.update(concurrency=concurrency, **s.peaks(),
               rejected_delta=d["search_rejected_delta"], old_gc_ms_delta=d["old_gc_ms_delta"])
    return agg, recs, s.samples, pre, post, t0


def saturation_onset(rungs):
    """Lowest concurrency at which each §4.3 metric first crossed its threshold —
    used to name the metric that broke first (deliverable 3)."""
    onset = {}
    def mark(key, cond, n):
        if key not in onset and cond:
            onset[key] = n
    for r in sorted(rungs, key=lambda z: z["concurrency"]):
        n = r["concurrency"]
        mark("rejections", (r.get("rejected_delta") or 0) > 0, n)
        mark("search_queue", (r.get("search_queue_peak") or 0) > 0, n)
        mark("heap", (r.get("heap_max_pct") or 0) >= HEAP_SAT_PCT, n)
        mark("cpu", (r.get("cpu_max_pct") or 0) >= CPU_SAT_PCT, n)
        mark("errors", (r.get("err_timeout_rate") or 0) > 0, n)
    return onset


def l1_ladder(http, work, levels):
    out = []
    for n in levels:
        agg, _recs, series, pre, post, _ = _phase(http, n, lambda n=n: _run_pass(http, work, n))
        agg.update(series=series, pre=pre, post=post)
        out.append(agg)
    return out


def l2_ramp(http, work, ramp_max, sample, step, rung_seconds, seed):
    """Ramp concurrency over a FIXED seeded pool, windowed per rung. Records the
    first rung to cross §4.3 thresholds and the metric that saturated first."""
    rng = random.Random(seed)
    pool = rng.sample(work, min(sample, len(work)))
    rungs, breaking, trigger = [], None, None
    for n in range(step, ramp_max + 1, step):
        agg, _recs, series, _pre, _post, _ = _phase(
            http, n, lambda n=n: _run_window(http, pool, n, rung_seconds, seed))
        agg["series"] = series
        rungs.append(agg)
        if breaking is None and (agg["err_timeout_rate"] > 0.30 or (agg["avg_s"] or 0) > 60):
            breaking = n
            trigger = "err_timeout>30%" if agg["err_timeout_rate"] > 0.30 else "avg>60s"
        print("  L2 N=%-3d pass=%.0f%% avg=%ss p95=%ss err=%.0f%% cpu=%s heap=%s queue=%s rej_d=%s"
              % (n, agg["pass_rate"] * 100, agg["avg_s"], agg["p95_s"], agg["err_timeout_rate"] * 100,
                 agg["cpu_max_pct"], agg["heap_max_pct"], agg["search_queue_peak"], agg["rejected_delta"]))
    onset = saturation_onset(rungs)
    return {"rungs": rungs, "breaking_point": breaking, "break_trigger": trigger,
            "saturation_onset": onset,
            "first_metric": min(onset, key=onset.get) if onset else None,
            "pool_size": len(pool), "pool_ids": sorted(x["id"] for x in pool),
            "rung_seconds": rung_seconds, "seed": seed}


def l3_sustained(http, work, concurrency, duration_s, seed):
    agg, recs, series, pre, post, t0 = _phase(
        http, concurrency, lambda: _run_window(http, work, concurrency, duration_s, seed))
    recs.sort(key=lambda r: r["t"])

    # per-minute trend (deliverable 4): latency from requests, heap/cpu from sampler
    lat_bins, heap_bins, cpu_bins = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in recs:
        lat_bins[int((r["t"] - t0) // 60)].append(r["s"])
    for x in series:
        m = int((x["_t"] - t0) // 60)
        if x.get("heap_max_pct") is not None:
            heap_bins[m].append(x["heap_max_pct"])
        if x.get("cpu_max_pct") is not None:
            cpu_bins[m].append(x["cpu_max_pct"])
    trend = []
    for m in sorted(set(lat_bins) | set(heap_bins)):
        lat = lat_bins.get(m, [])
        trend.append({"minute": m, "n": len(lat),
                      "p50_s": round(pct(lat, 50), 3) if lat else None,
                      "p95_s": round(pct(lat, 95), 3) if lat else None,
                      "heap_max_pct": max(heap_bins[m]) if heap_bins.get(m) else None,
                      "cpu_max_pct": max(cpu_bins[m]) if cpu_bins.get(m) else None})

    third = max(1, len(recs) // 3)
    first = statistics.mean(r["s"] for r in recs[:third]) if recs else 0
    last = statistics.mean(r["s"] for r in recs[-third:]) if recs else 0
    heaps = [x["heap_max_pct"] for x in series if x.get("heap_max_pct") is not None]
    agg.update(concurrency=concurrency, duration_s=duration_s, trend=trend, series=series,
               pre=pre, post=post,
               latency_drift_pct=round((last - first) / first * 100, 1) if first else None,
               heap_growth_pct=round(heaps[-1] - heaps[0], 1) if len(heaps) > 1 else None)
    return agg


def work_slice(work, mode):
    """full = whole catalogue; slow = known_slow only; heavy = known_slow minus the
    whole-set memory-breakers (individually-passing saturators, for force-locate)."""
    if mode == "full":
        return work
    slow = [w for w in work if w["known_slow"]]
    if mode == "slow":
        return slow
    if mode == "heavy":
        return [w for w in slow if w["id"] not in MEM_BREAKER_IDS]
    raise SystemExit("bad --ramp-work %r (full|slow|heavy)" % mode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--auth")
    ap.add_argument("--as-user", dest="as_user",
                    help="named identity from the environment (suite/identities.py)")
    ap.add_argument("--tests", default="l1,l2,l3")
    ap.add_argument("--levels", default="5,10,20")
    ap.add_argument("--ramp-max", type=int, default=50)
    ap.add_argument("--ramp-step", type=int, default=5)
    ap.add_argument("--ramp-sample", type=int, default=40, help="query-pool size for L2")
    ap.add_argument("--ramp-work", default="full", help="full|slow|heavy (L2 pool)")
    ap.add_argument("--rung-seconds", type=int, default=45, help="wall-clock per L2 rung")
    ap.add_argument("--sustained-n", type=int, default=10)
    ap.add_argument("--duration", type=int, default=1800, help="L3 seconds (default 30m)")
    ap.add_argument("--time-range", default="1h")
    ap.add_argument("--settle-seconds", type=int, default=30,
                    help="idle gap before L2 and L3 so heap recovers and each phase's "
                         "baseline is clean (avoids cross-phase pressure contamination)")
    ap.add_argument("--ramp-time-range", default=None,
                    help="time range for the L2 pool only (default = --time-range); use a wider "
                         "range to make the heavy slice genuinely saturating without dragging "
                         "the eventstats/streamstats memory-breakers into L1/L3")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--req-timeout", type=int, default=120,
                    help="hard per-request timeout (s) so no single query stalls a phase")
    ap.add_argument("--out", default="results/load.json")
    args = ap.parse_args()

    http = make_http(args.host, identities.auth_for(args.as_user, args.auth),
                     timeout=args.req_timeout)
    def build_work(tr):
        return [{"id": q.id, "category": q.category, "known_slow": q.known_slow,
                 "ppl": catalogue.full_query(q, tr)} for q in catalogue.build_catalogue()]
    work = build_work(args.time_range)
    ramp_tr = args.ramp_time_range or args.time_range
    ramp_work = work_slice(build_work(ramp_tr), args.ramp_work)
    tests = set(args.tests.split(","))
    result = {"run": runinfo.header("load", args.host, as_user=args.as_user,
                                    time_range=args.time_range, work_size=len(work),
                                    ramp_work=args.ramp_work, ramp_work_size=len(ramp_work),
                                    ramp_time_range=ramp_tr,
                                    ramp_max=args.ramp_max, ramp_step=args.ramp_step,
                                    rung_seconds=args.rung_seconds, levels=args.levels, seed=args.seed),
              "host": args.host, "time_range": args.time_range, "work_size": len(work),
              "baseline": metrics.snapshot(http)}

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    def dump(tag):
        """Persist after each phase so a kill/failure keeps completed phases."""
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
        print("... wrote %s (through %s)" % (args.out, tag))

    if "l1" in tests:
        result["l1_ladder"] = l1_ladder(http, work, [int(x) for x in args.levels.split(",")])
        for r in result["l1_ladder"]:
            print("L1 N=%-3d pass=%.0f%% avg=%ss p95=%ss err=%.0f%% cpu=%s heap=%s queue=%s rej_d=%s"
                  % (r["concurrency"], r["pass_rate"] * 100, r["avg_s"], r["p95_s"],
                     r["err_timeout_rate"] * 100, r["cpu_max_pct"], r["heap_max_pct"],
                     r["search_queue_peak"], r["rejected_delta"]))
        dump("l1")
    if "l2" in tests:
        if args.settle_seconds and "l1" in tests:
            print("... settle %ds before L2" % args.settle_seconds)
            time.sleep(args.settle_seconds)
        result["l2_ramp"] = l2_ramp(http, ramp_work, args.ramp_max, args.ramp_sample,
                                    args.ramp_step, args.rung_seconds, args.seed)
        rr = result["l2_ramp"]
        print("L2 breaking_point=%s trigger=%s first_metric=%s onset=%s"
              % (rr["breaking_point"], rr["break_trigger"], rr["first_metric"], rr["saturation_onset"]))
        dump("l2")
    if "l3" in tests:
        if args.settle_seconds and tests & {"l1", "l2"}:
            print("... settle %ds before L3" % args.settle_seconds)
            time.sleep(args.settle_seconds)
        result["l3_sustained"] = l3_sustained(http, work, args.sustained_n, args.duration, args.seed)
        r = result["l3_sustained"]
        print("L3 N=%d %ds: pass=%.0f%% drift=%s%% heap_growth=%s%% minutes=%d"
              % (r["concurrency"], r["duration_s"], r["pass_rate"] * 100,
                 r["latency_drift_pct"], r["heap_growth_pct"], len(r["trend"])))
        dump("l3")

    result["final"] = metrics.snapshot(http)
    dump("final")
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
