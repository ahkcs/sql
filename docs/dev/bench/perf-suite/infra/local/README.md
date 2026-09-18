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
`make ship` publishes a finished run to the local sink (§3.5); `make test-local` does it for you.

## WLM / U7 (security-on profile)

U7 needs real users, so the same compose file has a security-on profile. Tier 2 can run U7 as
well — managed AWS does expose `_wlm`/`_rules` on OpenSearch 3.5 — but iterating here is free
and doesn't disturb the benchmark cluster:

```bash
export OS_ADMIN_PASSWORD='StrongDemo#Pass1'
export PPL_ADMIN_AUTH=admin:"$OS_ADMIN_PASSWORD"
export PPL_DASH_AUTH=dash_user:'StrongDash#Pass1'
export PPL_ADHOC_AUTH=adhoc_user:'StrongAdhoc#Pass1'
make up-secure     # HTTPS + demo certs + security plugin on
make load-secure   # same 20k/index, authenticated
make wlm-setup     # §3.3: 2 workload groups, 2 users/roles, 2 principal rules, mode=enabled
make usecase-wlm   # U5 + U7 (solo / WLM off / WLM on)
```

Demo certs are self-signed, so the secure targets export `PPL_INSECURE_TLS=1` (skips cert
verification — local only, never against a managed domain).

## Notes

- The default profile has the security plugin **disabled** (HTTP, no auth) for dev speed, so
  `--auth` is omitted; use the security-on profile above for U7.
- Default image is `opensearchproject/opensearch:2.18.0`. Set `OS_VERSION=3.5.0`
  (once confirmed) to match Tier-2 for query-behaviour fidelity:
  `OS_VERSION=3.5.0 make up`.
- Ports: SUT on `localhost:9200`, observability sink on `localhost:9201`.
- The suite modules run from the perf-suite root; the Makefile sets `PYTHONPATH`
  automatically.
- Coordinating-only node (`os-coord`, `node.roles: []`) mirrors the dedicated-coordinator
  path that CFN can't express for Tier-2.
