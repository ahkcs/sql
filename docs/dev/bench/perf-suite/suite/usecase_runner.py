#!/usr/bin/env python3
"""Use-case pillar (plan §2.3 / U1-U7): realistic end-user access patterns.

U1 dashboard refresh · U2 auto-refresh · U3 investigation session ·
U4 alert-rule cadence · U5 multi-user mixed · U6 long-range · U7 WLM noisy-neighbor.
User-facing verdicts (GOOD <5s / ACCEPTABLE 5-10s / POOR >10s).

Usage (sandbox, short):
  python3 -m suite.usecase_runner --host https://EP --auth admin:PW \
      --scenarios u1,u2,u3,u4,u5,u6 --think 1 --short --out results/usecase.json
Full: drop --short/--think (real 30s/1m cadences, 20-30s think-time).

U7 additionally needs the §3.3 WLM policy and the two identities:
  export PPL_DASH_AUTH=dash_user:PW PPL_ADHOC_AUTH=adhoc_user:PW
  python3 -m suite.wlm --host ... --auth admin:PW --provision
It self-skips with a reason when WLM or an identity is missing — including on
Amazon OpenSearch Service, which does not expose _wlm (so U7 is Tier 1 only).
"""
import argparse
import itertools
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import catalogue, identities, metrics, runinfo, verdicts, wlm
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


def u5(http, duration, dash=None, adhoc=None):
    """5 concurrent users, each a different action loop for `duration`.

    When per-user identities are configured (plan §3.3) the dashboard/alert users
    authenticate as `dash_user` and the ad-hoc users as `adhoc_user`, so WLM
    classifies them into different groups; otherwise all five share `http`.
    """
    d, a = dash or http, adhoc or http
    actions = {
        "dashboard": lambda: _dashboard_once(d, DASHBOARD())["wall_s"],
        "session": lambda: run_ppl(a, SESSION()[1])["s"],
        "alert": lambda: run_ppl(d, "source=mock-kv-pi %s| stats count() by severityText" % _tw("15m"))["s"],
        "adhoc_rex": lambda: run_ppl(a, "source=mock-json-http %s| rex field=body '\"(?<m>\\w+) '" % _tw(TR))["s"],
        "browse": lambda: run_ppl(a, "source=mock-kv-pi %s| head 100" % _tw("1d"))["s"],
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


def _adhoc_queries():
    """The `bad-queries` category — U7's noisy neighbor (plan §2.4/M6)."""
    return [catalogue.full_query(q, "1d")
            for q in catalogue.build_catalogue() if q.category == "bad-queries"]


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


def _u7_phase(dash_http, adhoc_http, duration, noisy):
    """One phase: the dashboards user loops U1's dashboard; when `noisy`, the ad-hoc
    user hammers `bad-queries` in parallel."""
    panels, adhoc_q = DASHBOARD(), _adhoc_queries()
    end = time.time() + duration
    dash_runs, adhoc_runs, threads = [], [], []

    def dash_once():
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(panels)) as ex:
            res = list(ex.map(lambda p: run_ppl(dash_http, p), panels))
        return {"s": time.perf_counter() - t0, "ok": all(r["ok"] for r in res),
                "status": max(r["status"] for r in res)}

    threads.append(threading.Thread(target=_loop_until, args=(dash_once, end, dash_runs),
                                    daemon=True))
    if noisy:
        cyc = itertools.cycle(adhoc_q)

        def adhoc_once():
            r = run_ppl(adhoc_http, next(cyc))
            return {"s": r["s"], "ok": r["ok"], "status": r["status"]}
        threads.append(threading.Thread(target=_loop_until, args=(adhoc_once, end, adhoc_runs),
                                        daemon=True))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {"dashboards_user": _side_summary(dash_runs),
            "adhoc_user": _side_summary(adhoc_runs) if noisy else None}


def u7(host, admin_http, duration, dash_auth, adhoc_auth, http_factory=make_http):
    """Noisy-neighbor isolation (plan §2.3/U7, gates in §4.4).

    Three phases: solo (dashboards user alone) -> WLM off -> WLM on. The gate is
    the dashboards user's p95 with WLM on vs solo (<= 2x) plus a positive Δ
    rejections on the `adhoc` group, sampled from /_wlm/stats.
    """
    out = {"scenario": "U7 WLM noisy-neighbor"}
    p = wlm.paths(admin_http)
    if p is None:
        out.update(verdict="SKIPPED",
                   reason="cluster does not expose _wlm/_rules. Amazon OpenSearch Service "
                          "supports neither, and wlm.*.mode is not an allowlisted cluster "
                          "setting -> run U7 on Tier 1 (infra/local, security enabled).")
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

    solo = _u7_phase(dash_http, adhoc_http, duration, noisy=False)
    out["phases"]["solo"] = solo

    for mode in ("disabled", "enabled"):
        ok, body = wlm.set_mode(admin_http, mode, mode_setting)
        if not ok:
            out.update(verdict="SKIPPED", reason="cannot set %s=%s: %s"
                                                 % (mode_setting, mode, body[:200]))
            return out
        time.sleep(2)                              # let the setting propagate
        pre = wlm.stats(admin_http)
        phase = _u7_phase(dash_http, adhoc_http, duration, noisy=True)
        phase["wlm_stats_delta"] = wlm.delta(pre, wlm.stats(admin_http))
        out["phases"]["wlm_%s" % ("on" if mode == "enabled" else "off")] = phase

    on, off = out["phases"]["wlm_on"], out["phases"]["wlm_off"]
    solo_p95 = solo["dashboards_user"]["p95_s"]
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
               adhoc_group_delta=adhoc_delta,
               gates=gates,
               verdict="PASS" if all(gates.values()) else "FAIL")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--auth")
    ap.add_argument("--as-user", dest="as_user",
                    help="named identity for the main loop (see suite/identities.py)")
    ap.add_argument("--scenarios", default="u1,u2,u3,u4,u5,u6,u7")
    ap.add_argument("--think", type=float, default=25.0, help="U3 think-time seconds")
    ap.add_argument("--short", action="store_true", help="tiny durations for validation")
    ap.add_argument("--out", default="results/usecase.json")
    args = ap.parse_args()

    auth = identities.auth_for(args.as_user, args.auth)
    http = make_http(args.host, auth)
    # Per-user identities for the WLM-classified scenarios (U5, U7); None if unset.
    dash_auth = identities.auth_for("dash_user", None) if "dash_user" in identities.configured() else None
    adhoc_auth = identities.auth_for("adhoc_user", None) if "adhoc_user" in identities.configured() else None
    dash_http = make_http(args.host, dash_auth) if dash_auth else None
    adhoc_http = make_http(args.host, adhoc_auth) if adhoc_auth else None

    want = set(args.scenarios.split(","))
    # cadences/durations: full vs --short
    u2_cad, u2_dur = (30, 300) if not args.short else (5, 15)
    u4_cad, u4_dur = (60, 600) if not args.short else (5, 15)
    u5_dur = 600 if not args.short else 15
    u7_dur = 300 if not args.short else 15

    out = {"run": runinfo.header("usecase", args.host, as_user=args.as_user,
                                 identities=identities.configured()),
           "host": args.host, "results": []}
    runners = {"u1": lambda: u1(http), "u2": lambda: u2(http, u2_cad, u2_dur),
               "u3": lambda: u3(http, args.think), "u4": lambda: u4(http, u4_cad, u4_dur),
               "u5": lambda: u5(http, u5_dur, dash_http, adhoc_http),
               "u6": lambda: u6(http),
               "u7": lambda: u7(args.host, http, u7_dur, dash_auth, adhoc_auth)}
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
