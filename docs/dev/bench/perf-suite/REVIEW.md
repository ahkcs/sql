# PPL Performance Benchmark — Review Package

**For:** engineering manager + principal engineer · **Date:** 2026-09-24
**Scope:** three benchmark pillars plus a type-coverage axis, run at fidelity scale, measured against the [Test Plan](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan)
**Contents:** what we built (§1), what we found (§2, §2b), how much to trust it (§3), where everything lives (§4).

---

## 1. What we built and why

The question behind the whole exercise: **how does PPL behave at a real customer's scale, and where does it
break?** Nothing in CI answers that — integration tests run against a handful of documents.

So we stood up a dedicated benchmark domain mirroring the customer's [obs-pi pre-prod environment](https://iad.prod.tumbler.oss.aws.dev/992382490528/obs-pi-pre-prod-us-east-1/overview) scaled down
8× (12 data nodes instead of 96), and loaded **1.83 billion documents** — one full customer day ÷ 8 —
across 10 different log body formats with a ~3,000-field schema. **Shard size ~12.7 GB matches the customer's**,
which is the single most important knob for latency realism.

Three pillars, each answering a different question, plus a fourth axis added this week:

| Pillar | Question | Shape |
| --- | --- | --- |
| **Perf** ([§2.1](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan)) | What does each query cost on its own? | 96 templates × 6 time ranges = 576 measured points, single concurrency |
| **Load** ([§2.2](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan)) | How does the cluster behave with N queries in flight? | concurrency ladder, stress ramp to N=100, 30-min sustained |
| **Use-case** ([§2.3](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan)) | Do real users get a good experience? | 7 realistic workflows (dashboards, incident session, alerting, multi-user, WLM isolation) |
| **Type × operation** (new) | Does an operation still push down for *this field type*? | 254 points asserted from `_explain`, not inferred from latency |

---

## 2. Headline results

### Perf — 576 points: 491 FAST · 23 ACCEPTABLE · 42 SLOW · 20 ERROR
_FAST <5 s · ACCEPTABLE 5–30 s · SLOW 30–300 s · ERROR failed._

Most PPL commands are flat across time ranges (~0.05–0.5 s) because `head` early-terminates the scan, so they
measure command overhead rather than scan cost. The slow tail is narrow and specific:

- **`rex` field extraction — 52 s at 1 d** (mean over the 10 body formats), **worst 148 s at 7 d**
  (`mock-kv-quoted-wi`). Every one of the 10 formats is SLOW at 3 d and 7 d:

  ```
  source=mock-kv-quoted-wi | where @timestamp >= '2026-04-10 00:00:00'
  | rex field=body "(?<w>\w+)" | stats count() by w
  ```

- **leading-wildcard `LIKE` on the message body — 64 s at 1 d, 75 s at 3 d, 87 s at 7 d.** A leading `%`
  cannot use the index, so this is a per-document regex over the body:

  ```
  source=mock-mixed-pi | where @timestamp >= '2026-04-10 00:00:00'
  | where like(body, '%timeout%')
  ```

  Note the shape: 6.4 s → 40.9 s from 5 m to 1 h (roughly linear in documents), then only 40.9 s → 86.6 s
  from 1 h to 7 d despite **168× more data**. That flattening is what early termination looks like — this
  query returns raw rows, so it is capped by the 10,000-row `size_limit` and almost certainly stops scanning
  once the cap is met. Unconfirmed, and worth confirming: if so, **the 7 d number understates the real cost**
  of the same predicate inside an aggregation.
- **`eventstats` / `streamstats` hit the query memory circuit breaker** (`plugins.query.memory_limit=85 %`):
  they run 150–190 s and then abort with *"Insufficient resources… memory usage exceeds limit"*. These are
  whole-result-set operations — they emit a row per input document, so over 26 M–183 M rows they exhaust the
  query memory pool. Already 82 s at 1 h before failing. **Unusable over ≥1-day windows at this scale**, and
  this is a hard limit rather than a tuning problem: the breaker is doing its job.

The per-format probe table isolates *operation* cost from *format* cost, and the answer is unambiguous —
**the operation dominates**. Mean p95 across all six ranges, by probe:

| Probe | Range across the 10 body formats |
| --- | --- |
| count-by-severity (low-card keyword agg) | 0.058 – 0.108 s |
| count-by-pod (10.8 M-cardinality agg) | 0.215 – 0.455 s |
| filtered scan + `head` | 0.221 – 0.275 s |
| **`rex` on the message body** | **42.9 – 55.0 s** |

`rex` is 100–900× every other probe *on every format*. Body format is only a ~28 % modifier on top of that
(`json-dd` and `nested-cape` most expensive at ~55 s, `json-http` cheapest at ~43 s), which matches expectation:
richer or nested bodies cost more to parse, but the parse itself is the problem.

Of the 20 errors, **6 are real** (the memory-breaker cases) and **14 were collateral** — cheap queries
admission-rejected because heap had not recovered from the preceding heavy query. All 14 pass in isolation.
That distinction matters: a naive reading would have reported 20 broken queries.

### Load — the cluster degrades gracefully; it does not fall over
- **Breaking point ≈ 25 concurrent heavy queries** (average latency crosses 60 s). Full collapse by N=55.
- **The search thread-pool queue saturates first** — onset at N=10, peaking ~2,880. **Heap stays flat at 79 %
  and server-side rejections are zero throughout.** So the failure mode is queue backlog and latency, *not*
  memory exhaustion or admission control. The "errors" at high N are client-side timeouts on queued work.
- **Saturation has a ~20-minute recovery tail** — the pool keeps draining queued work long after load stops.
  Capacity planning needs to budget recovery, not just steady state.
- Steady state is healthy: **N=10 sustained for 30 min holds 96 %** with no heap growth.

### Use-case — all seven scenarios pass
- Dashboards load in **~0.5 s**; a 6-panel dashboard over **a full week of all 11 indices (281 shards) is
  1.84 s**. Fan-out is sub-linear: 3.8× cost for 10× the shards.
- Alert rules: **10 of 10 evaluations inside their 60 s cadence.**
- Widening 1 h → 7 d (168× the data) costs **2.4×** — the signature of a correctly pushed-down aggregation.
- **WLM isolation, the strongest customer-facing number we have** (setup matters, see §3): a noisy ad-hoc
  neighbour costs the dashboard user **732× with WLM off (p95 0.15 s → 111 s)** and **1.7× with WLM on
  (0.26 s)**. The ad-hoc group absorbed 150,910 rejections instead. On a shared cluster, WLM is the difference
  between a two-minute dashboard and a quarter-second one.

### Type coverage — where the sharpest findings came from
Added this week, and it produced more per hour than anything else. 254 points, verdict asserted from the
physical plan rather than inferred from timing.

- **Three mapping types are invisible to PPL: `unsigned_long`, `wildcard`, `flat_object`.** The fields exist in
  the mapping and the index accepts them, but PPL never surfaces them, so every reference fails
  `Field [x] not found`. **Those fields are unqueryable via PPL** — a hard failure, not a slowdown.
- **Aggregating on a bare `text` field falls off pushdown for 7 of 11 operations** (group-by, distinct-count,
  count, sort, dedup, top, rare), and the results **silently truncate at 10,000 groups with no warning**.
- **`rex`-then-aggregate is a different mechanism** and we got it wrong at first (§3). It *does* push down, as a
  scripted aggregation. Isolated at 1 h: plain keyword agg 0.12 s · `rex` over a **keyword** field 0.14 s ·
  `rex` over **`body`** 2.49 s. **The regex is nearly free; reading a `text` field per document is the cost.**

---

## 2b. Timeouts and partial results — the same query fails differently on AOS and AOSS

This came out of a support escalation ([P468931651](https://t.corp.amazon.com/P468931651/overview)) and is the
finding with the widest customer blast radius, because it is a **behavioural divergence the plugin does not
control**.

**What the plugin does.** PPL sets a **per-shard** timeout of **60 s** on every search
(`DEFAULT_QUERY_TIMEOUT = 1 minute`; on the paginated scan path each page is overridden with
`plugins.sql.cursor.keep_alive`, also 60 s). It **never sets `allow_partial_search_results`**, so every PPL query
inherits whatever the environment defaults to. That single inherited flag decides what 60 s *means*:

| Environment | `allow_partial_search_results` | What happens when a shard exceeds 60 s |
| --- | --- | --- |
| **Managed OpenSearch** — our benchmark domain, and the customer's obs-pi | **true** (default) | the shard returns **partial results**, response is `timed_out: true`, **HTTP 200**, the query keeps going |
| **AOSS serverless collections** | **false** (enforced) | `QueryPhaseExecutionException` propagates → **HTTP 500 at ~60 s**; the whole query fails |

**We reproduced the mechanism directly** rather than inferring it. Forcing a shard timeout with `timeout: 1ms` on
a heavy aggregation, same query both ways:

- `allow_partial_search_results=false` → **HTTP 500**, `search_phase_execution_exception` /
  `query_phase_execution_exception`, "all shards failed"
- `allow_partial_search_results=true` → **HTTP 200**, `timed_out: true`, `took: 457ms`, and — note this —
  **`_shards: {successful: 28, failed: 0}`**

**So why do our queries run well past 60 s without failing?** Because on a managed domain the 60 s is a
*per-shard, per-request collection budget*, not a query deadline. It does not bound coordinator-side work, does
not bound multi-page pagination, does not count queue wait, and returns partial data rather than aborting. The
only real ceiling is `plugins.ppl.query.timeout` (**300 s**). We verified this live: heavy queries returned
**HTTP 200 after 72 s and 88 s**.

**Why this matters more than a timeout curiosity:**

1. **On managed domains the failure mode is silent wrongness, not an error.** A response can be flagged
   `timed_out: true` while simultaneously reporting `failed: 0` — and **PPL never surfaces that flag to the
   user**. Combined with the 10,000-row `size_limit` truncation (also silent), a user can act on an incomplete
   answer with no indication. Our harness recorded **zero warnings** even on results we know were truncated.
2. **On AOSS the same PPL query is simply broken at 60 s**, which is what the escalation was.
3. **Customers cannot opt in or out.** On a managed domain the cluster-wide setting is rejected
   (`_cluster/settings` refuses the key; `_plugins/_query/settings` filters to `plugins.*` prefixes), and PPL
   offers no per-query control — though the flag *is* settable per request on raw `_search`, which is how we
   reproduced it.
4. **Our benchmark therefore cannot reproduce the AOSS regime**, and should not be quoted as evidence about it.

---

## 3. Methodology — what a reviewer should push on

We found and fixed **nine defects in our own harness**, each of which had been producing a wrong conclusion.
Listing them because they are the reason to trust the current numbers, and because the pattern (measure, distrust,
verify) is what we would want from any benchmark:

| Flaw | Wrong conclusion it produced |
| --- | --- |
| Repeats pinned an absolute time window | dashboards looked **20–50× faster** than reality (shard request cache hits) |
| Load test made a single pass over the query pool | in-flight concurrency capped at pool size; "no breaking point through N=40" was an artifact |
| Load ramp re-sampled queries per rung | concurrency and query mix confounded; p95 *fell* as concurrency rose |
| U7 noisy neighbour was a single serial loop | isolation gates passed with **no contention to isolate against** (1.1× with WLM off) |
| U5 solo baseline measured cold | every user appeared *faster* under load; measured warmup, not contention |
| U7 noisy-query pool drawn from a category that no longer exists | pool was empty; the neighbour generated **no load at all** |
| WLM provisioning created groups before enabling the mode | groups silently failed, all routing rules skipped, U7 would have self-skipped |
| Pushdown classifier credited the time-range filter | false PUSHED on `top`/`rare`/`dedup`; three further false FALLBACKs later |
| Python stdout buffered under systemd | a healthy 54-minute run looked hung and was killed |

**Two claims we published and have since corrected:**
1. "`rex`-then-aggregate drags every row to the coordinator" — **wrong**; it pushes down as a scripted
   aggregation. The cost is per-document `_source` reads on a `text` field.
2. "It grows linearly with the time window" — partially wrong; a controlled sweep shows 0.34 / 2.35 / 24.9 s at
   5m / 1h / 1d, but one earlier 7 d reading was anomalous and remains unexplained.

**Fidelity basis and where it diverges from the customer** — worth a reviewer's attention:
- shard size (~12.7 GB) and per-window doc counts match; schema width and body-format mix match
- **index granularity does not**: we use 10 fat indices spanning 7 days each; the customer has ~306 daily
  indices. Consequence: a 1-hour wildcard query for us cannot prune any index and fans out to all 281 shards,
  while the customer's prunes ~305 of 306. So our wildcard fan-out is *pessimistic* for narrow windows and we
  **cannot reproduce PIT-context exhaustion** (GH [#5698](https://github.com/opensearch-project/sql/issues/5698) / [#5634](https://github.com/opensearch-project/sql/issues/5634)), which needs >300 shards on one node.
- the dataset is historical (ends 2026-04-11), so a literal `now-1h` matches nothing; rolling windows are
  simulated by sliding within the data

---

## 4. Artifacts

| What | Where |
| --- | --- |
| Findings & action tracker | [Results, Findings & Tracker](https://chorus.aws.dev/doc/ctWafvk3X0c2/PPL-Performance-Benchmark--Results-Findings--Tracker) |
| Plain-English walkthrough of the Use-case pillar | [What We Tested and What We Found](https://chorus.aws.dev/doc/sanzZe3QLdP3/PPL-Use-Case-Benchmark--What-We-Tested-and-What-We-Found) · [EXPLAINED.md](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v1/EXPLAINED.md) |
| Perf report (576 points) | [fidelity-perf-v2/report.md](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-perf-v2/report.md) |
| Load report (ladder, ramp, sustained) | [fidelity-load-v1/report.md](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-load-v1/load-test-report.md) · [clean sustained rerun](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-load-l3clean/report.md) |
| Use-case reports | [v1 (all 7 scenarios)](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v1/report.md) · [v2 corrected U5/U7](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v2-u5u7/report.md) · [v3 wildcard + 7 d](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v3-wide/report.md) |
| Type × operation matrix (254 points) | [pushdown/report-types.md](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/pushdown/report-types.md) |
| Reseed spec + expansion checklist | [RESEED-SPEC.md](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/RESEED-SPEC.md) · [TODO-EXPANSION.md](https://github.com/ahkcs/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/TODO-EXPANSION.md) |
| Harness | [perf-suite/](https://github.com/ahkcs/sql/tree/feature/ppl-perf-suite/docs/dev/bench/perf-suite) on branch `feature/ppl-perf-suite` |
| Cluster access, sizing, infra inventory | [Benchmark Cluster — Access & Details](https://chorus.aws.dev/doc/Itz4zsOtkhKx/PPL-Benchmark-Cluster--Access--Details) |
| Test plan these results measure against | [Performance, Load & Use-Case Test Plan](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan) |
