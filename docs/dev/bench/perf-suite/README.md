# PPL Performance, Load & Use-Case Test Suite

In-repo harness for the PPL Perf/Load/Use-Case Test Plan
(Chorus doc `Wz9MgtrddN1P`). Seeded from the pattern in `../` (the
PIT-exhaustion bench: `seed_*` / `run_bench.py` / `make_report.py`).

## Decisions

- **Harness home:** here (`docs/dev/bench/perf-suite/`), Python, out of the Gradle build.
- **Tier 1 (dev-loop):** local docker, 1 coord + 3 data, ~1/1000 scale.
- **Tier 2 (release gate):** NEW dedicated OpenSearch 3.5 cluster, sized via the
  "Test Domain Sizing & Scale-Down Rationale" method (hold per-node
  data/shards/shard-size/instance-type constant; scale node-count + total by N),
  mirroring **obs-pi**, loaded with synthetic `mock-*` indices.
- **Smoke tier:** reuse Ryan Liang's `ppl-repro-os35` (public FGAC, OS 3.5) for
  auth/wiring + as the distribution-sampling source (prod values are
  guardrail-blocked; os35 is not).

## Layout

```
perf-suite/
  mock_data/
    schemas/
      customer-pre-prod-mapping.json   # real obs-pi OTel mapping (reference, verbatim)
      mock-index-template.json         # 75-field base template (loader --narrow)
      mock-index-template-wide.json    # ~3000-field wide template — THE DEFAULT
      distributions.yaml               # M1 field distributions (mirrors distributions.py)
    generator.py                       # deterministic OTel doc emitters, one per body format
    wide_schema.py                     # sparse attributes.*/resource.attributes.* width
    expected.py                        # analytical expected values for correctness
    load.py / load_parallel.py         # idempotent bulk load
  infra/
    local/                             # Tier 1: compose + Makefile + observability sink
    aws/                               # Tier 2: CFN domain, snapshot, EC2 loader, run_pillars.sh
  suite/
    catalogue.py                       # 22 query templates x 11 categories
    runner.py / load_runner.py / usecase_runner.py    # the three pillars (P*, L*, U*)
    identities.py                      # named per-user auth from env (--as-user)
    wlm.py                             # §3.3 workload-group policy + stats (U7)
    runinfo.py                         # run header: run_id / git_sha / schema_version
    metrics.py / verdicts.py
  report/
    make_report.py / diff.py           # report.md + run-to-run comparison
    ship.py                            # publish a finished run to the observability sink
  results/                             # run outputs (results.json)
```

## Status

- [x] Save real obs-pi mapping (`schemas/customer-pre-prod-mapping.json`)
- [x] Derive mock index template (`schemas/mock-index-template.json`)
- [x] Sample field distributions from `ppl-repro-os35` -> `distributions.yaml` v0.2 (17 namespaces, svc card 120, cluster env/name verified; obs-pi-only synthesized)
- [x] Measure `obs-pi` topology -> `infra/aws/tier2-domain-spec.md` (N=8 recommended; shards/node pending)
- [x] **M2 core**: `distributions.py` / `generator.py` / `expected.py` / `load.py` + `test_generator.py` (11/11 pass; loader dry-run verified). Canonical distributions in `distributions.py`; yaml mirrors it.
- [ ] Actual Tier-1 load (needs M4 docker) + wire `expected.py` into the runner
- [x] Tier-2 CFN template + deploy runbook (`infra/aws/tier2-domain.cfn.yaml`, `deploy.md`); target acct 089813482837; instance types verified.
- [x] **Pilot deployed** (`ppl-perf-tier2-pilot`, 3-node r7g.large) — validating CFN + FGAC + loader before full N=8.
- [x] **M3 core**: `suite/{catalogue,runner,metrics,verdicts}.py` — 22 query templates x 11 categories, warmup+reps/percentiles, latency verdicts, correctness vs `expected.py`, cluster-metric snapshots. `--list` validated offline.
- [ ] Run against pilot: smoke-load `mock-*` + `suite.runner` (correctness + latency)
- [x] Pilot run GREEN end-to-end (correctness 3/3, 88 latency runs FAST); pilot torn down.
- [x] Full N=8 Tier-2 deploying (`ppl-perf-tier2`); snapshot path staged (`snapshot-repo.cfn.yaml` + `snapshot.md`).
- [x] Full N=8 verified GREEN (correctness 3/3, 88 latency runs 87 FAST/1 known-slow) on real 12-node cluster.
- [x] Snapshot/restore proven end-to-end (`es_sigv4.py` + FGAC IAM map; mock-v1 snapshot + renamed restore = 50000).
- [x] Parallel loader (`mock_data/load_parallel.py`) — live-validated (1M docs, 0 err, correctness 3/3).
- [x] Load pillar (`suite/load_runner.py`, L1/L2/L3) — live-validated on sandbox.
- [x] Use-case pillar (`suite/usecase_runner.py`, U1-U6; U7 WLM scaffolded) — live-validated.
- [x] Report step (`report/make_report.py` + `report/diff.py`) — validated offline.
- [x] Tier-1 local docker (`infra/local/`: compose + Makefile + README) — compose config valid; `make up` smoke pending.
- [x] Authoritative Tier-2 run on the 75-field mapping (250M docs): 79 FAST / 8 ACCEPTABLE / 1 SLOW,
      Load 100% in-threshold, U1-U6 green (`results/tier2-team-full/`). Snapshot `mock-250m`.
- [x] **Wide (~3000-field) schema is the default** (`wide_schema.py`, `--narrow` = old 75-field base).
      Width lives in sparse `attributes.*` / `resource.attributes.*` — the OTel logs data model has no
      `log.**` field, so the customer's `log.**` explosion is deliberately not reproduced.
- [x] **M6 complete — U7 WLM noisy-neighbor implemented** (`suite/wlm.py`, `suite/identities.py`,
      real `u7()` with solo / WLM-off / WLM-on phases and §4.4 gates). 9/9 in `suite/test_wlm.py`.
- [x] **M5 ship step** (`report/ship.py`): daily per-pillar indices, idempotent by `run_id`,
      ISM hot-90d policy, `SINK_URL` knob; run header in every results.json (`suite/runinfo.py`).

- [x] Wide 250M loaded + snapshotted (`mock-250m-wide`) as the equal-doc-count schema-width control.
- [x] **Fidelity-scale dataset (M7 data)**: 1.83B docs = one customer day / N=8, 183M per index,
      28 shards -> 3.54 TB primaries / 6.83 TB on disk, 12.7 GB/shard, 569 GB/node. Ingested at
      81.5K docs/s aggregate on 3 loader workers (`loader-fleet.cfn.yaml` + `fleet_load.py`).
- [x] **Fidelity-scale pillar run** (`results/fidelity-1d/`): Perf 75 FAST / 10 ACCEPTABLE / 3 SLOW,
      0 errors; L1/L2/L3 in threshold (heap exactly on the 85% line); U1-U6 pass, U7 skipped.
      **Perf does NOT pass §4.2**: `rex` 33% and `dedup` 50% and `simple-search` 83% miss the
      >=90% FAST gate; `rex` (100%) and `simple-search` (50%) miss the <=20% SLOW-at-1d gate.

### Open

- [ ] **U7 for real on Tier 2** — managed AWS *does* expose WLM (see above); needs the two FGAC
      identities provisioned (`python3 -m suite.wlm --provision`) and the scenario run.
- [ ] File the two gate-breaking findings: leading-wildcard `LIKE` on `body` (61.7s at 1d, up from
      48.9s at 250M) and `rex` over a scaled day (61.8s / 52.6s).
- [ ] Fix two methodology gaps the fidelity run exposed: the catalogue's **absolute** time window
      makes U2/U4/U5 repeat-query cache hits (0.04-0.4s vs P1's seconds) instead of modelling a
      rolling `now-1h` dashboard; and L2's per-rung sample is too short (p95 *falls* as N rises).
- [ ] Turn AutoTune OFF on the domain (spec calls for it off; it is currently ENABLED).
- [ ] Tier-1 `make up` smoke (needs a running Docker daemon).
- [ ] AWS observability sink domain + the four dashboards / three alerts (§3.4).

## WLM / U7

Runs on **either tier**. Managed Amazon OpenSearch Service does expose workload management on 3.5 —
verified 2026-09-18: `_wlm/workload_group`, `_wlm/stats`, `_rules/workload_group` all answer and
`wlm.workload_group.mode` is settable (the AWS "supported operations" page is stale on this). Tier 1
with the security plugin on is the cheap loop for iterating on the scenario. `u7()` self-skips with a
specific reason (no WLM / no identities / groups not provisioned).

Plan §3.3 says the groups differ by "priority"; WLM has no priority field. The equivalent is
`resiliency_mode`: `dashboards` is `soft`, `adhoc` is `enforced` — which is what makes U7's 429s
observable.

```bash
export OS_ADMIN_PASSWORD='...'   PPL_ADMIN_AUTH=admin:"$OS_ADMIN_PASSWORD"
export PPL_DASH_AUTH=dash_user:'...'  PPL_ADHOC_AUTH=adhoc_user:'...'
cd infra/local && make up-secure load-secure wlm-setup usecase-wlm
```

## Key facts

- Single unified OTel-logs schema; 5 dynamic_templates coerce
  `resource.attributes.*`/`attributes.*` -> keyword and `log.**` -> text+.keyword / object / keyword.
- Field paths: `severityText`/`severityNumber`, `log.status` (string!),
  `resource.attributes.k8s.namespace.name`, `...k8s.pod.name`,
  `resource.attributes.cloud.region`, `resource.attributes.applicationid`.
- Gotchas: `log.@timestamp` is keyword (real date = `@timestamp`/`observedTimestamp`/`time`);
  `attributes.time` + `log.timestamp` are `object enabled:false`; `body` is `text norms:false`.
- `duration` is NOT in the mapping — pending decision (drop / synthesize / other sourcetype).
