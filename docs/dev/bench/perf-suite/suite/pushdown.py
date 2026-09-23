#!/usr/bin/env python3
"""Type x operation pushdown matrix (plan §2.1, type-coverage axis).

The latency catalogue only ever groups/filters on keyword, long and date, so it
misses the class of bug where an operation silently falls off the pushdown path
because of the FIELD TYPE. Canonical example found 2026-09-23:

    stats count() by body        -- body is bare `text`

pushes no aggregation: the plan degrades to a coordinator-side
EnumerableAggregate fed by an UNBOUNDED scan (requestedTotalSize=2147483647),
i.e. every matching document's field value is shipped to the coordinator. 52 s at
1 h vs 0.45 s for the same query on a keyword field, and it grows linearly with
the window.

This module asserts pushdown from `_explain` instead of inferring it from
latency: explain costs ~50 ms and is scale-independent, so the whole matrix can
be swept cheaply and the verdict is unambiguous (`AGGREGATION->` in the physical
plan vs an `Enumerable*` fallback). Run the latency suite only on what fails
here.

Usage:
  python3 -m suite.pushdown --host https://EP --as-user admin --out results/pushdown.json
  python3 -m suite.pushdown --list
"""
import argparse
import json
import os
import re

from . import identities, runinfo
from .runner import make_http

INDEX = "mock-mixed-pi"
TW = "| where @timestamp >= '2026-04-10 23:00:00' "

# label, field, mapped type, class (drives which ops apply + literal choice).
# Only types PRESENT in the fidelity dataset; see MISSING_TYPES for the gap.
TYPE_FIELDS = [
    ("keyword_lowcard", "severityText", "keyword", "str"),
    ("keyword_highcard", "resource.attributes.k8s.pod.name", "keyword", "str"),
    ("text_bare", "body", "text (no subfield)", "str"),
    ("text_multifield", "log.method", "text (+.keyword)", "str"),
    ("text_subfield", "log.method.keyword", "keyword (subfield)", "str"),
    ("long", "attributes.obs_body_length", "long", "num"),
    ("integer", "severityNumber", "integer", "num"),
    ("byte", "flags", "byte", "num"),
    ("date", "@timestamp", "date", "date"),
    ("object", "log.mdc", "object", "obj"),
]

# Types NOT in the dataset — pushdown behaviour for these is untested (needs a
# mapping change + reload, or a small side index).
MISSING_TYPES = ["boolean", "double", "float", "scaled_float", "half_float",
                 "unsigned_long", "ip", "nested", "flattened", "wildcard", "alias"]

LITERAL = {"str": "'x'", "num": "1", "date": "'2026-04-10 23:00:00'", "obj": "'x'"}

# op, template, applicable classes. {f} = field, {lit} = type-appropriate literal.
OPS = [
    ("groupby", "stats count() by {f}", ("str", "num", "date", "obj")),
    ("dc", "stats dc({f})", ("str", "num", "date")),
    ("count_field", "stats count({f})", ("str", "num", "date")),
    ("min_max", "stats min({f}) as mn, max({f}) as mx", ("str", "num", "date")),
    ("avg_sum", "stats avg({f}) as a, sum({f}) as s", ("num",)),
    ("filter_eq", "where {f} = {lit} | head 100", ("str", "num", "date")),
    ("filter_range", "where {f} > {lit} | head 100", ("num", "date")),
    ("sort", "sort {f} | head 100", ("str", "num", "date")),
    ("dedup", "dedup {f} | head 100", ("str", "num", "date")),
    ("top", "top 10 {f}", ("str", "num", "date")),
    ("rare", "rare {f}", ("str", "num", "date")),
    ("like", "where like({f}, '%x%') | head 100", ("str",)),
    ("isnull", "where isnull({f}) | head 100", ("str", "num", "date")),
    ("bin", "bin {f} span=5 | stats count() by {f}", ("num",)),
    ("span_time", "stats count() by span({f}, 1h)", ("date",)),
]

UNBOUNDED = "requestedTotalSize=2147483647"
_ENUM = re.compile(r"Enumerable(Aggregate|Sort|Limit|Calc|Join|Window)")
_PUSH_CTX = re.compile(r"PushDownContext=\[\[(.*?)\]\s*,\s*OpenSearchRequestBuilder", re.S)

# Ops whose real cost is the reduction, so they are only safe if AGGREGATION pushes.
# top/rare/dedup always add a coordinator-side Window; that is cheap when the
# grouped result is what crosses the wire, ruinous when raw rows do.
AGG_CLASS = ("groupby", "dc", "count_field", "min_max", "avg_sum", "bin", "span_time",
             "top", "rare", "dedup")
FILTER_CLASS = ("filter_eq", "filter_range", "like", "isnull")


def build_matrix():
    out = []
    for label, field, mtype, cls in TYPE_FIELDS:
        for op, tmpl, classes in OPS:
            if cls not in classes:
                continue
            lit = LITERAL[cls]
            q = tmpl.replace("{f}", field).replace("{lit}", lit)
            out.append({"type_label": label, "field": field, "mapped_type": mtype,
                        "op": op, "literal": lit,
                        "ppl": "source=%s %s| %s" % (INDEX, TW, q)})
    return out


def classify(physical, op, literal=None):
    """Derive a pushdown verdict from the physical plan.

    Flags are read from the PushDownContext only, so unrelated plan text cannot
    fake a pushdown. `requestedTotalSize=MAX` is NOT by itself a danger sign: it
    is present on pushed aggregations too (which send size:0 and reduce
    server-side). It only matters when the reduction did *not* push, because then
    that many raw rows really do cross the wire.
    """
    m = _PUSH_CTX.search(physical)
    ctx = m.group(1) if m else ""
    pushed = {"agg": "AGGREGATION->" in ctx, "filter": "FILTER->" in ctx,
              "sort": "SORT->" in ctx, "limit": "LIMIT->" in ctx}
    fallback = sorted(set(_ENUM.findall(physical)))
    size_max = UNBOUNDED in physical

    # For filter ops the time-range WHERE is always pushed, so presence of
    # FILTER-> proves nothing about the op's own predicate: look for its literal.
    predicate_pushed = None
    if op in FILTER_CLASS:
        token = {"isnull": "IS NULL"}.get(op, (literal or "").strip("'"))
        predicate_pushed = bool(token) and token in ctx

    if op in AGG_CLASS:
        ok = pushed["agg"]
    elif op in FILTER_CLASS:
        ok = bool(predicate_pushed)
    elif op == "sort":
        ok = pushed["sort"]
    else:
        ok = pushed["agg"] or pushed["sort"]

    if ok:
        verdict = "PUSHED"
    else:
        # unbounded row flow = no pushed reduction and no pushed row cap
        verdict = ("FALLBACK_UNBOUNDED" if (size_max and not pushed["agg"] and not pushed["limit"])
                   else "FALLBACK")
    return {"verdict": verdict, "pushed": pushed, "predicate_pushed": predicate_pushed,
            "fallback_ops": fallback, "size_max": size_max}


def explain(http, ppl):
    status, body = http("POST", "/_plugins/_ppl/_explain", json.dumps({"query": ppl}))
    if status != 200:
        try:
            j = json.loads(body)
            return None, "%s: %s" % ((j.get("error") or {}).get("type"),
                                     ((j.get("error") or {}).get("reason") or "")[:160])
        except Exception:  # noqa: BLE001
            return None, body[:160]
    try:
        return (json.loads(body).get("calcite") or {}).get("physical") or "", None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--auth")
    ap.add_argument("--as-user", dest="as_user")
    ap.add_argument("--out", default="results/pushdown.json")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    matrix = build_matrix()
    if args.list:
        for m in matrix:
            print("%-18s %-13s %s" % (m["type_label"], m["op"], m["ppl"]))
        print("\n%d points (%d types x ops)" % (len(matrix), len(TYPE_FIELDS)))
        return
    if not args.host:
        ap.error("--host required (or --list)")

    http = make_http(args.host, identities.auth_for(args.as_user, args.auth), timeout=60)
    result = {"run": runinfo.header("pushdown", args.host, as_user=args.as_user,
                                    index=INDEX, points=len(matrix),
                                    missing_types=MISSING_TYPES),
              "points": []}
    for m in matrix:
        physical, err = explain(http, m["ppl"])
        rec = dict(m)
        if err:
            rec.update(verdict="ERROR", error=err)
        else:
            rec.update(classify(physical, m["op"], m.get("literal")))
            rec["physical"] = physical
        result["points"].append(rec)
        print("%-18s %-13s %s%s" % (m["type_label"], m["op"], rec["verdict"],
                                    "  " + rec.get("error", "") if err else ""))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    from collections import Counter
    print("\n== %s ==" % dict(Counter(p["verdict"] for p in result["points"])))
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
