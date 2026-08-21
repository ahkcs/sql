# Tier-1 local dev loop. Run from infra/local/.
# Suite modules run from perf-suite root (two dirs up).
SUITE := $(abspath ../..)
HOST  := http://localhost:9200
SINK  := http://localhost:9201
PY    := PYTHONPATH=$(SUITE) python3

.PHONY: up down load test-local perf load-test usecase wait clean

up:
	docker compose up -d
	@echo "waiting for cluster..."; $(MAKE) wait

wait:
	@for i in $$(seq 1 60); do \
	  curl -s $(HOST)/_cluster/health >/dev/null 2>&1 && \
	  curl -s "$(HOST)/_cluster/health?wait_for_status=yellow&timeout=2s" >/dev/null 2>&1 && \
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

# full dev-loop: perf + load + use-case, then a report
test-local: perf load-test usecase
	$(PY) $(SUITE)/report/make_report.py $(SUITE)/results/local-perf.json > $(SUITE)/results/local-report.md
	@echo "wrote results/local-report.md"

clean:
	curl -s -XDELETE $(HOST)/mock-* >/dev/null || true
