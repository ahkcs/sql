#!/bin/bash
# Run all three pillars from the EC2 loader (same-region, no 10-min shell limit).
# Downloads the suite bundle, reads the FGAC password from SSM, runs Perf/Load/
# Use-case against the team cluster, uploads results to S3, marks done.
#
# Defaults are the plan's release-run settings (§4.3 L3 = 30 min, full U cadences).
# Env knobs:
#   TAG=wide          results land in results/$TAG/ locally and in S3
#   FAST=1            short durations for a smoke pass (what the 75-field run used)
#   DOCS=25000000     docs per index, for the correctness/expected bookkeeping
set -x
BUCKET=ppl-perf-tier2-loader-924196221507
EP=https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com
TAG=${TAG:-wide}
DOCS=${DOCS:-25000000}
if [ -n "$FAST" ]; then
  L3_DUR=120; UC_ARGS="--think 3 --short"
else
  L3_DUR=1800; UC_ARGS="--think 25"      # plan §4.3 L3: 30 min at N=10; §4.4 full cadences
fi

cd /opt
aws s3 cp "s3://$BUCKET/perf-suite.tgz" . --region us-east-1
rm -rf ppl && mkdir ppl && tar xzf perf-suite.tgz -C ppl
PW=$(aws ssm get-parameter --name /ppl-perf-tier2/fgac-password --with-decryption --region us-east-1 --query Parameter.Value --output text)
export PYTHONPATH=/opt/ppl
export PYTHONUNBUFFERED=1
cd /opt/ppl && mkdir -p "results/$TAG"
rm -f /opt/ppl/PILLARS_DONE

# P1 (gated) first, so a slow P3 can never jeopardise the gated numbers.
python3 -m suite.runner --host "$EP" --auth "admin:$PW" --loaded-docs "$DOCS" \
  --skip-correctness --out "results/$TAG/perf.json"
python3 -m suite.load_runner --host "$EP" --auth "admin:$PW" --tests l1,l2,l3 \
  --levels 5,10,20 --ramp-max 40 --duration "$L3_DUR" --out "results/$TAG/load.json"
python3 -m suite.usecase_runner --host "$EP" --auth "admin:$PW" \
  --scenarios u1,u2,u3,u4,u5,u6,u7 $UC_ARGS --out "results/$TAG/usecase.json"
# P3 wide-range coverage (3d, 7d) — documented, not gated (§4.2).
python3 -m suite.runner --host "$EP" --auth "admin:$PW" --loaded-docs "$DOCS" \
  --skip-correctness --time-ranges 3d,7d --out "results/$TAG/perf-wide-range.json"

python3 report/make_report.py "results/$TAG/perf.json" > "results/$TAG/report.md"
aws s3 cp "results/$TAG/" "s3://$BUCKET/results/$TAG/" --recursive --region us-east-1
touch /opt/ppl/PILLARS_DONE
echo "PILLARS DONE"
