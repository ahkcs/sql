# PPL Use-Case Benchmark — What We Tested and What We Found

**Run:** `usecase-20260923T184148Z-73f6` · 2026-09-23 · OpenSearch 3.5, PPL with the Calcite engine
**Cluster:** `ppl-perf-tier2` — a dedicated benchmark domain sized to mirror the customer's pre-prod environment, scaled down 8×
**Data:** 1.83 billion log documents (one full customer day ÷ 8), 10 different log formats, ~3,000 fields
**Companion files:** `report.md` (generated tables) · `usecase.json` (raw data)

---

## 1. Summary for readers in a hurry

We asked one question: **does the cluster serve real users well?** Not "is this query fast" — that was the previous
phase — but "does a person opening a dashboard, chasing an incident, or running an alert get a good experience."

**All seven scenarios passed.** Every realistic user workflow completes comfortably inside its target, most of them in
well under a second at a scale equivalent to a full customer day of logs.

Four things worth a manager's attention:

1. **Normal usage is fast and has a lot of headroom.** Dashboards load in ~0.5 s. Alert rules complete 10/10
   evaluations inside their schedule. Widening a time range from 1 hour to 7 days (168× more data) costs only
   2.4× more time — the sign that the query engine is doing the right thing and pushing work down to the data
   nodes rather than dragging data around.

2. **We found one real user-facing problem.** In a realistic incident-investigation workflow, one specific step takes
   **26 seconds** while every other step in the same session takes under 0.6 s. It happens when a user extracts a
   value out of raw log text and then *groups by* that extracted value. This pattern cannot be optimised by the
   engine, so all matching data is pulled back to a single coordinating node. It is slow, it gets worse the wider
   the time range, and results can be silently truncated. This is the most actionable finding of the phase.

3. **Workload Management (WLM) is not optional on a shared cluster — we now have a number for it.** We ran one
   well-behaved "dashboard user" alongside a deliberately abusive "ad-hoc user." With WLM **off**, the dashboard
   user's response time went from **0.15 s to 111 s — 732× worse**; the dashboard is effectively unusable. With WLM
   **on**, the same abuse cost the dashboard user only **1.7×** (0.26 s), while the abusive workload was throttled
   (150,910 rejections). *This is the strongest customer-facing result in the project so far.*

4. **We fixed a measurement flaw that had been flattering our own numbers.** Earlier runs repeated the identical
   query with a fixed time window, so the cluster was serving cached answers and reporting results 20–50× faster
   than reality. Dashboards now genuinely re-query on every refresh. The corrected numbers are the ones in this
   document.

**What is not yet proven:** we do not yet verify that results are *correct* at this scale (only that they are fast),
and each scenario has been run once, so we have no measurement of run-to-run variance. Both are being addressed
before these numbers are used as a release gate.

---

## 2. How to read the numbers

| Term | Plain meaning |
| --- | --- |
| **median** | The typical experience — half of requests were faster than this. |
| **p95** | The unlucky experience — 95% of requests were faster, 5% slower. This is what users complain about. |
| **wall-clock** | Total time until the whole page is ready. A dashboard is not "loaded" until its slowest panel returns, so this is the number the user actually feels. |
| **Verdict** | **GOOD** under 5 s · **ACCEPTABLE** 5–10 s · **POOR** over 10 s. These are user-experience thresholds from the test plan, not engineering ones. |
| **"pushed down"** | Work done on the data nodes, next to the data, and only small summaries sent back. The opposite is pulling raw rows to one node and computing there — orders of magnitude slower. |

**One important methodology note.** Real dashboards ask for "the last hour," which is a different hour every time
you refresh, so nothing can be served from cache. Our dataset is historical (it ends 2026-04-11), so we cannot
literally ask for "the last hour" — there is no data there. Instead, every repeat slides its time window slightly,
which defeats caching exactly the way a live dashboard does while keeping the amount of data constant. This is why
these numbers are higher, and more honest, than our earlier runs.

---

## 3. The seven scenarios

### U1 — Dashboard refresh
**What it simulates:** a person opens a monitoring dashboard. Five to eight panels all fire at once, and the page
isn't ready until the slowest one finishes.

**How it works:** we built 3 realistic dashboards and ran each against 3 different data scopes — one index, a
group of indices (`mock-json-*`), and everything (`mock-*`) — for 9 page loads in total. All panels of a page fire
in parallel, and we time until the last one returns.

**Result: GOOD — median 0.543 s, p95 1.138 s, zero errors.**

| Dashboard | Data scope | Panels | Page load |
| --- | --- | ---: | ---: |
| ops_overview | one index | 6 | 0.685 s |
| ops_overview | `mock-json-*` | 6 | 0.908 s |
| ops_overview | everything | 6 | 1.292 s |
| error_triage | one index | 5 | 0.220 s |
| error_triage | `mock-json-*` | 5 | 0.543 s |
| error_triage | everything | 5 | 0.710 s |
| service_health | one index | 5 | 0.128 s |
| service_health | `mock-json-*` | 5 | 0.259 s |
| service_health | everything | 5 | 0.404 s |

**Reading it:** searching *everything* costs about 2–3× searching one index — a sensible, non-alarming scaling.
Even the heaviest page is comfortably interactive.

**The queries** (`{WINDOW}` is the 1-hour time filter):

*Dashboard "ops_overview" — the "what's happening now" page:*
```
source=IDX {WINDOW} | stats count() by severityText
```
Log volume broken down by level (INFO / WARN / ERROR) — the classic bar chart.
```
source=IDX {WINDOW} | top 10 resource.attributes.service.name
```
The ten noisiest services.
```
source=IDX {WINDOW} | stats count() by span(@timestamp, 1h)
```
The volume-over-time line chart.
```
source=IDX {WINDOW} | where severityText='ERROR' | head 50
```
The "recent errors" table — 50 actual log lines.
```
source=IDX {WINDOW} | stats count() by resource.attributes.cloud.region
```
Traffic split by AWS region.
```
source=IDX {WINDOW} | stats dc(resource.attributes.k8s.pod.name) as pods
```
How many distinct Kubernetes pods reported. This is the expensive panel — roughly 10.8 million distinct values.

*Dashboard "error_triage" — everything filtered to errors first:*
```
source=IDX {WINDOW} | where severityText='ERROR' | stats count()
source=IDX {WINDOW} | where severityText='ERROR' | stats count() by resource.attributes.service.name
source=IDX {WINDOW} | where severityText='ERROR' | stats count() by span(@timestamp, 1h)
source=IDX {WINDOW} | where severityText='ERROR' | head 50
source=IDX {WINDOW} | where severityText='ERROR' | stats count() by resource.attributes.cloud.region
```
How many errors · which service · when they spiked · the raw lines · which region. Tests whether filtering first
makes the aggregations cheaper (it does — this is the fastest dashboard).

*Dashboard "service_health" — numeric summaries:*
```
source=IDX {WINDOW} | stats count() by resource.attributes.service.name
```
Volume per service.
```
source=IDX {WINDOW} | stats count() by resource.attributes.service.name, severityText
```
A two-dimensional breakdown (service × severity) — a cross-tab table.
```
source=IDX {WINDOW} | stats avg(attributes.obs_body_length) as avg_len
```
Average message size — exercises numeric averaging.
```
source=IDX {WINDOW} | stats percentile(attributes.obs_body_length, 95) as p95_len
```
95th-percentile message size — more expensive than an average.
```
source=IDX {WINDOW} | stats count() by span(@timestamp, 1h)
```
The same timeline chart, for comparison across dashboards.

---

### U2 — Auto-refresh dashboard
**What it simulates:** a dashboard left open on a wall display, refreshing itself every 30 seconds.

**How it works:** the `ops_overview` dashboard above, re-fired every 30 s for 5 minutes (10 refreshes). Each
refresh asks for a slightly different time window, so none of them can be answered from cache. The point is not
the average — it is whether refresh #10 is slower than refresh #1.

**Result: GOOD — median 0.162 s, p95 0.293 s, zero errors. No degradation.**

Page load per refresh: 0.294, 0.292, 0.156, 0.161, 0.271, 0.157, 0.153, 0.164, 0.158, **0.162 s**

**Reading it:** flat, and if anything slightly faster after the first two. Sustained repeat load does not wear the
cluster down.

**The queries:** identical to `ops_overview` in U1.

---

### U3 — Incident investigation session
**What it simulates:** one engineer chasing a problem — starting broad, narrowing step by step, pausing ~25 s
between steps to read the screen (a realistic 5-minute session, not a burst of machine traffic). Time range is a
full day.

**Result: GOOD overall — median 0.169 s — but with one bad step: p95 14.576 s.**

| # | Step | What the engineer is asking | Time |
| ---: | --- | --- | ---: |
| 0 | `stats count()` | "How much data is there?" | 0.06 s |
| 1 | `stats count() by severityText` | "What's the error mix?" | 0.10 s |
| 2 | `where severityText='ERROR' \| stats count()` | "How many errors exactly?" | 0.12 s |
| 3 | `... \| stats count() by ...service.name` | "Which service is at fault?" | 0.08 s |
| 4 | `... \| stats count() by span(@timestamp, 1h)` | "When did it spike?" | 0.15 s |
| 5 | `... \| head 100` | "Show me 100 actual log lines." | 0.19 s |
| 6 | `... \| rex field=body '(?<w>\w+)' \| head 100` | "Pull a value out of the message text." | 0.21 s |
| 7 | `... \| rex field=body '(?<w>\w+)' \| stats count() by w` | **"Now count by that extracted value."** | **26.11 s** |
| 8 | `... \| dedup ...k8s.pod.name \| head 100` | "Which distinct pods are affected?" | 0.47 s |
| 9 | `... \| sort @timestamp \| head 50` | "Show me the 50 most recent." | 0.32 s |

**This is the finding.** Compare step 6 (0.21 s) with step 7 (26.11 s). Both extract the same value from the same
text. The only difference is that step 6 shows 100 rows while step 7 *counts* them. Extracted values do not exist
in the index, so the engine cannot summarise them on the data nodes — it must ship every matching row to one
coordinating node and count there. Consequences: it is ~120× slower, it gets linearly worse as the time range
widens, and the result is silently capped at 10,000 groups.

This is not an exotic query. "Extract something from the log line and count it" is one of the most natural things
an engineer does mid-incident, and it sits in the middle of an otherwise sub-second workflow.

---

### U4 — Alert-rule evaluation
**What it simulates:** the alerting system, re-running the same rule on a fixed schedule. What matters is not
speed but *reliability* — if an evaluation takes longer than its interval, the scheduler falls behind and alerts
get skipped.

**How it works:** one alert query re-run every 60 s for 10 minutes, counting how many evaluations finished inside
their 60-second budget.

**Result: GOOD — 10 of 10 evaluations inside budget, 0 missed. Median 0.049 s.**

**The query:**
```
source=mock-kv-pi {15m WINDOW} | stats count() by severityText
```
A typical threshold rule — "how many errors in the last 15 minutes" — of the shape used to trigger a page. It
finished in ~50 ms against a 60-second budget, i.e. roughly 1,200× more headroom than it needs.

---

### U5 — Multiple users at once
**What it simulates:** five different people using the cluster simultaneously for five different purposes — the
normal state of a shared cluster.

**How it works:** each user's workload is first measured alone to get a baseline, then all five run continuously
in parallel for 10 minutes. The interesting output is how much each user slowed down from sharing.

**Result: GOOD — all users stayed fast. Median 0.045 s, p95 0.155 s, zero errors.**

| "User" | What they're doing | Their query | Median under load |
| --- | --- | --- | ---: |
| dashboard | watching a dashboard | the 6 `ops_overview` panels | 0.148 s |
| session | investigating an incident | `source=mock-mixed-pi {1d} \| where severityText='ERROR' \| stats count() by ...service.name` | 0.048 s |
| alert | the alerting scheduler | `source=mock-kv-pi {15m} \| stats count() by severityText` | 0.038 s |
| adhoc_rex | **the heavy ad-hoc query** | `source=mock-json-http {1h} \| rex field=body '(?<w>\w+)' \| stats count() by w` | 7.291 s |
| browse | paging through raw logs | `source=mock-kv-pi {1d} \| head 100` | 0.157 s |

**Reading it:** the four ordinary users are unaffected by each other. The one heavy user (`adhoc_rex` — the same
problematic extract-then-count pattern from U3) is slow for itself, but notably *does not* drag the others down at
this level of load. That changes dramatically under heavier abuse — see U7.

**Caveat, stated plainly:** the "how much did each user slow down" ratios from this run are not trustworthy. The
solo baseline was measured cold while the shared phase ran for ten minutes with warm caches, so several users
appear *faster* when shared, which is not physically meaningful. We fixed this and re-ran it (see §5); the
absolute numbers above are unaffected.

---

### U6 — Widening the time range
**What it simulates:** a user zooming out — the same question asked over 1 hour, then 6 hours, 1 day, 3 days,
7 days.

**Result: GOOD — 0.069 s → 0.165 s. Only 2.4× slower for 168× more data.**

| Range | Time |
| --- | ---: |
| 1 hour | 0.069 s |
| 6 hours | 0.072 s |
| 1 day | 0.080 s |
| 3 days | 0.089 s |
| 7 days | 0.165 s |

**The query:**
```
source=mock-kv-pi {WINDOW} | stats count() by resource.attributes.k8s.namespace.name
```
Count log lines per Kubernetes namespace.

**Reading it:** this is the shape you want. Because the engine summarises on the data nodes, 168× more data costs
only 2.4× more time. Contrast with the extract-then-count pattern in U3, which grows in direct proportion to the
data. This one test cleanly separates "queries that scale" from "queries that don't."

---

### U7 — Noisy-neighbour isolation (the WLM test)
**What it simulates:** the shared-cluster nightmare. One well-behaved user is watching a dashboard. Another user
starts hammering the cluster with expensive ad-hoc queries. Does the innocent user suffer — and does Workload
Management protect them?

**How it works:** two genuinely separate logins, each assigned to a workload group with its own resource budget:
- `dash_user` → **dashboards** group, "soft" limits (may borrow spare capacity), 60% budget
- `adhoc_user` → **adhoc** group, "enforced" limits (gets cut off when over budget), 30% budget

Three 5-minute phases: the dashboard user **alone** (the baseline), then dashboard **+ abusive neighbour with WLM
off**, then the identical load with **WLM on**.

The neighbour cycles 27 deliberately expensive queries over a full day of data — full-text regex scans,
wildcard text matching, ~10.8-million-value groupings, a cross-index sweep over all 10 indices, log-pattern
clustering, and the extract-then-count pattern from U3, on every one of the 10 log formats.

**Result: PASS** — and after we strengthened the test (see §5), a very clear one:

| Phase | Dashboard user's p95 | How much worse than alone |
| --- | ---: | ---: |
| Alone | 0.152 s | — |
| **Noisy neighbour, WLM off** | **111.29 s** | **732× worse** |
| **Noisy neighbour, WLM on** | **0.258 s** | **1.7× worse** |

**Reading it — this is the headline.** Without WLM, a single abusive user turns a quarter-second dashboard into a
nearly two-minute one. It is not a degradation; it is an outage for that user. With WLM enabled, the same abuse
costs the dashboard user 1.7× — still a quarter of a second — while the abusive workload absorbed **150,910
rejections**. The cluster also reached 99–100% CPU during this phase and *still* served the protected user in
0.26 s.

Put in one sentence for a customer: **on a shared PPL cluster, WLM is the difference between a two-minute
dashboard and a quarter-second one.**

---

## 4. Cluster health during the tests

| Scenario | Peak CPU | Peak heap | Queued requests | Rejections |
| --- | ---: | ---: | ---: | ---: |
| U1 dashboard | 8% | 77% | 0 | 0 |
| U2 auto-refresh | 45% | 79% | 0 | 0 |
| U3 investigation | 43% | 65% | 0 | 0 |
| U4 alert rule | 58% | 65% | 0 | 0 |
| U5 five users | 65% | 79% | 2 | 0 |
| U6 long range | 18% | 77% | 0 | 0 |
| U7 noisy neighbour | 100% | 79% | 545 | 0 |

Memory stayed flat throughout and the cluster never rejected a request on its own account. Only the deliberately
abusive U7 phase pushed CPU to saturation — and even then the protected user was unaffected.

---

## 5. Two measurement flaws we found in our own tests

Recorded deliberately, because a benchmark that hides its own weaknesses is not worth much.

**1. The cache flaw (affected all earlier runs — now fixed).** Repeats used a fixed time window, so the cluster
answered from cache and reported dashboards 20–50× faster than reality. Fixed by sliding the window on every
repeat. Effect: U1 went from a flattering 0.25 s to an honest 0.54 s. All numbers in this document are the honest
ones.

**2. Two flaws in this run specifically — both fixed and re-run:**

- *U5's slowdown ratios were meaningless* (baseline measured cold vs. a warm 10-minute comparison). After fixing:
  the two high-traffic users read **1.03×** and **0.99×** — correctly showing no degradation from sharing.
- *U7's abusive neighbour was too weak.* Originally it was a single sequential loop, which barely touched the
  dashboard user (1.1× even with WLM off) — so the test "passed" without ever proving that WLM protects anyone.
  Re-run with 20 parallel abusive loops, it produced the 732× vs 1.7× result above, which is a genuine
  demonstration rather than an assumption.

**Still outstanding (being addressed):** we verify speed but not yet *correctness* at this scale; and each scenario
has been run once, so we cannot yet distinguish a real regression from normal run-to-run variation.

---

## 6. Recommendations

1. **Treat the extract-then-count pattern as a known limitation and document it for users**, with the workaround:
   if you need to group by a value, index it as a proper field rather than extracting it at query time. We should
   file this as a tracked issue.
2. **Recommend WLM to any customer running a shared PPL cluster.** We now have a concrete number (732× → 1.7×)
   rather than a general claim.
3. **Add correctness checking and run-to-run variance measurement** before these figures are used as a release
   gate — they are currently strong evidence, not yet a certified baseline.

---

## 7. Where the data lives

| What | Where |
| --- | --- |
| Generated tables (all 9 plan deliverables) | `docs/dev/bench/perf-suite/results/fidelity-usecase-v1/report.md` |
| Raw measurements | `.../fidelity-usecase-v1/usecase.json` |
| The corrected U5/U7 re-run | `.../fidelity-usecase-v2-u5u7/` |
| Test code | `docs/dev/bench/perf-suite/suite/usecase_runner.py` |
| Findings & action tracker | Chorus doc `ctWafvk3X0c2` |
| Test plan this measures against | Chorus doc `Wz9MgtrddN1P` §2.3 |
