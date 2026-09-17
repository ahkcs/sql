# Tier-2 domain spec — obs-pi scale-down

Authoritative AWS SUT for the Perf/Load/Use-case release gate. Sized by the
"Test Domain Sizing & Scale-Down Rationale" method: **hold per-node data /
per-node shards / shard-size / instance-type constant; divide node-count and
total data by N.** Only the *count* of nodes and *aggregate* data shrink — each
node still feels prod-like pressure.

## Prod reference — obs-pi-pre-prod-us-east-1 (measured 2026-08-20)

| Role | Count | Instance | Storage |
|---|---:|---|---|
| Hot data | 96 | `om2.4xlarge.elasticsearch` | gp3 3072 GB / 9216 IOPS / 1250 MB/s |
| Coordinator | 12 | `m8g.4xlarge.elasticsearch` | — |
| Dedicated leader (master) | 3 | `r8g.4xlarge.elasticsearch` | — |
| UltraWarm | 24 | `ultrawarm1.large` | ~20 TB/node |

- OS 3.5 · 3-AZ (`us-east-1a/b/c`), CapacityOptimized, MultiAZWithStandby **off**
- Remote store + remote publication **on** · Cold storage **on** · AutoTune **on** · FGAC **on** (SAML + IAM Identity Center)
- `AdvancedOptions`: `indices.fielddata.cache.size=20`, `indices.query.bool.max_clause_count=1024`, `override_main_response_version=true`, `rest.action.multi.allow_explicit_index=true`
- Live: green, 120 data nodes (96 hot + 24 warm), pri 3427 / shards 5726 (RF≈0.67), **153.4 B docs**, ~1 TB indices/node hot, ~96 TB hot on-disk incl. replicas.

## Tier-2 repro spec (N = 8 → 12 hot) — RECOMMENDED

| Dimension | Prod (obs-pi) | Tier-2 (N=8) | Note |
|---|---|---|---|
| Engine | OS 3.5 | **OS 3.5** | matched |
| Hot data nodes | 96 × om2.4xlarge | **12 × om2.4xlarge** | 96/8, multiple of 3 ✓ |
| Coordinators | 12 × m8g.4xlarge | **3 × m8g.4xlarge** | 12/8→round up→3 (min 1/AZ); same instance |
| Masters | 3 × r8g.4xlarge | **3 × r8g.large** | downsized — masters don't serve queries |
| UltraWarm | 24 | **none** | DROP — hot-tier PPL only; 7-day mock window is all hot |
| Cold storage | on | **off** | archival, off query path |
| Per-node hot data | ~1 TB | **~1 TB (matched)** | the point of the method |
| Total hot on-disk | ~96 TB | **~12 TB** | 96/8 |
| Source data to generate | — | **~6 TB @ RF=1** | 12 nodes × 0.5 TB primary; OpenSearch makes the replica |
| Shard size (hot) | ~13 GB (est.) | **~13 GB (match)** | TODO: confirm from prod hot shards/node |
| Per-node shards | ~80 (est.) | **~80 (match)** | ⇒ ~480 primary shards total |
| EBS/node | gp3 3072/9216/1250 | **gp3 3072 GB / 9216 IOPS / 1250 MB/s** | match IOPS/throughput exactly (IO-bound PPL) |
| Zone awareness | 3 AZ | **3 AZ, CapacityOptimized** | matched |
| Remote store | on | **on** | OS 3.5 default; affects query path |
| `AdvancedOptions` | (4 opts) | **replicate all 4** | matched |
| AutoTune | on | **off** | reproducibility — avoid adaptive drift across runs |
| Auth | SAML + IdC | **FGAC internal user + public endpoint** | drive from dev box, no bastion (mirrors os35) |
| KMS | CMK | AWS-owned key | encryption-at-rest ≠ query latency |
| Docs (approx) | 153.4 B | **~19 B** | derived; we target by *volume* (6 TB), doc-count falls out |

## Data-scale ladder — how much data we actually load

Fidelity reference (obs-pi pre-prod, as reported by the customer domain): 1 h ≈ 607 M docs /
508 GB · 1 d ≈ 14.6 B docs / 12.2 TB · retained ≈ 156 B docs / 169 TB (~14 d, RF≈0.67).
Those TB figures are on-disk including replicas, so one prod day is ≈ 7.3 TB of primaries and
the customer's average document is **≈ 0.50 KB of primary store**.

Our wide (~3000-field) synthetic document is **≈ 1.95 KB of primary store — 3.9× the
customer's**, so doc-count parity and byte parity do not coincide. We target **doc count**,
because PPL latency tracks documents scanned per shard far more closely than bytes on disk;
overshooting bytes is the conservative direction.

| Rung | Docs | Primaries | On-disk (RF=1) | Shards/index (~13 GB) | Ingest @ 34.5 K docs/s |
|---|---:|---:|---:|---:|---:|
| Schema-diff run (equal docs vs the 75-field baseline) | 250 M | 0.50 TB | 1.0 TB | 5 | 2 h |
| **1 fidelity day ÷ N=8 — AUTHORITATIVE** | **1.83 B** | **3.6 TB** | **7.1 TB** | **28** | **~5 h on 3 workers** |
| 1 fidelity day, absolute (no scale-down) | 14.6 B | 28.5 TB | 57 TB | 220 | ~5 days |
| Spec design target (retained ÷ N=8, per-node parity) | 19.5 B | 38 TB | 76 TB | 292 | ~6 days |

- The **absolute** and **full-retention** rungs do not fit: 36 TB of provisioned EBS (12 × 3072 GB)
  caps us at ~18 TB of primaries at RF=1. They would need either a larger cluster or a
  customer-sized document (≈ 0.50 KB), i.e. cutting `wide_schema.SPARSE_PER_DOC`.
- At the authoritative rung the topology lands close to prod on every axis that matters:
  ~12.8 GB/shard (prod ~13), ~47 shards/node (prod ~80), ~590 GB/node (prod ~1 TB).
- Ingest is parallelised across a loader fleet with a disjoint `--only` index list per worker
  (`fleet_load.py`); two workers on one index would wipe each other, since `create_index`
  DELETEs before it PUTs.

## Budget alternative (N = 16 → 6 hot)

6 × om2.4xlarge, 3 coord, 3 master, **~3 TB source data** (half the data-prep).
Same per-node load; cheaper and faster to green. Trade-off: 6 data nodes give
less fan-out realism, which matters for the **Load pillar** (concurrency /
thread-pool / coordinator-reduce behaviour). Use if data-generation time is the
binding constraint for the first release run.

## Open before this locks

- [ ] **Hot shards/node** from prod `_cat/allocation` (the `shards` column) → confirm shard-size + per-node-shard target (currently estimated ~13 GB / ~80).
- [ ] Confirm **N=8 (12 hot)** vs **N=16 (6 hot)**.
- [ ] Confirm **RF=1** (recommended: reproduces replica-read / shard-selection path).
- [ ] Confirm **drop UltraWarm + Cold + AutoTune**.
- [ ] **Provisioning AWS account** for the CDK deploy.
- [ ] Revisit UltraWarm only if any slow PPL query targets warm/cold indices.
