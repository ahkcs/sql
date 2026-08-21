# Tier-2 data provisioning via S3 snapshot / restore

Strategy: **load once → snapshot to S3 → restore on every subsequent run.** The
first population still happens once; after that a run restores the snapshot
(minutes) instead of regenerating data.

**Verified end-to-end 2026-08-20** on `ppl-perf-tier2` with the 50k-fraction.

Creds: `ada credentials update --account 089813482837 --role Admin --provider isengard --once`
(the ada token expires ~1h — re-run when AWS calls start returning ExpiredToken).

`SIG=infra/aws/es_sigv4.py` (minimal SigV4 signer — `awscurl` pulls a botocore
`crt` dep that isn't available here, so we sign with botocore's classic SigV4Auth).

## 1. Snapshot repo infra (S3 + IAM role)

```bash
aws cloudformation create-stack --stack-name ppl-perf-tier2-snapshot-repo \
  --region us-east-1 --capabilities CAPABILITY_NAMED_IAM \
  --template-body file://snapshot-repo.cfn.yaml
aws cloudformation describe-stacks --stack-name ppl-perf-tier2-snapshot-repo \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output text
# -> BucketName ppl-perf-tier2-snapshots-089813482837
# -> SnapshotRoleArn arn:aws:iam::089813482837:role/ppl-perf-tier2-snapshot-role
```

## 2. Map the Admin IAM role into FGAC  (the gotcha)

Registering an S3 repo is a SigV4/IAM call passing the snapshot role — the FGAC
internal `admin` user can't do it, so the calling IAM role must be an
`all_access` backend role. Done via the security API (basic auth as admin):

```bash
EP="https://<endpoint>"; PW="$(cat ~/.ppl-perf-tier2.secret)"
curl -s -u "admin:$PW" -H 'Content-Type: application/json' -X PATCH \
  "$EP/_plugins/_security/api/rolesmapping/all_access" \
  -d '[{"op":"add","path":"/backend_roles","value":["arn:aws:iam::089813482837:role/Admin"]}]'
```

## 3. Register the repo (SigV4)

```bash
python3 "$SIG" PUT "$EP/_snapshot/s3" \
  '{"type":"s3","settings":{"bucket":"ppl-perf-tier2-snapshots-089813482837","region":"us-east-1","role_arn":"arn:aws:iam::089813482837:role/ppl-perf-tier2-snapshot-role"}}'
# -> 200 {"acknowledged":true}
```

## 4. Snapshot after a (re)load

```bash
python3 "$SIG" PUT "$EP/_snapshot/s3/mock-v1?wait_for_completion=true" \
  '{"indices":"mock-*","include_global_state":false}'
# -> state SUCCESS, shards total==successful, failures []
```

## 5. Restore on a later run

Restore needs the target index to not exist; restore in place after deleting, or
rename to verify without touching originals (how we proved it):

```bash
python3 "$SIG" POST "$EP/_snapshot/s3/mock-v1/_restore?wait_for_completion=true" \
  '{"indices":"mock-json-http","rename_pattern":"(.+)","rename_replacement":"restored-$1","include_global_state":false}'
curl -s -u "admin:$PW" "$EP/restored-mock-json-http/_count"   # -> 50000
```

Full-run restore: `{"indices":"mock-*"}` (drop rename) into an empty domain.

## First population still needed once

Snapshot/restore doesn't remove the one-time initial load. For the full
~1 TB/node the single-threaded `load.py` is too slow (~1,250 docs/s) — needs the
parallel loader (mp workers + connection reuse + per-doc-index generator refactor).
The `filter_path=took,errors` fix in `load.py` was essential (large `_bulk`
responses were truncating). Snapshots persist in S3 (bucket `Retain`), so the
domain can be torn down between runs and restored later.
