#!/bin/bash
# Wait for the fidelity-scale ingest to be complete AND settled, then run the
# three pillars unattended. Lives on the worker whose role can PUT to the results
# bucket (the original loader), and is decoupled from the ingest units -- it only
# reads cluster state, so it does not care which worker loaded what.
#
# Gate (all must hold, then hold again after a quiet period):
#   * cluster green
#   * all 10 mock-* indices at >= TARGET docs (primaries)
#   * merges.current == 0 across all nodes  -- pillars on a merging cluster
#     measure the merge, not the query
#
#   pillars_gate.sh [--target 183000000] [--indices 10] [--tag fidelity-1d]
#                   [--quiet 900] [--force]
set -u
EP=https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com
REGION=us-east-1
PW_PARAM=/ppl-perf-tier2/fgac-password
TARGET=183000000; NIDX=10; TAG=fidelity-1d; QUIET_S=900; FORCE=0
MAX_WAIT_S=$((14 * 3600))

while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --indices) NIDX="$2"; shift 2 ;;
    --tag) TAG="$2"; shift 2 ;;
    --quiet) QUIET_S="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    *) echo "unknown arg $1"; exit 2 ;;
  esac
done

PW=$(aws ssm get-parameter --name "$PW_PARAM" --with-decryption --region "$REGION" \
      --query Parameter.Value --output text) || exit 1
say() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

check_ready() {
  EP="$EP" PW="$PW" TARGET="$TARGET" NIDX="$NIDX" python3 - <<'PY'
import base64, json, os, sys, urllib.request

ep, pw = os.environ["EP"], os.environ["PW"]
target, nidx = int(os.environ["TARGET"]), int(os.environ["NIDX"])
auth = "Basic " + base64.b64encode(("admin:" + pw).encode()).decode()


def get(path):
    req = urllib.request.Request(ep + path, headers={"Authorization": auth})
    return json.load(urllib.request.urlopen(req, timeout=90))


h = get("/_cluster/health")
if h["status"] != "green":
    sys.exit("health=%s unassigned=%s" % (h["status"], h.get("unassigned_shards")))

st = get("/mock-*/_stats/docs?level=indices&filter_path=indices.*.primaries.docs.count")
idx = st.get("indices", {})
if len(idx) != nidx:
    sys.exit("indices=%d want %d" % (len(idx), nidx))
short = {k: v["primaries"]["docs"]["count"] for k, v in idx.items()
         if v["primaries"]["docs"]["count"] < target}
if short:
    done = sum(v["primaries"]["docs"]["count"] for v in idx.values())
    sys.exit("loading: %d/%d docs, %d indices short (min %s)"
             % (done, target * nidx, len(short), min(short.values())))

m = get("/_nodes/stats/indices?filter_path=nodes.*.indices.merges.current")
cur = sum(n["indices"]["merges"]["current"] for n in m["nodes"].values())
if cur:
    sys.exit("merges.current=%d" % cur)
print("READY")
PY
}

waited=0
while :; do
  if [ "$FORCE" = 1 ] || out=$(check_ready 2>&1); then
    say "gate open (${out:-forced}); quiet period ${QUIET_S}s"
    sleep "$QUIET_S"
    if [ "$FORCE" = 1 ] || out=$(check_ready 2>&1); then
      break
    fi
    say "regressed during quiet period: $out"
  else
    say "not ready: $out"
  fi
  sleep 120; waited=$((waited + 120))
  [ $waited -gt $MAX_WAIT_S ] && { say "FAIL: gate never opened in ${MAX_WAIT_S}s"; exit 1; }
done

RUN=""
for c in /opt/perf-suite-wide/infra/aws/run_pillars.sh /opt/perf-suite/infra/aws/run_pillars.sh; do
  [ -f "$c" ] && RUN="$c" && break
done
[ -n "$RUN" ] || { say "FAIL: run_pillars.sh not found"; exit 1; }

say "starting pillars: TAG=$TAG DOCS=$TARGET via $RUN"
TAG="$TAG" DOCS="$TARGET" bash "$RUN"
rc=$?
say "pillars exited rc=$rc"
echo "pillars TAG=$TAG rc=$rc $(date -u +%FT%TZ)" >> /opt/PIPELINE_DONE
exit $rc
