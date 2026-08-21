#!/usr/bin/env python3
"""Compare two perf results.json — flag queries whose p95 moved beyond a threshold.

The §3.4 "regression detector": p95 moved > 20% vs a prior (green) run.
Usage: python3 report/diff.py OLD.json NEW.json [--pct 20]
"""
import argparse
import json


def key(r):
    return (r["id"], r["time_range"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--pct", type=float, default=20.0)
    args = ap.parse_args()

    old = {key(r): r for r in json.load(open(args.old)).get("perf", [])}
    new = {key(r): r for r in json.load(open(args.new)).get("perf", [])}

    rows, regressions = [], 0
    for k in sorted(set(old) & set(new)):
        o, n = old[k]["p95_s"], new[k]["p95_s"]
        if o <= 0:
            continue
        delta = (n - o) / o * 100.0
        if abs(delta) >= args.pct:
            flag = "REGRESSION" if delta > 0 else "improved"
            if delta > 0:
                regressions += 1
            rows.append((k[0], k[1], o, n, delta, flag))

    print("# p95 diff (threshold +/-%.0f%%)\n" % args.pct)
    if not rows:
        print("No queries moved beyond threshold.")
    else:
        print("| Query | range | old_p95 | new_p95 | delta%% | flag |")
        print("| --- | --- | ---: | ---: | ---: | --- |")
        for id_, tr, o, n, d, f in sorted(rows, key=lambda z: -z[4]):
            print("| %s | %s | %.3f | %.3f | %+.0f%% | %s |" % (id_, tr, o, n, d, f))
    print("\n%d regressions, %d moved / %d common queries"
          % (regressions, len(rows), len(set(old) & set(new))))
    raise SystemExit(1 if regressions else 0)


if __name__ == "__main__":
    main()
