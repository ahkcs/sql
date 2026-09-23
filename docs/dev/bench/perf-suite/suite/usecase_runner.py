#!/usr/bin/env python3
"""Use-case pillar (plan §2.3 / U1-U7): realistic end-user access patterns.

U1 dashboard refresh · U2 auto-refresh · U3 investigation session ·
U4 alert-rule cadence · U5 multi-user mixed · U6 long-range · U7 WLM noisy-neighbor.
User-facing verdicts (GOOD <5s / ACCEPTABLE 5-10s / POOR >10s).

**Rolling vs fixed window.** A real dashboard queries `now-<range>`, so every
refresh is a new window and nothing is served from the shard request cache. The
earlier runs pinned an absolute window, which made repeated refreshes exact cache
hits and reported 20-50x faster than the same queries in the Perf pillar. A
literal `now-<range>` is not usable here either: the dataset's @timestamp ends
2026-04-11, so `now-1h` matches zero documents. `--cache-mode rolling` (default)
therefore slides a constant-width window back by `--window-step` per iteration,
which defeats the cache exactly as a real rolling window does while holding doc
volume steady. `--cache-mode fixed` reproduces the old cache-warm behaviour for
comparison.

Every scenario is sampled by a background metrics poller, and each result carries
its own peaks plus the raw series (plan §2.3 deliverable 9). U7 additionally
carries per-group /_wlm/stats deltas.

Usage (sandbox, short):
  python3 -m suite.usecase_runner --host https://EP --as-user admin \
      --scenarios u1,u2,u3,u4,u5,u6 --think 1 --short --out results/usecase.json
Full: drop --short/--think (real 30s/1m cadences, 20-30s think-time).

U7 needs the §3.3 WLM policy and the two identities:
  export PPL_DASH_AUTH=dash_user:PW PPL_ADHOC_AUTH=adhoc_user:PW
  python3 -m suite.wlm --host ... --auth admin:PW --provision
It self-skips with a specific reason when WLM or an identity is missing.
"""
import argparse
import itertools
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from mock_data import distributions as dist

from . import catalogue, identities, metrics, runinfo, verdicts, wlm
from .load_runner import Sampler
from .runner import make_http, pct, run_ppl

TR = "1h"

# Fields present in every body format, so a panel can run against any index pattern.
SEV = "severityText"
SVC = "resource.attributes.service.name"
REGION = "resource.attributes.cloud.region"
POD = "resource.attributes.k8s.pod.name"

INDEX_PATTERNS = ["mock-kv-pi", "mock-json-*", "mock-*"]

_SECS = {"5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400,
         "3d": 259200, "7d": 604800}


def _fmt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def window_where(tr, iteration=0, mode="rolling", step_s=30):
    """Time predicate for one iteration. rolling -> constant-width window slid back
    by iteration*step_s (cache-defeating); fixed -> the catalogue's absolute lower
    bound (cache-warm)."""
    if mode == "fixed":
        return catalogue.time_where(tr)
    secs = _SECS[tr]
    ub = dist.ANCHOR_MS - iteration * step_s * 1000
    lb = ub - secs * 1000
    return "| where @timestamp >= '%s' and @timestamp < '%s' " % (_fmt(lb), _fmt(ub))


class Win:
    """Per-scenario window factory; keeps the mode/step choice out of every call."""

    def __init__(self, mode, step_s):
        self.mode, self.step_s = mode, step_s

    def __call__(self, tr=TR, iteration=0):
        return window_where(tr, iteration, self.mode, self.step_s)


# name -> panel builders (index, window) -> ppl. 5-8 panels each, common fields only.
DASHBOARD_VARIANTS = {
    "ops_overview": [
        lambda i, w: "source=%s %s| stats count() by %s" % (i, w, SEV),
        lambda i, w: "source=%s %s| top 10 %s" % (i, w, SVC),
        lambda i, w: "source=%s %s| stats count() by span(@timestamp, 1h)" % (i, w),
        lambda i, w: "source=%s %s| where %s='ERROR' | head 50" % (i, w, SEV),
        lambda i, w: "source=%s %s| stats count() by %s" % (i, w, REGION),
        lambda i, w: "source=%s %s| stats dc(%s) as pods" % (i, w, POD),
    ],
    "error_triage": [
        lambda i, w: "source=%s %s| where %s='ERROR' | stats count()" % (i, w, SEV),
        lambda i, w: "source=%s %s| where %s='ERROR' | stats count() by %s" % (i, w, SEV, SVC),
        lambda i, w: "source=%s %s| where %s='ERROR' | stats count() by span(@timestamp, 1h)" % (i, w, SEV),
        lambda i, w: "source=%s %s| where %s='ERROR' | head 50" % (i, w, SEV),
        lambda i, w: "source=%s %s| where %s='ERROR' | stats count() by %s" % (i, w, SEV, REGION),
    ],
    "service_health": [
        lambda i, w: "source=%s %s| stats count() by %s" % (i, w, SVC),
        lambda i, w: "source=%s %s| stats count() by %s, %s" % (i, w, SVC, SEV),
        lambda i, w: "source=%s %s| stats avg(attributes.obs_body_length) as avg_len" % (i, w),
        lambda i, w: "source=%s %s| stats percentile(attributes.obs_body_length, 95) as p95_len" % (i, w),
        lambda i, w: "source=%s %s| stats count() by span(@timestamp, 1h)" % (i, w),
    ],
}


def SESSION(win, tr="1d"):
    """~10 progressive-narrowing steps (plan §2.3 U3)."""
    w = win(tr)
    base = "source=mock-mixed-pi %s" % w
    err = "%s| where %s='ERROR' " % (base, SEV)
    return [
        ("broad_count", "%s| stats count()" % base),
        ("count_by_sev", "%s| stats count() by %s" % (base, SEV)),
        ("filter_error", "%s| stats count()" % err),
        ("error_by_service", "%s| stats count() by %s" % (err, SVC)),
        ("error_timeline", "%s| stats count() by span(@timestamp, 1h)" % err),
        ("error_sample", "%s| head 100" % err),
        ("rex_extract", r"%s| rex field=body '(?<w>\w+)' | head 100" % err),
        ("rex_aggregate", r"%s| rex field=body '(?<w>\w+)' | stats count() by w" % err),
        ("dedup_pod", "%s| dedup %s | head 100" % (err, POD)),
        ("sort_recent", "%s| sort @timestamp | head 50" % err),
    ]


def _card(lat, errors, on=None):
    """Normalised verdict card: median, p95, errors, user-facing verdict."""
    if not lat:
        return {"median_s": None, "p95_s": None, "errors": errors, "verdict": "NO_DATA"}
    basis = statistics.median(lat) if on is None else on
    return {"median_s": round(statistics.median(lat), 3), "p95_s": round(pct(lat, 95), 3),
            "max_s": round(max(lat), 3), "errors": errors,
            "verdict": verdicts.usecase_verdict(basis)}


def _dashboard_once(http, panels, index, win, iteration=0):
    ppls = [p(index, win(TR, iteration)) for p in panels]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(ppls)) as ex:
        res = list(ex.map(lambda p: run_ppl(http, p), ppls))
    wall = time.perf_counter() - t0
    lat = [r["s"] for r in res]
    return {"wall_s": round(wall, 3), "panels": len(ppls),
            "avg_panel_s": round(statistics.mean(lat), 3),
            "slowest_panel_s": round(max(lat), 3),
            "errors": sum(1 for r in res if not r["ok"]),
            "verdict": verdicts.usecase_verdict(wall)}


def _sampled(http, fn):
    """Run fn() under a metrics sampler; return (result, metrics_dict)."""
    s = Sampler(http, interval=5.0)
    pre = metrics.snapshot(http)
    s.start()
    try:
        out = fn()
    finally:
        s.stop()
    post = metrics.snapshot(http)
    return out, {"peaks": s.peaks(), "pre": pre, "post": post, "series": s.samples,
                 "deltas": metrics.delta(pre, post)}


def u1(http, win):
    """Dashboard refresh: one row per variant x index pattern."""
    rows = []
    for name, panels in DASHBOARD_VARIANTS.items():
        for idx in INDEX_PATTERNS:
            r = _dashboard_once(http, panels, idx, win)
            r.update(variant=name, index_pattern=idx)
            rows.append(r)
    walls = [r["wall_s"] for r in rows]
    return {"scenario": "U1 dashboard refresh", "id": "u1", "rows": rows,
            **_card(walls, sum(r["errors"] for r in rows))}


def u2(http, win, cadence, duration):
    """Auto-refresh: per-refresh series so the trend over the window is visible."""
    panels = DASHBOARD_VARIANTS["ops_overview"]
    series, errs, i, t0, end = [], 0, 0, time.time(), time.time() + duration
    while time.time() < end:
        c = _dashboard_once(http, panels, "mock-kv-pi", win, iteration=i)
        series.append({"refresh": i, "t_offset_s": round(time.time() - t0, 1),
                       "wall_s": c["wall_s"], "slowest_panel_s": c["slowest_panel_s"],
                       "errors": c["errors"]})
        errs += c["errors"]
        i += 1
        time.sleep(max(0, cadence - c["wall_s"]))
    walls = [x["wall_s"] for x in series]
    return {"scenario": "U2 auto-refresh", "id": "u2", "cadence_s": cadence,
            "refreshes": len(series), "series": series,
            **_card(walls, errs, on=pct(walls, 95) if walls else None)}


def u3(http, win, think):
    """Investigation session: ~10 steps, each flagged against the <5s target."""
    steps = []
    for i, (label, ppl) in enumerate(SESSION(win)):
        r = run_ppl(http, ppl)
        steps.append({"step": i, "label": label, "s": round(r["s"], 3), "ok": r["ok"],
                      "verdict": verdicts.usecase_verdict(r["s"]),
                      "missed_target": r["s"] >= 5.0, "ppl": ppl})
        time.sleep(think)
    lat = [s["s"] for s in steps]
    return {"scenario": "U3 investigation session", "id": "u3", "steps": steps,
            "steps_missing_target": [s["label"] for s in steps if s["missed_target"]],
            "completed_ok": all(s["ok"] for s in steps),
            **_card(lat, sum(0 if s["ok"] else 1 for s in steps))}


def u4(http, win, cadence, duration):
    """Alert-rule cadence: completed-within-budget vs missed."""
    lats, missed, errs, i, end = [], 0, 0, 0, time.time() + duration
    while time.time() < end:
        ppl = "source=mock-kv-pi %s| stats count() by %s" % (win("15m", i), SEV)
        r = run_ppl(http, ppl)
        lats.append(r["s"])
        errs += 0 if r["ok"] else 1
        if r["s"] > cadence:
            missed += 1
        i += 1
        time.sleep(max(0, cadence - r["s"]))
    return {"scenario": "U4 alert-rule", "id": "u4", "cadence_s": cadence,
            "evaluations": len(lats), "within_budget": len(lats) - missed, "missed": missed,
            **_card(lats, errs, on=pct(lats, 95) if lats else None)}


def _u5_actions(http, win, dash=None, adhoc=None):
    d, a = dash or http, adhoc or http
    return {
        "dashboard": lambda i: _dashboard_once(d, DASHBOARD_VARIANTS["ops_overview"],
                                               "mock-kv-pi", win, i)["wall_s"],
        "session": lambda i: run_ppl(a, "source=mock-mixed-pi %s| where %s='ERROR' | stats count() by %s"
                                     % (win("1d", i), SEV, SVC))["s"],
        "alert": lambda i: run_ppl(d, "source=mock-kv-pi %s| stats count() by %s"
                                   % (win("15m", i), SEV))["s"],
        "adhoc_rex": lambda i: run_ppl(a, r"source=mock-json-http %s| rex field=body '(?<w>\w+)' | stats count() by w"
                                       % win(TR, i))["s"],
        "browse": lambda i: run_ppl(a, "source=mock-kv-pi %s| head 100" % win("1d", i))["s"],
    }


def u5(http, win, duration, solo_reps, warmup_reps=2, dash=None, adhoc=None):
    """Multi-user mixed, measured against each user's own solo baseline.

    The baseline is warmed first. With a cold baseline the mixed phase — which
    runs for minutes and warms the page cache and JVM — comes out FASTER than
    solo, so every degradation ratio lands below 1.0 and measures warmup instead
    of contention.
    """
    actions = _u5_actions(http, win, dash, adhoc)

    solo = {}
    for name, fn in actions.items():
        for i in range(warmup_reps):
            fn(i)
        lat = [fn(warmup_reps + i) for i in range(solo_reps)]
        solo[name] = {"n": len(lat), "warmup_reps": warmup_reps,
                      "median_s": round(statistics.median(lat), 3),
                      "p95_s": round(pct(lat, 95), 3)}

    per, lock, end = {k: [] for k in actions}, threading.Lock(), time.time() + duration

    def loop(name, fn):
        i = 0
        while time.time() < end:
            v = fn(i)
            i += 1
            with lock:
                per[name].append(v)
    threads = [threading.Thread(target=loop, args=(k, fn), daemon=True)
               for k, fn in actions.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    users = {}
    for k, v in per.items():
        if not v:
            continue
        med, p95 = statistics.median(v), pct(v, 95)
        s = solo.get(k, {})
        users[k] = {"n": len(v), "median_s": round(med, 3), "p95_s": round(p95, 3),
                    "solo_median_s": s.get("median_s"), "solo_p95_s": s.get("p95_s"),
                    "median_degradation_x": round(med / s["median_s"], 2)
                    if s.get("median_s") else None,
                    "p95_degradation_x": round(p95 / s["p95_s"], 2) if s.get("p95_s") else None,
                    "verdict": verdicts.usecase_verdict(med)}
    allv = [x for v in per.values() for x in v]
    return {"scenario": "U5 multi-user mixed", "id": "u5", "users": users, "solo_baseline": solo,
            **_card(allv, 0)}


def u6(http, win):
    """Long-range: same query stepped 1h -> 7d."""
    curve = []
    for tr in ["1h", "6h", "1d", "3d", "7d"]:
        ppl = "source=mock-kv-pi %s| stats count() by resource.attributes.k8s.namespace.name" % win(tr)
        r = run_ppl(http, ppl)
        curve.append({"range": tr, "s": round(r["s"], 3), "ok": r["ok"],
                      "verdict": verdicts.usecase_verdict(r["s"])})
    lat = [c["s"] for c in curve]
    return {"scenario": "U6 long-range", "id": "u6", "curve": curve,
            "growth_1h_to_7d_x": round(curve[-1]["s"] / curve[0]["s"], 1) if curve[0]["s"] else None,
            **_card(lat, sum(0 if c["ok"] else 1 for c in curve), on=max(lat))}


def noisy_queries(win):
    """U7's noisy neighbour: the known-slow full-scan/extract queries at 1d, minus
    the two whole-set ops that die on the memory breaker regardless of neighbours."""
    skip = {"cmd_eventstats", "cmd_streamstats"}
    out = [catalogue.full_query(q, "1d") for q in catalogue.build_catalogue()
           if q.known_slow and q.id not in skip]
    return out or [r"source=mock-mixed-pi %s| rex field=body '(?<w>\w+)' | stats count() by w"
                   % win("1d")]


def _loop_until(fn, end, out):
    while time.time() < end:
        out.append(fn())


def _side_summary(samples):
    lat = [r["s"] for r in samples]
    return {"n": len(samples),
            "p95_s": round(pct(lat, 95), 3) if lat else None,
            "median_s": round(statistics.median(lat), 3) if lat else None,
            "errors": sum(1 for r in samples if not r["ok"]),
            "throttled_429": sum(1 for r in samples if r["status"] == 429)}


def _u7_phase(dash_http, adhoc_http, win, duration, noisy, noisy_threads=1):
    """One phase. `noisy_threads` adhoc loops run in parallel: a single serial loop
    barely dents the dashboards user (~1.1x), which makes the isolation gates pass
    without ever creating contention to isolate against. Load-pillar data puts the
    heavy-query ceiling near 25 concurrent, so the neighbour needs to be in that
    range for WLM-off to actually hurt."""
    panels, adhoc_q = DASHBOARD_VARIANTS["ops_overview"], noisy_queries(win)
    end = time.time() + duration
    dash_runs, adhoc_runs, threads = [], [], []
    counter = itertools.count()

    def dash_once():
        i = next(counter)
        t0 = time.perf_counter()
        ppls = [p("mock-kv-pi", win(TR, i)) for p in panels]
        with ThreadPoolExecutor(max_workers=len(ppls)) as ex:
            res = list(ex.map(lambda p: run_ppl(dash_http, p), ppls))
        return {"s": time.perf_counter() - t0, "ok": all(r["ok"] for r in res),
                "status": max(r["status"] for r in res)}

    threads.append(threading.Thread(target=_loop_until, args=(dash_once, end, dash_runs),
                                    daemon=True))
    if noisy:
        acount = itertools.count()

        def adhoc_once():
            r = run_ppl(adhoc_http, adhoc_q[next(acount) % len(adhoc_q)])
            return {"s": r["s"], "ok": r["ok"], "status": r["status"]}
        for _ in range(max(1, noisy_threads)):
            threads.append(threading.Thread(target=_loop_until,
                                            args=(adhoc_once, end, adhoc_runs), daemon=True))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"dashboards_user": _side_summary(dash_runs),
            "adhoc_user": _side_summary(adhoc_runs) if noisy else None,
            "noisy_pool_size": len(adhoc_q) if noisy else 0,
            "noisy_threads": noisy_threads if noisy else 0}


def u7(host, admin_http, win, duration, dash_auth, adhoc_auth, noisy_threads=20,
       http_factory=make_http):
    """Noisy-neighbor isolation (plan §2.3/U7, gates in §4.4): solo -> WLM off -> WLM on."""
    out = {"scenario": "U7 WLM noisy-neighbor", "id": "u7"}
    p = wlm.paths(admin_http)
    if p is None:
        out.update(verdict="SKIPPED",
                   reason="cluster does not expose _wlm/_rules (needs OpenSearch >= 2.18 with "
                          "workload management; managed AWS domains do expose it on 3.5).")
        return out
    group_path, rules_path, mode_setting = p
    if not (dash_auth and adhoc_auth):
        out.update(verdict="SKIPPED",
                   reason="needs both identities: set PPL_DASH_AUTH and PPL_ADHOC_AUTH "
                          "(see suite/identities.py) and provision with "
                          "`python3 -m suite.wlm --provision`.")
        return out
    ids = wlm.group_ids(admin_http, group_path)
    if not {"dashboards", "adhoc"} <= set(ids):
        out.update(verdict="SKIPPED",
                   reason="workload groups %s not loaded; run `python3 -m suite.wlm --provision`"
                          % sorted({"dashboards", "adhoc"} - set(ids)))
        return out

    dash_http, adhoc_http = http_factory(host, dash_auth), http_factory(host, adhoc_auth)
    out["group_ids"] = ids
    out["phases"] = {}
    out["noisy_threads"] = noisy_threads
    out["phases"]["solo"] = _u7_phase(dash_http, adhoc_http, win, duration, noisy=False)

    for mode in ("disabled", "enabled"):
        ok, body = wlm.set_mode(admin_http, mode, mode_setting)
        if not ok:
            out.update(verdict="SKIPPED", reason="cannot set %s=%s: %s"
                                                 % (mode_setting, mode, body[:200]))
            return out
        time.sleep(2)
        pre = wlm.stats(admin_http)
        phase = _u7_phase(dash_http, adhoc_http, win, duration, noisy=True,
                          noisy_threads=noisy_threads)
        phase["wlm_stats_delta"] = wlm.delta(pre, wlm.stats(admin_http))
        out["phases"]["wlm_%s" % ("on" if mode == "enabled" else "off")] = phase

    on, off = out["phases"]["wlm_on"], out["phases"]["wlm_off"]
    solo_p95 = out["phases"]["solo"]["dashboards_user"]["p95_s"]
    adhoc_delta = on["wlm_stats_delta"].get(ids["adhoc"], {})
    degr_on = (on["dashboards_user"]["p95_s"] / solo_p95) if solo_p95 else None
    degr_off = (off["dashboards_user"]["p95_s"] / solo_p95) if solo_p95 else None
    adhoc_alive = (on["adhoc_user"]["n"] - on["adhoc_user"]["errors"] > 0
                   or on["adhoc_user"]["throttled_429"] > 0)
    gates = {
        "dash_p95_degradation_wlm_on_le_2x": degr_on is not None and degr_on <= 2.0,
        "dash_errors_wlm_on_is_zero": on["dashboards_user"]["errors"] == 0,
        "adhoc_rejections_delta_gt_0": adhoc_delta.get("rejections", 0) > 0,
        "adhoc_not_starved": adhoc_alive,
    }
    out.update(solo_dash_p95_s=solo_p95,
               dash_degradation_wlm_off=round(degr_off, 2) if degr_off else None,
               dash_degradation_wlm_on=round(degr_on, 2) if degr_on else None,
               adhoc_group_delta=adhoc_delta, gates=gates,
               verdict="PASS" if all(gates.values()) else "FAIL")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--auth")
    ap.add_argument("--as-user", dest="as_user")
    ap.add_argument("--scenarios", default="u1,u2,u3,u4,u5,u6,u7")
    ap.add_argument("--think", type=float, default=25.0, help="U3 think-time seconds")
    ap.add_argument("--cache-mode", choices=["rolling", "fixed"], default="rolling",
                    help="rolling: slide the window per iteration (cache-cold, realistic); "
                         "fixed: pin an absolute window (cache-warm, the old behaviour)")
    ap.add_argument("--window-step", type=int, default=30,
                    help="seconds the rolling window slides per iteration")
    ap.add_argument("--solo-reps", type=int, default=6, help="U5 solo-baseline reps per user")
    ap.add_argument("--solo-warmup", type=int, default=2,
                    help="U5 discarded warmup reps before the solo baseline")
    ap.add_argument("--u7-noisy-threads", type=int, default=20,
                    help="U7 parallel ad-hoc loops; 1 is too weak to create contention")
    ap.add_argument("--short", action="store_true", help="tiny durations for validation")
    ap.add_argument("--out", default="results/usecase.json")
    args = ap.parse_args()

    auth = identities.auth_for(args.as_user, args.auth)
    http = make_http(args.host, auth)
    dash_auth = identities.auth_for("dash_user", None) if "dash_user" in identities.configured() else None
    adhoc_auth = identities.auth_for("adhoc_user", None) if "adhoc_user" in identities.configured() else None
    dash_http = make_http(args.host, dash_auth) if dash_auth else None
    adhoc_http = make_http(args.host, adhoc_auth) if adhoc_auth else None
    win = Win(args.cache_mode, args.window_step)

    want = set(args.scenarios.split(","))
    u2_cad, u2_dur = (30, 300) if not args.short else (5, 15)
    u4_cad, u4_dur = (60, 600) if not args.short else (5, 15)
    u5_dur = 600 if not args.short else 15
    u7_dur = 300 if not args.short else 15
    solo_reps = args.solo_reps if not args.short else 1
    solo_warmup = args.solo_warmup if not args.short else 0
    noisy_threads = args.u7_noisy_threads if not args.short else 2

    out = {"run": runinfo.header("usecase", args.host, as_user=args.as_user,
                                 identities=identities.configured(),
                                 cache_mode=args.cache_mode, window_step_s=args.window_step,
                                 solo_reps=args.solo_reps, solo_warmup=args.solo_warmup,
                                 u7_noisy_threads=args.u7_noisy_threads,
                                 index_patterns=INDEX_PATTERNS,
                                 dashboard_variants=sorted(DASHBOARD_VARIANTS)),
           "host": args.host, "baseline": metrics.snapshot(http), "results": []}

    runners = {
        "u1": lambda: u1(http, win),
        "u2": lambda: u2(http, win, u2_cad, u2_dur),
        "u3": lambda: u3(http, win, args.think),
        "u4": lambda: u4(http, win, u4_cad, u4_dur),
        "u5": lambda: u5(http, win, u5_dur, solo_reps, solo_warmup, dash_http, adhoc_http),
        "u6": lambda: u6(http, win),
        "u7": lambda: u7(args.host, http, win, u7_dur, dash_auth, adhoc_auth, noisy_threads),
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    for key in ["u1", "u2", "u3", "u4", "u5", "u6", "u7"]:
        if key not in want:
            continue
        r, m = _sampled(http, runners[key])
        r["metrics"] = m
        out["results"].append(r)
        print("%-30s %-11s median=%s p95=%s errors=%s"
              % (r["scenario"], r.get("verdict"), r.get("median_s"), r.get("p95_s"),
                 r.get("errors")))
        with open(args.out, "w") as f:                 # persist per scenario
            json.dump(out, f, indent=2)

    out["final"] = metrics.snapshot(http)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
