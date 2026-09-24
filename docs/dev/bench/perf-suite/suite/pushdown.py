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

FIDELITY_INDEX = "mock-mixed-pi"
TYPES_INDEX = "mock-types"
TW = "| where @timestamp >= '2026-04-10 23:00:00' "

# label, field, mapped type, class (drives which ops apply + literal choice).
FIDELITY_FIELDS = [
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

# The eleven types the fidelity dataset lacks, carried by mock-types
# (mock_data/types_index.py). env_* is the same VALUE under three mappings, which
# isolates mapping from data for the customer's slow `stats count() by env`.
TYPES_FIELDS = [
    ("env_text_bare", "env_text", "text (no subfield)", "str"),
    ("env_keyword", "env_kw", "keyword", "str"),
    ("env_multifield", "env_multi", "text (+.keyword)", "str"),
    ("env_alias", "env_alias", "alias -> keyword", "str"),
    ("boolean", "flag_bool", "boolean", "bool"),
    ("double", "val_double", "double", "num"),
    ("float", "val_float", "float", "num"),
    ("half_float", "val_half", "half_float", "num"),
    ("scaled_float", "val_scaled", "scaled_float", "num"),
    ("unsigned_long", "val_ulong", "unsigned_long", "num"),
    ("ip", "client_ip", "ip", "ip"),
    ("wildcard", "path_wildcard", "wildcard", "wild"),
    ("flat_object_leaf", "payload_flat.region", "flat_object (leaf)", "flat"),
    ("nested_leaf", "events.name", "nested (leaf)", "nested"),
]

SUITES = {"fidelity": (FIDELITY_INDEX, FIDELITY_FIELDS),
          "types": (TYPES_INDEX, TYPES_FIELDS)}

LITERAL = {"str": "'x'", "num": "1", "date": "'2026-04-10 23:00:00'", "obj": "'x'",
           "bool": "true", "ip": "'10.0.0.1'", "wild": "'/auth/v1/1'",
           "flat": "'us-east-1'", "nested": "'auth'"}

# op, template, applicable classes. {f} = field, {lit} = type-appropriate literal.
_ALL = ("str", "num", "date", "obj", "bool", "ip", "wild", "flat", "nested")
_SCALAR = ("str", "num", "date", "bool", "ip", "wild", "flat")

OPS = [
    ("groupby", "stats count() by {f}", _ALL),
    ("dc", "stats dc({f})", _SCALAR),
    ("count_field", "stats count({f})", _SCALAR),
    ("min_max", "stats min({f}) as mn, max({f}) as mx", ("str", "num", "date", "ip")),
    ("avg_sum", "stats avg({f}) as a, sum({f}) as s", ("num",)),
    ("filter_eq", "where {f} = {lit} | head 100", _SCALAR),
    ("filter_range", "where {f} > {lit} | head 100", ("num", "date")),
    ("sort", "sort {f} | head 100", _SCALAR),
    ("dedup", "dedup {f} | head 100", ("str", "num", "date", "bool", "ip")),
    ("top", "top 10 {f}", _SCALAR),
    ("rare", "rare {f}", _SCALAR),
    ("like", "where like({f}, '%x%') | head 100", ("str", "wild")),
    ("isnull", "where isnull({f}) | head 100", _SCALAR),
    ("bin", "bin {f} span=5 | stats count() by {f}", ("num",)),
    ("span_time", "stats count() by span({f}, 1h)", ("date",)),
    ("cidr", "where cidrmatch({f}, '10.0.0.0/8') | head 100", ("ip",)),
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


def build_matrix(suites=("fidelity",)):
    out = []
    for suite in suites:
        index, fields = SUITES[suite]
        for label, field, mtype, cls in fields:
            for op, tmpl, classes in OPS:
                if cls not in classes:
                    continue
                lit = LITERAL[cls]
                q = tmpl.replace("{f}", field).replace("{lit}", lit)
                out.append({"suite": suite, "index": index, "type_label": label,
                            "field": field, "mapped_type": mtype, "op": op, "literal": lit,
                            "ppl": "source=%s %s| %s" % (index, TW, q)})
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
    ap.add_argument("--suite", default="fidelity",
                    help="comma-separated: fidelity,types (types needs mock-types loaded "
                         "via `python3 -m mock_data.types_index`)")
    ap.add_argument("--out", default="results/pushdown.json")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    suites = tuple(x.strip() for x in args.suite.split(",") if x.strip())
    bad = [s for s in suites if s not in SUITES]
    if bad:
        raise SystemExit("unknown suite(s) %s; known: %s" % (bad, sorted(SUITES)))
    matrix = build_matrix(suites)
    if args.list:
        for m in matrix:
            print("%-9s %-18s %-13s %s" % (m["suite"], m["type_label"], m["op"], m["ppl"]))
        print("\n%d points across suites %s" % (len(matrix), list(suites)))
        return
    if not args.host:
        ap.error("--host required (or --list)")

    http = make_http(args.host, identities.auth_for(args.as_user, args.auth), timeout=60)
    result = {"run": runinfo.header("pushdown", args.host, as_user=args.as_user,
                                    suites=list(suites), points=len(matrix),
                                    indices=sorted({m["index"] for m in matrix})),
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
        print("%-9s %-18s %-13s %s%s" % (m["suite"], m["type_label"], m["op"], rec["verdict"],
                                    "  " + rec.get("error", "") if err else ""))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    from collections import Counter
    print("\n== %s ==" % dict(Counter(p["verdict"] for p in result["points"])))
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
