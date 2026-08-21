#!/usr/bin/env python3
"""Use-case pillar (plan §2.3 / U1-U7): realistic end-user access patterns.

U1 dashboard refresh · U2 auto-refresh · U3 investigation session ·
U4 alert-rule cadence · U5 multi-user mixed · U6 long-range · U7 WLM noisy-neighbor.
User-facing verdicts (GOOD <5s / ACCEPTABLE 5-10s / POOR >10s).

Usage (sandbox, short):
  python3 -m suite.usecase_runner --host https://EP --auth admin:PW \
      --scenarios u1,u2,u3,u4,u5,u6 --think 1 --short --out results/usecase.json
Full: drop --short/--think (real 30s/1m cadences, 20-30s think-time).
"""
import argparse
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import catalogue, metrics, verdicts
from .runner import make_http, pct, run_ppl

TR = "1h"                                    # default dashboard/panel time range


def _tw(tr=TR):
    return catalogue.time_where(tr)


def DASHBOARD(tr=TR):
    w = _tw(tr)
    return [
        "source=mock-kv-pi %s| stats count() by severityText" % w,
        "source=mock-kv-pi %s| top 10 resource.attributes.service.name" % w,
        "source=mock-json-http %s| stats count() by log.status" % w,
        "source=mock-kv-pi %s| stats count() by span(@timestamp, 1h)" % w,
        "source=mock-mixed-pi %s| where severityText='ERROR' | head 50" % w,
        "source=mock-kv-pi %s| stats count() by resource.attributes.cloud.region" % w,
    ]


def SESSION(tr="1d"):                         # progressive narrowing
    w = _tw(tr)
    return [
        "source=mock-mixed-pi %s| stats count()" % w,
        "source=mock-mixed-pi %s| where severityText='ERROR'" % w,
        "source=mock-mixed-pi %s| where severityText='ERROR' | rex field=body '(?<w>\\w+)'" % w,
        "source=mock-mixed-pi %s| where severityText='ERROR' | dedup resource.attributes.service.name" % w,
    ]


def _dashboard_once(http, panels):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(panels)) as ex:
        res = list(ex.map(lambda p: run_ppl(http, p), panels))
    wall = time.perf_counter() - t0
    lat = [r["s"] for r in res]
    return {"wall_s": round(wall, 3), "avg_panel_s": round(statistics.mean(lat), 3),
            "slowest_panel_s": round(max(lat), 3),
            "errors": sum(1 for r in res if not r["ok"]),
            "verdict": verdicts.usecase_verdict(wall)}


def u1(http):
    return {"scenario": "U1 dashboard refresh", **_dashboard_once(http, DASHBOARD())}


def u2(http, cadence, duration):
    panels, walls, errs, end = DASHBOARD(), [], 0, time.time() + duration
    while time.time() < end:
        c = _dashboard_once(http, panels)
        walls.append(c["wall_s"]); errs += c["errors"]
        time.sleep(max(0, cadence - c["wall_s"]))
    return {"scenario": "U2 auto-refresh", "refreshes": len(walls),
            "p95_wall_s": round(pct(walls, 95), 3), "errors": errs,
            "verdict": verdicts.usecase_verdict(pct(walls, 95))}


def u3(http, think):
    steps = []
    for i, ppl in enumerate(SESSION()):
        r = run_ppl(http, ppl)
        steps.append({"step": i, "s": round(r["s"], 3), "ok": r["ok"]})
        time.sleep(think)
    lat = [s["s"] for s in steps]
    return {"scenario": "U3 investigation session", "steps": steps,
            "median_step_s": round(statistics.median(lat), 3), "slowest_step_s": round(max(lat), 3),
            "completed_ok": all(s["ok"] for s in steps),
            "verdict": verdicts.usecase_verdict(statistics.median(lat))}


def u4(http, cadence, duration):
    q = "source=mock-kv-pi %s| stats count() by severityText" % _tw("15m")
    lats, missed, end = [], 0, time.time() + duration
    while time.time() < end:
        r = run_ppl(http, q)
        lats.append(r["s"])
        if r["s"] > cadence:
            missed += 1
        time.sleep(max(0, cadence - r["s"]))
    return {"scenario": "U4 alert-rule", "evaluations": len(lats),
            "p95_s": round(pct(lats, 95), 3), "missed": missed,
            "verdict": verdicts.usecase_verdict(pct(lats, 95))}


def u5(http, duration):
    """5 concurrent users, each a different action loop for `duration`."""
    actions = {
        "dashboard": lambda: _dashboard_once(http, DASHBOARD())["wall_s"],
        "session": lambda: run_ppl(http, SESSION()[1])["s"],
        "alert": lambda: run_ppl(http, "source=mock-kv-pi %s| stats count() by severityText" % _tw("15m"))["s"],
        "adhoc_rex": lambda: run_ppl(http, "source=mock-json-http %s| rex field=body '\"(?<m>\\w+) '" % _tw(TR))["s"],
        "browse": lambda: run_ppl(http, "source=mock-kv-pi %s| head 100" % _tw("1d"))["s"],
    }
    per, lock, end = {k: [] for k in actions}, threading.Lock(), time.time() + duration
    def loop(name, fn):
        while time.time() < end:
            v = fn()
            with lock:
                per[name].append(v)
    threads = [threading.Thread(target=loop, args=(k, fn), daemon=True) for k, fn in actions.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"scenario": "U5 multi-user mixed",
            "users": {k: {"n": len(v), "median_s": round(statistics.median(v), 3),
                          "p95_s": round(pct(v, 95), 3)} for k, v in per.items() if v}}


def u6(http):
    q = "source=mock-kv-pi %s| stats count() by resource.attributes.k8s.namespace.name"
    curve = []
    for tr in ["1h", "6h", "1d", "3d", "7d"]:
        r = run_ppl(http, q % catalogue.time_where(tr))
        curve.append({"range": tr, "s": round(r["s"], 3), "ok": r["ok"]})
    return {"scenario": "U6 long-range", "curve": curve}


def u7(http):
    s, _ = http("GET", "/_wlm/stats")
    if s != 200:
        return {"scenario": "U7 WLM noisy-neighbor",
                "verdict": "SKIPPED",
                "reason": "WLM not configured (see plan §3.3: dashboards/adhoc query groups, "
                          "dash_user/adhoc_user, routing rules). Requires OpenSearch >=2.18 and "
                          "the two-user setup; run twice (WLM off/on) with per-user auth."}
    return {"scenario": "U7 WLM noisy-neighbor", "verdict": "TODO",
            "note": "WLM present; per-user two-profile off/on comparison not yet implemented."}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--auth")
    ap.add_argument("--scenarios", default="u1,u2,u3,u4,u5,u6,u7")
    ap.add_argument("--think", type=float, default=25.0, help="U3 think-time seconds")
    ap.add_argument("--short", action="store_true", help="tiny durations for validation")
    ap.add_argument("--out", default="results/usecase.json")
    args = ap.parse_args()

    http = make_http(args.host, args.auth)
    want = set(args.scenarios.split(","))
    # cadences/durations: full vs --short
    u2_cad, u2_dur = (30, 300) if not args.short else (5, 15)
    u4_cad, u4_dur = (60, 600) if not args.short else (5, 15)
    u5_dur = 600 if not args.short else 15

    out = {"host": args.host, "results": []}
    runners = {"u1": lambda: u1(http), "u2": lambda: u2(http, u2_cad, u2_dur),
               "u3": lambda: u3(http, args.think), "u4": lambda: u4(http, u4_cad, u4_dur),
               "u5": lambda: u5(http, u5_dur), "u6": lambda: u6(http), "u7": lambda: u7(http)}
    for key in ["u1", "u2", "u3", "u4", "u5", "u6", "u7"]:
        if key in want:
            r = runners[key]()
            out["results"].append(r)
            print("%-30s %s" % (r["scenario"], r.get("verdict", r.get("users", ""))))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
