#!/usr/bin/env python3
"""Drive a parallel mock-* ingest across the EC2 loader fleet over SSM.

Each worker gets a DISJOINT set of indices (`--only`), because `create_index`
DELETEs before it PUTs — two workers on the same index would wipe each other's
docs. Work is split by index, so the wall clock is (indices per worker) x
(docs per index) / per-worker throughput.

The load runs as a systemd unit, not a backgrounded child of the SSM command, so
it survives the Run Command finishing (a plain `nohup ... &` gets reaped).

Usage:
  python3 fleet_load.py --docs-per-index 183000000 --shards 28          # start
  python3 fleet_load.py --status                                        # progress + rate
  python3 fleet_load.py --stop                                          # stop every worker

No third-party deps: shells out to the AWS CLI, like the rest of infra/aws.
"""
import argparse
import json
import subprocess
import sys
import time

REGION = "us-east-1"
UNIT = "ppl-fleet-load"
PW_PARAM = "/ppl-perf-tier2/fgac-password"
ENDPOINT = "search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com"
CODE = "s3://ppl-perf-tier2-loader-924196221507/perf-suite.tgz"
NAME_TAGS = "ppl-perf-tier2-loader,ppl-perf-tier2-loader-fleet"
INDICES = ["mock-kv-pi", "mock-mixed-pi", "mock-nested-cape", "mock-json-dd",
           "mock-json-ecs", "mock-json-spring", "mock-kv-quoted-wi", "mock-json-fid",
           "mock-json-http", "mock-multi-format"]


def aws(*args, parse=True):
    out = subprocess.check_output(["aws", "--region", REGION] + list(args), text=True)
    return json.loads(out) if parse and out.strip() else out


def workers():
    """Running loader instances that SSM can reach, oldest first (stable split)."""
    inst = aws("ec2", "describe-instances",
               "--filters", "Name=tag:Name,Values=%s" % NAME_TAGS,
               "Name=instance-state-name,Values=running",
               "--query", "Reservations[].Instances[].[InstanceId,LaunchTime]",
               "--output", "json")
    online = {i["InstanceId"] for i in aws(
        "ssm", "describe-instance-information",
        "--query", "InstanceInformationList[?PingStatus=='Online']", "--output", "json")}
    return [i for i, _ in sorted(inst, key=lambda x: x[1]) if i in online]


def split(items, n):
    """Round-robin so each worker gets a similar index count."""
    buckets = [[] for _ in range(n)]
    for k, item in enumerate(items):
        buckets[k % n].append(item)
    return [b for b in buckets if b]


def send(instance, commands, comment):
    payload = {"InstanceIds": [instance], "DocumentName": "AWS-RunShellScript",
               "Comment": comment[:100], "TimeoutSeconds": 600,
               "Parameters": {"commands": commands}}
    path = "/tmp/ssm-%s.json" % instance
    with open(path, "w") as f:
        json.dump(payload, f)
    return aws("ssm", "send-command", "--cli-input-json", "file://%s" % path,
               "--query", "Command.CommandId", "--output", "text", parse=False).strip()


def load_cmd(only, docs, shards, workers_per_host):
    onlys = " ".join("--only %s" % i for i in only)
    inner = ("PW=$(aws ssm get-parameter --name %s --with-decryption --region %s "
             "--query Parameter.Value --output text); "
             "exec python3 -u -m mock_data.load_parallel --host https://%s "
             "--auth \"admin:$PW\" %s --docs-per-index %d --shards %d --replicas 1 "
             "--workers %d > /var/log/fleet-load.log 2>&1"
             % (PW_PARAM, REGION, ENDPOINT, onlys, docs, shards, workers_per_host))
    return [
        "set -x",
        "rm -rf /opt/perf-suite && mkdir -p /opt/perf-suite && cd /opt/perf-suite && "
        "aws s3 cp %s perf-suite.tgz --region %s && tar xzf perf-suite.tgz" % (CODE, REGION),
        "systemctl reset-failed %s 2>/dev/null; true" % UNIT,
        "systemd-run --unit=%s --collect --property=WorkingDirectory=/opt/perf-suite "
        "bash -c '%s'" % (UNIT, inner),
        "sleep 10; systemctl is-active %s; tail -5 /var/log/fleet-load.log" % UNIT,
    ]


def cluster_docs():
    pw = aws("ssm", "get-parameter", "--name", PW_PARAM, "--with-decryption",
             "--query", "Parameter.Value", "--output", "text", parse=False).strip()
    out = subprocess.check_output(
        ["curl", "-s", "-u", "admin:%s" % pw,
         "https://%s/mock-*/_stats/docs,store?filter_path=_all.primaries" % ENDPOINT], text=True)
    p = json.loads(out)["_all"]["primaries"]
    return p["docs"]["count"], p["store"]["size_in_bytes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-per-index", type=int, default=183_000_000)
    ap.add_argument("--shards", type=int, default=28)
    ap.add_argument("--workers-per-host", type=int, default=24)
    ap.add_argument("--only", action="append", help="restrict the fleet to these indices")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    hosts = workers()
    if not hosts:
        sys.exit("no running+Online loader instances tagged %s" % NAME_TAGS)

    if args.status:
        d0, b0 = cluster_docs()
        time.sleep(60)
        d1, b1 = cluster_docs()
        rate = (d1 - d0) / 60.0
        total = args.docs_per_index * len(args.only or INDICES)
        print("workers: %s" % ", ".join(hosts))
        print("docs {:,} / {:,}  primaries {:.0f} GB  {:.2f} KB/doc"
              .format(d1, total, b1 / 1e9, b1 / max(d1, 1) / 1024))
        if rate > 0:
            print("rate {:,.0f} docs/s  ETA {:.2f} h".format(rate, (total - d1) / rate / 3600))
        for h in hosts:
            cid = send(h, ["systemctl is-active %s || true" % UNIT,
                           "tail -2 /var/log/fleet-load.log 2>/dev/null || true"], "status")
            print("  %s -> command %s" % (h, cid))
        return

    if args.stop:
        for h in hosts:
            print("%s stop -> %s" % (h, send(h, ["systemctl stop %s || true" % UNIT], "stop")))
        return

    groups = split(args.only or INDICES, len(hosts))
    for host, only in zip(hosts, groups):
        cmds = load_cmd(only, args.docs_per_index, args.shards, args.workers_per_host)
        if args.dry_run:
            print("%s: %s\n  %s\n" % (host, only, cmds[-2]))
            continue
        print("%s: %-52s -> command %s"
              % (host, ",".join(only), send(host, cmds, "fleet load %s" % ",".join(only))))
    if not args.dry_run:
        print("\ntotal target: {:,} docs across {} indices on {} workers"
              .format(args.docs_per_index * len(args.only or INDICES),
                      len(args.only or INDICES), len(hosts)))


if __name__ == "__main__":
    main()
