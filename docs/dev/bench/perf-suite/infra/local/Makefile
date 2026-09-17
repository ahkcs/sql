# Tier-1 local dev loop. Run from infra/local/.
# Suite modules run from perf-suite root (two dirs up).
SUITE := $(abspath ../..)
HOST  := http://localhost:9200
SINK  := http://localhost:9201
CURLO :=
PY    := PYTHONPATH=$(SUITE) python3

# Security-on profile (plan §3.3 WLM / U7): HTTPS + demo certs + real users.
SEC_HOST  := https://localhost:9200
SEC_CURLO := -k -u admin:$$OS_ADMIN_PASSWORD
SEC_PY    := PYTHONPATH=$(SUITE) PPL_INSECURE_TLS=1 python3
ADMIN     := admin:$$OS_ADMIN_PASSWORD

.PHONY: up down load test-local perf load-test usecase wait clean ship \
        up-secure load-secure wlm-setup wlm-show usecase-wlm

up:
	docker compose up -d
	@echo "waiting for cluster..."; $(MAKE) wait

wait:
	@for i in $$(seq 1 60); do \
	  curl -s $(CURLO) $(HOST)/_cluster/health >/dev/null 2>&1 && \
	  curl -s $(CURLO) "$(HOST)/_cluster/health?wait_for_status=yellow&timeout=2s" >/dev/null 2>&1 && \
	  echo "cluster up" && exit 0; sleep 3; done; echo "timed out waiting" && exit 1

down:
	docker compose down -v

# ~1/1000 dev scale (Tier-1). Uses the parallel loader; no auth (security disabled).
load:
	$(PY) -m mock_data.load_parallel --host $(HOST) --docs-per-index 20000 --shards 3 --replicas 0 --workers 6

perf:
	$(PY) -m suite.runner --host $(HOST) --loaded-docs 20000 --out $(SUITE)/results/local-perf.json

load-test:
	$(PY) -m suite.load_runner --host $(HOST) --tests l1,l2,l3 --levels 5,10 --ramp-max 20 --duration 60 \
	  --out $(SUITE)/results/local-load.json

usecase:
	$(PY) -m suite.usecase_runner --host $(HOST) --scenarios u1,u2,u3,u4,u5,u6 --think 2 --short \
	  --out $(SUITE)/results/local-usecase.json

# Publish a finished run to the local observability sink (plan §3.5). SINK_URL
# points at Tier-2's long-lived sink instead when running a release run.
ship:
	$(PY) $(SUITE)/report/ship.py --sink $(SINK) --ensure-policy \
	  $(SUITE)/results/local-perf.json $(SUITE)/results/local-load.json \
	  $(SUITE)/results/local-usecase.json

# full dev-loop: perf + load + use-case, then a report + ship
test-local: perf load-test usecase
	$(PY) $(SUITE)/report/make_report.py $(SUITE)/results/local-perf.json > $(SUITE)/results/local-report.md
	@echo "wrote results/local-report.md"
	@$(MAKE) ship

clean:
	curl -s $(CURLO) -XDELETE $(HOST)/mock-* >/dev/null || true

# ---- WLM / U7 (Tier-1 only; managed AWS exposes neither _wlm nor _rules) -------
# Prerequisites, exported in your shell first:
#   export OS_ADMIN_PASSWORD='StrongDemo#Pass1'
#   export PPL_ADMIN_AUTH=admin:$$OS_ADMIN_PASSWORD
#   export PPL_DASH_AUTH=dash_user:'StrongDash#Pass1'
#   export PPL_ADHOC_AUTH=adhoc_user:'StrongAdhoc#Pass1'
up-secure:
	@test -n "$$OS_ADMIN_PASSWORD" || { echo "export OS_ADMIN_PASSWORD first"; exit 1; }
	DISABLE_SECURITY=false docker compose up -d
	@echo "waiting for secured cluster..."; $(MAKE) wait HOST=$(SEC_HOST) CURLO="$(SEC_CURLO)"

load-secure:
	$(SEC_PY) -m mock_data.load_parallel --host $(SEC_HOST) --auth $(ADMIN) \
	  --docs-per-index 20000 --shards 3 --replicas 0 --workers 6

# Two workload groups + two users/roles + two principal rules, then mode=enabled.
wlm-setup:
	$(SEC_PY) -m suite.wlm --host $(SEC_HOST) --auth $(ADMIN) --provision

wlm-show:
	$(SEC_PY) -m suite.wlm --host $(SEC_HOST) --auth $(ADMIN) --show

# U7 runs the noisy-neighbor scenario solo / WLM off / WLM on and compares.
usecase-wlm:
	$(SEC_PY) -m suite.usecase_runner --host $(SEC_HOST) --auth $(ADMIN) \
	  --scenarios u5,u7 --short --out $(SUITE)/results/local-usecase-wlm.json
