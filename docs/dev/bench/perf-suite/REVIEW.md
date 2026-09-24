# PPL Performance Benchmark — Review Package

**For:** engineering manager + principal engineer · **Date:** 2026-09-24
**Scope:** three benchmark pillars plus a type-coverage axis, run at fidelity scale, measured against the [Test Plan](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan)
**Ask:** six decisions (§6). Everything else here is context for them.

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
Most PPL commands are flat across time ranges (~0.05–0.5 s) because `head` early-terminates the scan, so they
measure command overhead rather than scan cost. The slow tail is narrow and specific:

- `rex` field extraction: 52 s at 1 d, up to **148 s at 7 d**
- leading-wildcard `LIKE` on the message body: 62 s at 1 d, **122 s at 3 d**
- `eventstats` / `streamstats`: run 150–190 s then abort on the query memory breaker — **unusable over ≥1-day
  windows at this scale**

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

## 4. Known gaps — stated plainly

1. **We verify speed, not correctness.** Fidelity runs use `--skip-correctness`. We have already seen two ways
   results go quietly wrong (10,000-group truncation; partial results on shard timeout), so **a "fast" number
   could mean less work was done.** This is the biggest gap.
2. **Single runs, so no variance.** Every pillar ran once. We cannot distinguish a real 20 % regression from
   noise, which means **the baseline currently has no error bars**.
3. **Index patterns are barely covered** — 1 of 96 Perf templates uses a wildcard, though `logs-*` is how
   customers actually query. Partially addressed in Use-case this week.
4. **11 mapping types were untested until this week**; the first pass found three of them unqueryable.
5. **Tier-1 / security-profile run never executed** (needs a local Docker daemon).
6. **Observability sink not built** — results accumulate as files rather than trend lines. `ship.py` is written
   and dry-run-verified but has nowhere to ship.

---

## 5. Exit criteria status

**The plan's [§4.2](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan) Perf gates are not met.** Three categories miss them at fidelity scale: `rex`,
`simple-search`, `dedup`. Load ([§4.3](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan)) and Use-case ([§4.4](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan)) gates pass.

The honest framing: **the gates were written before we had fidelity-scale data.** A ≥90 % FAST requirement on
`rex` is not achievable when `rex` over a day of logs is inherently a full-scan, per-document operation. That is
a decision to make, not a bug to fix — see D3.

---

## 6. Decisions we need

| # | Decision | Recommendation |
| ---: | --- | --- |
| **D1** | **Are `rex` / `dedup` / `simple-search` at ≥1 day release blockers, or documented known-slow with revised thresholds?** The [§4.2](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan) gates predate fidelity data. | Documented known-slow with revised gates, plus user-facing guidance. They are inherent costs, not regressions. |
| **D2** | **File F1–F9 as GitHub issues?** Nine findings currently live only in a Chorus doc. F8 (three unqueryable types) and F6 (bare-text aggregation) are the strongest. | Yes — F8 and F7 first; they are hard failures with clear repros. |
| **D3** | **Close the correctness gap before or after automating?** | Before. Trend-lining unverified numbers compounds the problem. |
| **D4** | **Weekly automation and its cost.** The domain runs 12×om2.4xlarge 24/7 for what is currently a ~5 h weekly job. Options: leave it, or snapshot→delete→restore per run (~2 h restore, big saving, adds variability). | Leave the domain up for now; split weekly (light subset ~90 min) from monthly (full wide-range). Revisit cost once cadence is proven. |
| **D5** | **Reingest scope.** Five sub-decisions in [RESEED-SPEC.md](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/RESEED-SPEC.md): load alongside as `mock2-*` (disk is at 17 %, so the old baseline stays queryable for a direct A/B), roll timestamps to "now" (realism vs reproducibility — genuine tension), index granularity, scale, correctness ground truth. | Load alongside; keep fat indices and add a *separate* small daily-granularity set for PIT/fan-out; defer the "now" timestamps decision until the reproducibility trade-off is agreed. |
| **D6** | **Do we recommend WLM to the customer as a requirement rather than an option?** | Yes. 732× → 1.7× is not a marginal improvement. |

---

## 7. Artifacts

| What | Where |
| --- | --- |
| Findings & action tracker | [Results, Findings & Tracker](https://chorus.aws.dev/doc/ctWafvk3X0c2/PPL-Performance-Benchmark--Results-Findings--Tracker) |
| Plain-English walkthrough of the Use-case pillar | [What We Tested and What We Found](https://chorus.aws.dev/doc/sanzZe3QLdP3/PPL-Use-Case-Benchmark--What-We-Tested-and-What-We-Found) · [EXPLAINED.md](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v1/EXPLAINED.md) |
| Perf report (576 points) | [fidelity-perf-v2/report.md](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-perf-v2/report.md) |
| Load report (ladder, ramp, sustained) | [fidelity-load-v1/report.md](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-load-v1/report.md) · [clean sustained rerun](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-load-l3clean/report.md) |
| Use-case reports | [v1 (all 7 scenarios)](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v1/report.md) · [v2 corrected U5/U7](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v2-u5u7/report.md) · [v3 wildcard + 7 d](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/fidelity-usecase-v3-wide/report.md) |
| Type × operation matrix (254 points) | [pushdown/report-types.md](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/results/pushdown/report-types.md) |
| Reseed spec + expansion checklist | [RESEED-SPEC.md](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/RESEED-SPEC.md) · [TODO-EXPANSION.md](https://github.com/KaiHuang020719/sql/blob/feature/ppl-perf-suite/docs/dev/bench/perf-suite/TODO-EXPANSION.md) |
| Harness | [perf-suite/](https://github.com/KaiHuang020719/sql/tree/feature/ppl-perf-suite/docs/dev/bench/perf-suite) on branch `feature/ppl-perf-suite` |
| Cluster access, sizing, infra inventory | [Benchmark Cluster — Access & Details](https://chorus.aws.dev/doc/Itz4zsOtkhKx/PPL-Benchmark-Cluster--Access--Details) |
| Test plan these results measure against | [Performance, Load & Use-Case Test Plan](https://chorus.aws.dev/doc/Wz9MgtrddN1P/PPL-Performance-Load--Use-Case-Test-Plan) |
