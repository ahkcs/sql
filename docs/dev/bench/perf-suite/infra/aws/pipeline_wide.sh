#!/bin/bash
# Unattended chain on a loader worker: wait out the in-flight 250M load, snapshot
# it, then ingest the fidelity-scale dataset. Runs as a systemd unit so it is
# independent of any dev shell -- the laptop can be off.
#
# One worker runs with --create-snapshot (it owns snapshot creation); the others
# just wait for that snapshot to reach SUCCESS before they start writing, so the
# 250M dataset is never destroyed before it is safely in S3.
#
#   pipeline_wide.sh --only mock-kv-pi,mock-json-dd --docs 183000000 --shards 28 \
#       [--create-snapshot] [--wait-unit ppl-wide-load]
#
# Guards: any failure exits non-zero BEFORE the destructive load starts, and the
# load only ever runs against this worker's own --only list.
set -u
EP=https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com
REGION=us-east-1
PW_PARAM=/ppl-perf-tier2/fgac-password
SNAP=mock-250m-wide
REPO=s3
ONLY=""; DOCS=183000000; SHARDS=28; WORKERS=24; CREATE=0; WAIT_UNIT=""
MAX_WAIT_S=$((10 * 3600))

while [ $# -gt 0 ]; do
  case "$1" in
    --only) ONLY="$2"; shift 2 ;;
    --docs) DOCS="$2"; shift 2 ;;
    --shards) SHARDS="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --create-snapshot) CREATE=1; shift ;;
    --wait-unit) WAIT_UNIT="$2"; shift 2 ;;
    *) echo "unknown arg $1"; exit 2 ;;
  esac
done
[ -n "$ONLY" ] || { echo "--only is required"; exit 2; }

PW=$(aws ssm get-parameter --name "$PW_PARAM" --with-decryption --region "$REGION" \
      --query Parameter.Value --output text) || exit 1
say() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
api() { curl -s -u "admin:$PW" "$@"; }
snap_state() {
  api "$EP/_snapshot/$REPO/$SNAP" \
    | python3 -c 'import sys,json
try: print(json.load(sys.stdin)["snapshots"][0]["state"])
except Exception: print("MISSING")'
}

# 1. Wait for the in-flight load, if this worker is running one.
if [ -n "$WAIT_UNIT" ]; then
  say "waiting for unit $WAIT_UNIT"
  waited=0
  while systemctl is-active --quiet "$WAIT_UNIT"; do
    sleep 60; waited=$((waited + 60))
    [ $waited -gt $MAX_WAIT_S ] && { say "FAIL: $WAIT_UNIT still running after ${MAX_WAIT_S}s"; exit 1; }
  done
  grep -q '^DONE' /var/log/loader-wide.log \
    || { say "FAIL: $WAIT_UNIT ended without a DONE line -- not snapshotting a partial load"; exit 1; }
  say "$WAIT_UNIT finished: $(grep '^DONE' /var/log/loader-wide.log | tail -1)"
fi

# 2. Snapshot (creator) / wait for it (everyone else). This is the gate that
#    protects the 250M dataset from the load in step 3.
if [ "$CREATE" = 1 ]; then
  state=$(snap_state)
  if [ "$state" = MISSING ]; then
    say "creating snapshot $SNAP"
    api -XPUT "$EP/_snapshot/$REPO/$SNAP" -H 'Content-Type: application/json' \
      -d '{"indices":"mock-*","include_global_state":false}' &
  else
    say "snapshot already exists (state=$state)"
  fi
fi

say "waiting for snapshot $SNAP to reach SUCCESS"
waited=0
while :; do
  state=$(snap_state)
  case "$state" in
    SUCCESS) say "snapshot $SNAP SUCCESS"; break ;;
    IN_PROGRESS|MISSING|STARTED) : ;;
    *) say "FAIL: snapshot $SNAP state=$state"; exit 1 ;;
  esac
  sleep 60; waited=$((waited + 60))
  [ $waited -gt $MAX_WAIT_S ] && { say "FAIL: snapshot not done after ${MAX_WAIT_S}s"; exit 1; }
done

# 3. Fidelity-scale ingest for this worker's own indices (recreates them).
ONLY_ARGS=""
for i in $(echo "$ONLY" | tr ',' ' '); do ONLY_ARGS="$ONLY_ARGS --only $i"; done
say "starting fidelity load: $ONLY_ARGS docs/index=$DOCS shards=$SHARDS"
cd /opt/perf-suite || cd /opt/perf-suite-wide || exit 1
python3 -u -m mock_data.load_parallel --host "$EP" --auth "admin:$PW" \
  $ONLY_ARGS --docs-per-index "$DOCS" --shards "$SHARDS" --replicas 1 --workers "$WORKERS" \
  >> /var/log/fleet-load.log 2>&1
rc=$?
say "fidelity load exited rc=$rc"
tail -3 /var/log/fleet-load.log
echo "$ONLY rc=$rc $(date -u +%FT%TZ)" >> /opt/PIPELINE_DONE
exit $rc
