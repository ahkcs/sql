#!/usr/bin/env python3
"""Render the type x operation pushdown matrix into report.md.

Emits the type/op grid, the list of non-pushed combinations with their
coordinator-side plan, errors, and the untested-type gap.

Usage: python3 report/make_pushdown_report.py results/pushdown/pushdown.json [> report.md]
"""
import json
import sys
from collections import Counter, OrderedDict

MARK = {"PUSHED": "ok", "FALLBACK": "FB", "FALLBACK_UNBOUNDED": "**FB-UNB**", "ERROR": "ERR"}


def main():
    d = json.load(open(sys.argv[1]))
    run, pts = d.get("run", {}), d.get("points", [])
    out = []
    out.append("# PPL pushdown matrix — type x operation\n")
    out.append("| Field | Value |\n| --- | --- |")
    for k in ("run_id", "host", "tier", "git_sha", "suites", "indices", "index",
              "points", "classifier_version"):
        if run.get(k) is not None:
            out.append("| %s | %s |" % (k, run[k]))
    out.append("")
    out.append("Verdicts: **ok** = the operation's own work is pushed to OpenSearch · "
               "**FB** = falls back to coordinator-side but row flow is capped · "
               "**FB-UNB** = falls back AND no reduction/limit is pushed, so every matching "
               "row crosses the wire (the dangerous shape) · **ERR** = query rejected.\n")
    if run.get("note"):
        out.append("_%s_\n" % run["note"])

    ops = OrderedDict()
    for p in pts:
        ops.setdefault(p["op"], True)
    suites = OrderedDict()
    for p in pts:
        suites.setdefault(p.get("suite", "fidelity"), OrderedDict())
        suites[p["suite"] if p.get("suite") else "fidelity"].setdefault(
            p["type_label"], p.get("mapped_type", ""))
    grid = {(p.get("suite", "fidelity"), p["type_label"], p["op"]): p["verdict"] for p in pts}

    out.append("## Matrix\n")
    for suite, types in suites.items():
        idx = sorted({p["index"] for p in pts if p.get("suite", "fidelity") == suite
                      and p.get("index")})
        out.append("**suite `%s`**%s\n" % (suite, (" — `%s`" % ", ".join(idx)) if idx else ""))
        out.append("| type (field) | " + " | ".join(ops) + " |")
        out.append("| --- |" + " --- |" * len(ops))
        for t, mt in types.items():
            cells = [MARK.get(grid.get((suite, t, o)), "-") for o in ops]
            out.append("| %s <br>`%s` | %s |" % (t, mt, " | ".join(cells)))
        out.append("")

    vc = Counter(p["verdict"] for p in pts)
    out.append("Totals: " + ", ".join("%s=%d" % (k, v) for k, v in sorted(vc.items())) + "\n")

    bad = [p for p in pts if p["verdict"].startswith("FALLBACK")]
    if bad:
        out.append("## Not pushed down\n")
        out.append("| type | op | verdict | coordinator ops | size=MAX | query |")
        out.append("|" + " --- |" * 6)
        for p in sorted(bad, key=lambda z: (z["verdict"], z["type_label"], z["op"])):
            out.append("| %s | %s | %s | %s | %s | `%s` |" % (
                "%s/%s" % (p.get("suite", "fidelity"), p["type_label"]), p["op"], p["verdict"],
                ",".join(p.get("fallback_ops") or []) or "-", p.get("size_max"),
                p["ppl"].replace("|", "\\|")))
        out.append("")

    errs = [p for p in pts if p["verdict"] == "ERROR"]
    if errs:
        out.append("## Errors\n")
        by = Counter(p.get("error", "") for p in errs)
        for e, n in by.most_common():
            out.append("- **%d points** — `%s`" % (n, e))
        out.append("\nAffected: %s\n" % ", ".join(sorted({p["type_label"] for p in errs})))

    if run.get("missing_types"):
        out.append("## Untested types (coverage gap)\n")
        out.append("Not present in the dataset, so their pushdown behaviour is unverified: "
                   "%s.\n" % ", ".join("`%s`" % t for t in run["missing_types"]))
    print("\n".join(out))


if __name__ == "__main__":
    main()
