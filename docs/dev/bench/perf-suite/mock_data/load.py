#!/usr/bin/env python3
"""Idempotent bulk loader for the mock-* indices.

Reads the mapping from schemas/mock-index-template.json, (re)creates each mock
index as a plain index (Tier-1 dev; data-stream template is for Tier-2 fidelity),
and bulk-loads deterministic docs from generator.py.

Usage:
  # tiny local dev set (Tier-1 counts / 5000), against local docker
  python -m mock_data.load --host http://localhost:9200 --auth admin:admin --scale-divisor 5000

  # fixed count per index, single index, dry run (no cluster needed)
  python -m mock_data.load --docs-per-index 2000 --only mock-json-http --dry-run

  # against os35 smoke domain (FGAC basic auth)
  python -m mock_data.load --host https://search-...es.amazonaws.com --auth "admin:$OS35_PASS" --docs-per-index 5000
"""
import argparse
import base64
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request

from . import generator, wide_schema
from .indices import index_docs, seed_for

SCHEMA = os.path.join(os.path.dirname(__file__), "schemas", "mock-index-template.json")
BATCH_DOCS = 2000

_TRANSIENT = (urllib.error.URLError, http.client.IncompleteRead,
              http.client.RemoteDisconnected, ConnectionError, TimeoutError, OSError)


def req(method, url, body=None, auth=None, retries=5):
    data = body.encode() if isinstance(body, str) else body
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
    last = None
    for attempt in range(retries):
        r = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=180) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return e.code, e.read().decode()
        except _TRANSIENT as e:  # connection dropped mid-request: back off and retry
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
    return -1, "transient after %d retries: %s" % (retries, last)


def load_mappings(path=SCHEMA):
    with open(path) as f:
        tpl = json.load(f)
    return tpl["template"]["mappings"]


def create_index(host, index, mappings, shards, replicas, auth, total_fields_limit=2000):
    req("DELETE", "%s/%s" % (host, index), auth=auth)
    body = json.dumps({
        "settings": {"number_of_shards": shards, "number_of_replicas": replicas,
                     "refresh_interval": "-1", "index.mapping.total_fields.limit": total_fields_limit},
        "mappings": mappings,
    })
    status, resp = req("PUT", "%s/%s" % (host, index), body, auth=auth)
    if status >= 300:
        print("  create %s failed %d: %s" % (index, status, resp[:300]), file=sys.stderr)
        sys.exit(1)


def bulk_load(host, index, sourcetype, ndocs, seed, auth, wide=False):
    batch, done = [], 0
    # deterministic _id per doc -> a retried batch upserts (no dupes), and the
    # whole load is re-runnable without inflating counts.
    for i, doc in enumerate(generator.generate(ndocs, seed=seed, sourcetype=sourcetype, wide=wide)):
        batch.append('{"index":{"_id":"%d"}}' % i)
        batch.append(json.dumps(doc))
        if len(batch) >= BATCH_DOCS * 2:
            _flush(host, index, batch, auth)
            done += len(batch) // 2
            batch = []
            print("    %s: %d/%d" % (index, done, ndocs))
    if batch:
        _flush(host, index, batch, auth)
        done += len(batch) // 2
    return done


def _flush(host, index, batch, auth):
    # filter_path=took,errors -> a ~30-byte response instead of the full per-doc
    # items array (~900KB/batch), which was getting truncated (IncompleteRead) and
    # dominating load time. We only need to know if the batch errored.
    status, resp = req("POST", "%s/%s/_bulk?filter_path=took,errors" % (host, index),
                       "\n".join(batch) + "\n", auth=auth)
    if status >= 300 or '"errors":true' in resp:
        print("  bulk error %d into %s: %s" % (status, index, resp[:300]), file=sys.stderr)
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:9200")
    ap.add_argument("--auth", help="basic auth user:pass (SigV4/--target aws-iam is TODO)")
    ap.add_argument("--target", choices=["local", "aws"], default="local")
    ap.add_argument("--scale-divisor", type=int, default=5000,
                    help="Tier-1 count // this (ignored if --docs-per-index)")
    ap.add_argument("--docs-per-index", type=int, help="flat doc count per index")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--replicas", type=int, default=0)
    ap.add_argument("--only", action="append", help="restrict to these index names")
    ap.add_argument("--dry-run", action="store_true", help="print a sample doc, no HTTP")
    ap.add_argument("--narrow", action="store_true",
                    help="use the 75-field base instead of the default ~3000-field wide schema")
    args = ap.parse_args()

    plan = index_docs(args.scale_divisor, args.docs_per_index)
    if args.only:
        plan = {k: v for k, v in plan.items() if k in set(args.only)}
        if not plan:
            print("no matching indices in --only", file=sys.stderr); sys.exit(2)

    if args.dry_run:
        for name, (st, n) in plan.items():
            sample = next(generator.generate(1, seed=seed_for(name, args.seed), sourcetype=st, wide=not args.narrow))
            print("== %s  sourcetype=%s  docs=%d ==" % (name, st, n))
            print(json.dumps(sample, indent=2)[:1400])
        print("\nDRY RUN: %d indices, %d docs total"
              % (len(plan), sum(n for _, n in plan.values())))
        return

    mappings = load_mappings(SCHEMA if args.narrow else wide_schema.WIDE_TEMPLATE)
    tfl = 2000 if args.narrow else wide_schema.TOTAL_FIELDS_LIMIT
    total = 0
    for name, (st, n) in plan.items():
        create_index(args.host, name, mappings, args.shards, args.replicas, args.auth, total_fields_limit=tfl)
        loaded = bulk_load(args.host, name, st, n, seed_for(name, args.seed), args.auth, wide=not args.narrow)
        req("POST", "%s/%s/_refresh" % (args.host, name), auth=args.auth)
        total += loaded
        print("  seeded %s (%d docs, sourcetype=%s)" % (name, loaded, st))
    print("DONE. %d indices, %d docs total." % (len(plan), total))


if __name__ == "__main__":
    main()
