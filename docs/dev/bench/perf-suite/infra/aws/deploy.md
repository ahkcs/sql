# Tier-2 provisioning runbook

Target account: **089813482837** (personal Isengard), region **us-east-1**.
Template: `tier2-domain.cfn.yaml`. Spec rationale: `tier2-domain-spec.md`.

> **This is an expensive cluster.** Spin it up for a run, snapshot to S3, tear it
> down. Do not leave it idle. See cost note at the bottom.

## Credentials

```bash
ada credentials update --account 089813482837 --role Admin --provider isengard --once
aws sts get-caller-identity      # expect .../assumed-role/Admin/ahkcs-Isengard
export AWS_REGION=us-east-1
```

## 0. Pilot first (recommended) — validate the template + loader cheaply

Deploy a tiny 3-node domain to prove the CFN + FGAC + loader end-to-end before
committing to the full 12-node / 6 TB build:

```bash
aws cloudformation deploy \
  --template-file tier2-domain.cfn.yaml \
  --stack-name ppl-perf-tier2-pilot \
  --region us-east-1 \
  --parameter-overrides \
      DomainName=ppl-perf-tier2-pilot \
      DataInstanceCount=3 \
      DataInstanceType=r7g.large.search \
      MasterInstanceType=r7g.large.search \
      VolumeSize=100 VolumeIops=3000 VolumeThroughput=125 \
      MasterUserPassword="$TIER2_PASS"
```

Then load a small set + verify (from `perf-suite/`):
```bash
EP=$(aws cloudformation describe-stacks --stack-name ppl-perf-tier2-pilot \
      --query "Stacks[0].Outputs[?OutputKey=='DomainEndpoint'].OutputValue" --output text)
python3 -m mock_data.load --host "https://$EP" --auth "admin:$TIER2_PASS" --docs-per-index 5000
```
Tear the pilot down when satisfied: `aws cloudformation delete-stack --stack-name ppl-perf-tier2-pilot`.

## 1. Full authoritative domain (N=8 defaults)

```bash
export TIER2_PASS='<choose a strong FGAC password>'   # >=8 chars, upper+lower+number+special
aws cloudformation deploy \
  --template-file tier2-domain.cfn.yaml \
  --stack-name ppl-perf-tier2 \
  --region us-east-1 \
  --parameter-overrides MasterUserPassword="$TIER2_PASS"
# ~15-30 min to go active. Endpoint:
aws cloudformation describe-stacks --stack-name ppl-perf-tier2 \
  --query "Stacks[0].Outputs" --output table
```

Budget alternative (N=16 -> 6 hot, ~half the cost + data): add `DataInstanceCount=6`.

## 2. Load data

```bash
EP=$(aws cloudformation describe-stacks --stack-name ppl-perf-tier2 \
      --query "Stacks[0].Outputs[?OutputKey=='DomainEndpoint'].OutputValue" --output text)
# scale up toward ~6 TB via --docs-per-index / index_docs ratios (a multi-hour load)
python3 -m mock_data.load --host "https://$EP" --auth "admin:$TIER2_PASS" --scale-divisor 8
```

## 3. Snapshot + teardown between runs (skip re-loading 6 TB)

Register an S3 snapshot repo, snapshot, then `delete-stack`. Restore on the next
run instead of regenerating. (Snapshot repo + IAM role steps: TODO in a follow-up.)

```bash
aws cloudformation delete-stack --stack-name ppl-perf-tier2 --region us-east-1
```

## Cost note (rough, on-demand, us-east-1)

Full N=8 (12x om2.4xlarge data + 3x r8g.large master + 12x 3 TB gp3 @ 9216 IOPS / 1250 MB/s):
order of **~$25+/hour** compute + **~$4k/month** EBS if left running. Treat it as
**ephemeral** — up for a load+run, then snapshot + delete. N=16 roughly halves it.
Confirm the `om2.4xlarge.search` type is offered in your account/region before the
full deploy (fallback: `r7gd`/`r7g` family) — the pilot uses cheap `r7g.large.search`.
