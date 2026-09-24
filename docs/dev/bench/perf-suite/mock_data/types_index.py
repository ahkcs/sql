#!/usr/bin/env python3
"""`mock-types` — a small index carrying one field per mapped type.

Why a separate index. The fidelity dataset only contains keyword, text, long,
integer, byte, date and object, so the type x operation pushdown matrix
(`suite/pushdown.py`) cannot say anything about the other eleven types. Pushdown
is decided from the MAPPING, not the data volume, so those questions are
scale-independent: a small index answers them for ~0.1% of the cluster's disk and
a few minutes of loading, with no risk to the 1.83B-doc baseline.

The `env_*` trio is the point of the index as much as the exotic types. A
customer's `stats count() by env` is slow when `env` is bare `text`, and the three
fields here isolate exactly that, holding the VALUES identical:

    env_text   text, no subfield   -> the customer's shape (no doc_values)
    env_kw     keyword             -> the control
    env_multi  text + .keyword     -> the workaround

`@timestamp` spans the same 7-day window as the fidelity data (ending
distributions.ANCHOR_MS), so the suite's existing time filters work unchanged.

Usage:
  python3 -m mock_data.types_index --host https://EP --auth admin:PW --docs 10000000
  python3 -m mock_data.types_index --dry-run          # print a sample doc
"""
import argparse
import json
import random
import sys

from . import distributions as dist
from .load import create_index, req

INDEX = "mock-types"

ENVS = ["prod", "staging", "dev", "qa", "canary", "sandbox"]
REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-2"]
SEVERITIES = ["INFO", "WARN", "ERROR", "DEBUG"]
EVENT_NAMES = ["auth", "fetch", "write", "evict", "retry"]

MAPPING = {
    "properties": {
        "@timestamp": {"type": "date"},
        # controls: types the fidelity set already covers, so results are comparable
        "severityText": {"type": "keyword"},
        "count_long": {"type": "long"},
        "body": {"type": "text"},
        # the env trio -- same values, three mappings
        "env_text": {"type": "text"},
        "env_kw": {"type": "keyword"},
        "env_multi": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "env_alias": {"type": "alias", "path": "env_kw"},
        # the eleven types missing from the fidelity dataset
        "flag_bool": {"type": "boolean"},
        "val_double": {"type": "double"},
        "val_float": {"type": "float"},
        "val_half": {"type": "half_float"},
        "val_scaled": {"type": "scaled_float", "scaling_factor": 100},
        "val_ulong": {"type": "unsigned_long"},
        "client_ip": {"type": "ip"},
        "path_wildcard": {"type": "wildcard"},
        "payload_flat": {"type": "flattened"},
        "events": {"type": "nested",
                   "properties": {"name": {"type": "keyword"},
                                  "code": {"type": "integer"}}},
    }
}


def make_doc(rng, ts_ms):
    env = rng.choice(ENVS)
    return {
        "@timestamp": ts_ms,
        "severityText": rng.choice(SEVERITIES),
        "count_long": rng.randint(0, 5_000_000),
        "body": "svc=%s op=%s latency=%dms status=%d %s" % (
            rng.choice(EVENT_NAMES), rng.choice(["get", "put", "scan"]),
            rng.randint(1, 4000), rng.choice([200, 404, 500, 503]),
            rng.choice(["ok", "timeout", "refused", "throttled"])),
        # identical value, three mappings -> isolates mapping from data
        "env_text": env,
        "env_kw": env,
        "env_multi": env,
        "flag_bool": rng.random() < 0.3,
        "val_double": round(rng.uniform(0, 10_000), 6),
        "val_float": round(rng.uniform(0, 1_000), 3),
        "val_half": round(rng.uniform(0, 100), 2),
        "val_scaled": round(rng.uniform(0, 500), 2),
        "val_ulong": rng.randint(0, 2**63) + 2**63 if rng.random() < 0.1 else rng.randint(0, 10**12),
        "client_ip": "%d.%d.%d.%d" % (rng.randint(10, 210), rng.randint(0, 255),
                                      rng.randint(0, 255), rng.randint(1, 254)),
        "path_wildcard": "/%s/%s/%d" % (rng.choice(EVENT_NAMES),
                                        rng.choice(["v1", "v2", "internal"]),
                                        rng.randint(1, 9999)),
        "payload_flat": {"region": rng.choice(REGIONS), "retries": rng.randint(0, 5),
                         "cache": rng.choice(["hit", "miss"])},
        "events": [{"name": rng.choice(EVENT_NAMES), "code": rng.randint(200, 599)}
                   for _ in range(rng.randint(1, 3))],
    }


def generate(n, seed=1337, window_days=7):
    """Docs with @timestamp spread uniformly over the same window the fidelity
    dataset uses, so existing time filters select a proportional slice."""
    rng = random.Random(seed)
    span_ms = window_days * 86400 * 1000
    lo = dist.ANCHOR_MS - span_ms
    for _ in range(n):
        yield make_doc(rng, rng.randrange(lo, dist.ANCHOR_MS))


def bulk_load(host, index, ndocs, seed, auth, batch_size=5000):
    batch, done = [], 0
    for i, doc in enumerate(generate(ndocs, seed=seed)):
        batch.append('{"index":{"_id":"%d"}}' % i)
        batch.append(json.dumps(doc))
        if len(batch) >= batch_size * 2:
            done += _flush(host, index, batch, auth)
            batch = []
            if done % 500_000 == 0:
                print("    %s: %d docs" % (index, done), flush=True)
    if batch:
        done += _flush(host, index, batch, auth)
    return done


def _flush(host, index, batch, auth):
    status, resp = req("POST", "%s/%s/_bulk?filter_path=took,errors" % (host, index),
                       "\n".join(batch) + "\n", auth=auth)
    if status >= 300 or '"errors":true' in resp:
        print("  bulk into %s failed %s: %s" % (index, status, resp[:300]), file=sys.stderr)
        sys.exit(1)
    return len(batch) // 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--auth")
    ap.add_argument("--docs", type=int, default=10_000_000)
    ap.add_argument("--shards", type=int, default=4)
    ap.add_argument("--replicas", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--index", default=INDEX)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        print(json.dumps(next(iter(generate(1, seed=args.seed))), indent=2))
        print("\nmapped types: %s" % sorted({
            v.get("type") for v in MAPPING["properties"].values()}))
        return
    if not args.host:
        ap.error("--host required (or --dry-run)")

    print("creating %s (%d shards, %d replicas)" % (args.index, args.shards, args.replicas))
    create_index(args.host, args.index, MAPPING, args.shards, args.replicas, args.auth,
                 total_fields_limit=200)
    print("loading %d docs" % args.docs)
    n = bulk_load(args.host, args.index, args.docs, args.seed, args.auth)
    req("PUT", "%s/%s/_settings" % (args.host, args.index),
        json.dumps({"index": {"refresh_interval": "1s"}}), auth=args.auth)
    req("POST", "%s/%s/_refresh" % (args.host, args.index), auth=args.auth)
    s, body = req("GET", "%s/%s/_count" % (args.host, args.index), auth=args.auth)
    print("loaded %d docs; _count -> %s %s" % (n, s, body[:120]))


if __name__ == "__main__":
    main()
