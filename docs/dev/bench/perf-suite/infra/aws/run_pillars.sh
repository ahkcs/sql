#!/bin/bash
# Run all three pillars from the EC2 loader (same-region, no 10-min shell limit).
# Downloads the suite bundle, reads the FGAC password from SSM, runs Perf/Load/
# Use-case against the team cluster, uploads results to S3, marks done.
set -x
BUCKET=ppl-perf-tier2-loader-924196221507
EP=https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com
cd /opt
aws s3 cp "s3://$BUCKET/perf-suite.tgz" . --region us-east-1
rm -rf ppl && mkdir ppl && tar xzf perf-suite.tgz -C ppl
PW=$(aws ssm get-parameter --name /ppl-perf-tier2/fgac-password --with-decryption --region us-east-1 --query Parameter.Value --output text)
export PYTHONPATH=/opt/ppl
cd /opt/ppl && mkdir -p results
rm -f /opt/ppl/PILLARS_DONE

python3 -m suite.runner --host "$EP" --auth "admin:$PW" --loaded-docs 25000000 --skip-correctness --out results/perf.json
python3 -m suite.load_runner --host "$EP" --auth "admin:$PW" --tests l1,l2,l3 --levels 5,10,20 --ramp-max 40 --duration 120 --out results/load.json
python3 -m suite.usecase_runner --host "$EP" --auth "admin:$PW" --scenarios u1,u2,u3,u4,u5,u6 --think 3 --short --out results/usecase.json

aws s3 cp results/ "s3://$BUCKET/results/" --recursive --region us-east-1
touch /opt/ppl/PILLARS_DONE
echo "PILLARS DONE"
