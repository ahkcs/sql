# Tier-1 local dev loop

A throwaway local OpenSearch cluster (1 coordinator + 3 data) + a local
observability sink, for fast offline iteration on the suite — no AWS, no auth.
Not authoritative (can't reproduce customer-scale shards); use Tier-2 for that.

## < 10-min recipe

```bash
cd infra/local
make up            # docker compose up + wait for green/yellow (needs Docker + ~4GB RAM)
make load          # ~1/1000 mock data (20k/index) via the parallel loader
make test-local    # perf + load + use-case pillars, then results/local-report.md
make down          # tear down (removes volumes)
```

Individual pillars: `make perf`, `make load-test`, `make usecase`, `make clean`.

## Notes

- Security plugin is **disabled** (HTTP, no auth) for dev speed — so `--auth` is
  omitted and WLM (U7) isn't exercised here (WLM needs FGAC; that's a Tier-2 test).
- Default image is `opensearchproject/opensearch:2.18.0`. Set `OS_VERSION=3.5.0`
  (once confirmed) to match Tier-2 for query-behaviour fidelity:
  `OS_VERSION=3.5.0 make up`.
- Ports: SUT on `localhost:9200`, observability sink on `localhost:9201`.
- The suite modules run from the perf-suite root; the Makefile sets `PYTHONPATH`
  automatically.
- Coordinating-only node (`os-coord`, `node.roles: []`) mirrors the dedicated-coordinator
  path that CFN can't express for Tier-2.
