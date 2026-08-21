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
      mock-index-template.json         # composable template derived from ^ (what the loader PUTs)
      distributions.yaml               # M1 field distributions (TODO: sample from os35)
    generator.py                       # TODO M2: one emitter per body format
    expected.py                        # TODO M2: analytical expected values for correctness
    load.py                            # TODO M2: idempotent bulk load --target local|aws
  infra/
    local/                             # TODO M4: docker-compose + Makefile + observability
    aws/                               # TODO M5: CDK/domain spec from the sizing doc
  suite/                               # TODO M3/M6: runner, catalogue, sessions
  report/                              # TODO: report.md + diff.py
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
- [ ] Team sandbox `make up` local smoke; full N=8 run (deploy in team for authoritative run); U7 WLM two-user setup (§3.3).

## Key facts

- Single unified OTel-logs schema; 5 dynamic_templates coerce
  `resource.attributes.*`/`attributes.*` -> keyword and `log.**` -> text+.keyword / object / keyword.
- Field paths: `severityText`/`severityNumber`, `log.status` (string!),
  `resource.attributes.k8s.namespace.name`, `...k8s.pod.name`,
  `resource.attributes.cloud.region`, `resource.attributes.applicationid`.
- Gotchas: `log.@timestamp` is keyword (real date = `@timestamp`/`observedTimestamp`/`time`);
  `attributes.time` + `log.timestamp` are `object enabled:false`; `body` is `text norms:false`.
- `duration` is NOT in the mapping — pending decision (drop / synthesize / other sourcetype).
