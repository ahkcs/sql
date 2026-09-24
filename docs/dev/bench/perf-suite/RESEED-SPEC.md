# Full fidelity reseed — specification (proposed, not yet executed)

**Status:** draft for review. Nothing has been reloaded.
**Why a spec:** a full reload is ~6 h. Every data-model change we want should land in **one** reload, not four.
**Cheap alternative already built:** `mock-types` (`mock_data/types_index.py`) answers the type-coverage questions
at ~10 M docs without touching the fidelity dataset. **Do that first**; this spec is for the questions it cannot
answer.

---

## 1. What the current dataset cannot answer

| Gap | Consequence | Fixed by |
| --- | --- | --- |
Only 7 mapped types present (keyword, text, long, integer, byte, date, object) | 11 types untested for pushdown | `mock-types` (done) **or** change 2 below |
Bare `text` only exists as high-cardinality `body` | cannot separate "no doc_values" from "10 M distinct values" | `mock-types` `env_*` trio (done) |
`@timestamp` ends **2026-04-11** (historical) | `now-<range>` matches zero docs, so rolling windows are simulated by sliding within the data | change 3 |
10 fat indices (28 shards each, ~13 GB/shard) vs the customer's ~306 daily indices | PIT-context exhaustion, shard fan-out, `can_match` skipping and cluster-state size are all unreproducible | change 4 |
No per-type latency at fidelity scale | we know *whether* something pushes down, not what it costs on 183 M docs | change 2 |

---

## 2. Proposed changes

### Change 1 — load alongside, do not overwrite  ★ strongly recommended
Write the new dataset to a **new index set** (`mock2-*`) and keep `mock-*` in place.

Disk makes this free: each data node is at **17 % (≈520 GB of 2.9 TB)**, with 2.4 TB free. A second full dataset
takes the cluster to roughly 36 %.

Payoff: the existing Perf/Load/Use-case baseline stays queryable, so old-vs-new is a direct A/B instead of a
re-baseline on faith. Rollback is deleting an index pattern rather than a 6 h restore.

### Change 2 — add the 11 missing types to the fidelity schema
Same fields as `mock_data/types_index.py`: `boolean`, `double`, `float`, `half_float`, `scaled_float`,
`unsigned_long`, `ip`, `wildcard`, `flattened`, `nested`, `alias`, plus the `env_text` / `env_kw` / `env_multi`
trio.

Touches `mock_data/schemas/mock-index-template-wide.json` and `mock_data/generator.py`.
Buys: per-type latency at 183 M docs (the matrix gives only pushdown yes/no).
Cost: small — the fields are narrow next to the existing ~3,000.

### Change 3 — roll the time window forward to "now"  ★ high value, needs a harness change
Seed `@timestamp` so the window **ends at load time** rather than at a fixed 2026-04-11.

Payoff:
- literal `now-1h` / `now-7d` works, so the Use-case pillar can drop the sliding-window workaround entirely
- dashboards behave as they do against a live cluster
- removes a standing "this is not quite how customers query" caveat

Cost / risk:
- **the dataset ages.** Absolute-window queries drift out of the data over weeks, so either re-seed periodically or
  make every time filter relative. Decide which before committing.
- the harness anchors on `distributions.ANCHOR_MS` in `catalogue.time_where()` and
  `usecase_runner.window_where()`; both need a relative mode.
- makes runs less reproducible by construction (the window moves), which slightly weakens week-over-week
  comparison — the opposite of what change 1 buys. **Tension worth an explicit decision.**

### Change 4 — index granularity: 10 fat vs ~306 daily  ☐ decide deliberately
The customer has ~306 backing indices; we have 10. This is the only change that makes PIT-context exhaustion
(GH #5698 / #5634) reproducible, because that bug needs >300 shards participating on one node.

Options:
- **(a) keep 10 fat indices** — preserves ~13 GB/shard, which is the single most important latency knob we match.
- **(b) mirror ~306 daily indices** at the same total volume — shards drop to ~50 MB, which distorts *every*
  latency number and adds fan-out overhead the customer does not have at their shard size.
- **(c) hybrid: a separate small daily-granularity index set** purely for fan-out/PIT tests, leaving the fidelity
  set fat. **Recommended** — it buys the missing coverage without contaminating the latency baseline.

### Change 5 — ground truth for correctness checking
Extend `mock_data/expected.py` so the new fields have known group counts. Without this the reseeded dataset
inherits today's biggest gap: we measure speed but never verify results, and we have already seen results silently
truncate at 10,000 groups and return partial data on shard timeout.

---

## 3. Execution plan (once approved)

1. Snapshot first. `mock-fidelity-1d` already exists; confirm it is restorable before touching anything.
2. Land the schema + generator changes, with `--dry-run` sample docs reviewed.
3. Load `mock2-*` on the loader fleet under systemd (same unattended pattern as the pillar runs). ~6 h.
4. Verify: doc counts, mapping, shard sizes ≈13 GB, cluster green.
5. Re-run **all** pillars against `mock2-*` and diff against the `mock-*` baseline — expect no change except
   where a change was intended. Unexplained deltas mean the reseed altered something we did not model.
6. Only then cut the weekly automation over to `mock2-*`.
7. Retire `mock-*` after one clean comparison, or keep it if disk allows.

---

## 4. Sequencing

| When | What |
| --- | --- |
Now | `mock-types` side index + the 147-point types matrix (built, needs a load + run) |
Before automation produces trend data | this reseed, so the trend starts on the final data model |
Not blocking either | change 4(c), as its own fan-out/PIT experiment |

**Do not start the weekly cron on the current dataset and expect the trend to survive this reseed** — either accept
that the first weeks are disposable, or reseed first.

---

## 5. Open questions for review

1. Change 3 (rolling "now") trades reproducibility for realism. Which do we want more?
2. Change 4: accept option (c), or is reproducing PIT exhaustion worth a dedicated many-small-index dataset?
3. Should `mock2-*` be the same 1.83 B docs, or is this the moment to change scale (N=8 → N=4)?
4. Is correctness checking (change 5) in scope for the reseed, or a separate workstream?
