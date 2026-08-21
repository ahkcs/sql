#!/usr/bin/env python3
"""Parallel bulk loader for full-scale mock-* population.

Multiprocessing workers, each holding ONE persistent keep-alive HTTPS connection,
posting filter_path=took,errors bulk batches with deterministic _id per doc
(generator.build_doc_at) so the parallel stream matches mock_data.expected exactly.

For the one-time ~1TB/node load. load.py stays the simple path for small/dev loads.

Usage:
  python -m mock_data.load_parallel --host https://EP --auth admin:PW \
      --docs-per-index 5000000 --shards 12 --workers 8
  python -m mock_data.load_parallel --docs-per-index 1000000 --workers 8 --dry-run
"""
import argparse
import base64
import http.client
import json
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from urllib.parse import urlsplit

from . import generator, load, wide_schema
from .indices import index_docs, seed_for

BATCH_DOCS = 2000
_TRANSIENT = (http.client.HTTPException, ConnectionError, TimeoutError, OSError)


def _connect(host):
    u = urlsplit(host)
    if u.scheme == "https":
        return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=180)
    return http.client.HTTPConnection(u.hostname, u.port or 9200, timeout=180)


def _worker(task):
    """Load doc indices [lo, hi) of one index over a persistent connection.
    Returns (index, loaded_count, error_or_None)."""
    host, index, sourcetype, seed, lo, hi, auth_hdr, wide = task
    headers = {"Content-Type": "application/json"}
    if auth_hdr:
        headers["Authorization"] = auth_hdr
    path = "/%s/_bulk?filter_path=took,errors" % index
    conn = _connect(host)

    def flush(ndjson):
        nonlocal conn
        last = None
        for attempt in range(5):
            try:
                conn.request("POST", path, body=ndjson, headers=headers)
                r = conn.getresponse()
                body = r.read().decode()
                if r.status >= 300 or '"errors":true' in body:
                    return "status=%d %s" % (r.status, body[:200])
                return None
            except _TRANSIENT as e:                 # drop/timeout: reconnect + back off
                last = e
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2 ** attempt)
                conn = _connect(host)
        return "transient after 5 retries: %s" % last

    batch, count = [], 0
    for i in range(lo, hi):
        batch.append('{"index":{"_id":"%d"}}' % i)
        batch.append(json.dumps(generator.build_doc_at(seed, i, sourcetype, wide)))
        if len(batch) >= BATCH_DOCS * 2:
            err = flush("\n".join(batch) + "\n")
            if err:
                conn.close()
                return (index, count, err)
            count += len(batch) // 2
            batch = []
    if batch:
        err = flush("\n".join(batch) + "\n")
        if err:
            conn.close()
            return (index, count, err)
        count += len(batch) // 2
    conn.close()
    return (index, count, None)


def _build_tasks(host, plan, workers, seed, auth_hdr, wide=False):
    """Split each index's [0,n) into ~workers contiguous slices."""
    tasks = []
    for name, (st, n) in plan.items():
        step = max(1, math.ceil(n / workers))
        for lo in range(0, n, step):
            tasks.append((host, name, st, seed_for(name, seed), lo, min(lo + step, n), auth_hdr, wide))
    return tasks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:9200")
    ap.add_argument("--auth")
    ap.add_argument("--scale-divisor", type=int, default=1)
    ap.add_argument("--docs-per-index", type=int)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--shards", type=int, default=12)
    ap.add_argument("--replicas", type=int, default=1)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--only", action="append")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--narrow", action="store_true",
                    help="use the 75-field base instead of the default ~3000-field wide schema")
    args = ap.parse_args()

    plan = index_docs(args.scale_divisor, args.docs_per_index)
    if args.only:
        plan = {k: v for k, v in plan.items() if k in set(args.only)}
    auth_hdr = ("Basic " + base64.b64encode(args.auth.encode()).decode()) if args.auth else None
    tasks = _build_tasks(args.host, plan, args.workers, args.seed, auth_hdr, not args.narrow)

    if args.dry_run:
        for name, (st, n) in plan.items():
            slices = [t for t in tasks if t[1] == name]
            print("%-20s sourcetype=%-10s docs=%-10d slices=%d (%s)"
                  % (name, st, n, len(slices), ", ".join("%d-%d" % (t[4], t[5]) for t in slices[:4])
                     + (" ..." if len(slices) > 4 else "")))
        print("\nDRY RUN: %d indices, %d docs, %d tasks, %d workers"
              % (len(plan), sum(n for _, n in plan.values()), len(tasks), args.workers))
        return

    mappings = load.load_mappings(load.SCHEMA if args.narrow else wide_schema.WIDE_TEMPLATE)
    tfl = 2000 if args.narrow else wide_schema.TOTAL_FIELDS_LIMIT
    for name in plan:
        load.create_index(args.host, name, mappings, args.shards, args.replicas, args.auth, total_fields_limit=tfl)

    totals, errors, t0 = {}, [], time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_worker, t) for t in tasks]
        for fut in as_completed(futs):
            index, count, err = fut.result()
            totals[index] = totals.get(index, 0) + count
            if err:
                errors.append((index, err))
                print("  ERROR %s: %s" % (index, err), file=sys.stderr)
            else:
                print("  %s: +%d (running %d)" % (index, count, totals[index]))

    for name in plan:
        load.req("POST", "%s/%s/_refresh" % (args.host, name), auth=args.auth)
    dt = time.time() - t0
    total = sum(totals.values())
    print("DONE. %d indices, %d docs in %.0fs (%.0f docs/s), %d errors."
          % (len(plan), total, dt, total / dt if dt else 0, len(errors)))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
