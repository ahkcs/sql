# Expansion TODO — data types, catalogue, reingest, snapshot

Working checklist for the next phase: widen the mapping, widen the query catalogue, reload the fidelity
dataset, snapshot it. Ordered by dependency — **Phase 0 blocks everything**, and the catalogue work
(Phase 2) can proceed in parallel with Phase 1 but cannot be *validated* until the data lands.

Design rationale lives in [RESEED-SPEC.md](RESEED-SPEC.md). Current findings live in Chorus `ctWafvk3X0c2`.

---

## Phase 0 — decisions that block the reload

A reload is ~6 h. Every one of these changes the data we produce, so they must be settled first or we
reload twice.

- [ ] **D1. Load alongside or overwrite?** Recommend **alongside** as `mock2-*`: disk is at 17 % (2.4 TB free
      per node), so the existing `mock-*` baseline stays queryable and old-vs-new becomes a direct A/B
      instead of a re-baseline on faith. Rollback becomes "delete an index pattern."
- [ ] **D2. Roll timestamps forward to "now"?** Lets us use literal `now-1h` and drop the sliding-window
      workaround, so dashboards behave as they do live. Cost: the dataset ages out of absolute windows, and
      a moving window weakens week-over-week comparability — which works against D1's purpose. **Pick one
      priority: realism or reproducibility.**
- [ ] **D3. Index granularity.** (a) keep 10 fat indices (preserves the ~13 GB/shard we match to the
      customer), (b) mirror ~306 daily indices (makes PIT exhaustion reproducible but shards drop to ~50 MB
      and distort every latency number), (c) **recommended:** keep fat, add a separate small
      daily-granularity set purely for fan-out/PIT tests.
- [ ] **D4. Scale.** Same 1.83 B docs, or change the scale-down factor (N=8 → N=4)?
- [ ] **D5. Is correctness verification in scope for this reload?** If yes, Phase 1 must also produce ground
      truth (T1.5), which is real work but closes our biggest structural gap.

---

## Phase 1 — mapping + generator

- [ ] **T1.1** Extend `mock_data/schemas/mock-index-template-wide.json` with the 11 missing types, mirroring
      the field set already proven in `mock_data/types_index.py`: `boolean`, `double`, `float`, `half_float`,
      `scaled_float`, `unsigned_long`, `ip`, `wildcard`, `flattened`, `nested`, `alias`.
- [ ] **T1.2** Add the **`env` trio** — `env_text` (bare `text`), `env_kw` (`keyword`), `env_multi`
      (`text` + `.keyword`) — carrying **identical values**. This is the customer's slow
      `stats count() by env`; three mappings over one value isolates mapping from cardinality.
- [ ] **T1.3** Decide per-type value distributions, not just types: cardinality, ranges, and **null rate**.
      Null rate matters — `isnull` / `fillnull` behaviour and pushdown differ on sparse fields, and today
      every field is fully populated.
- [ ] **T1.4** Update `mock_data/generator.py` to emit the new fields per body format. Verify with
      `--dry-run` and review a sample doc.
- [ ] **T1.5** *(gated on D5)* Extend `mock_data/expected.py` with ground-truth group counts for the new
      fields, so correctness can be asserted rather than assumed.
- [ ] **T1.6** Check `index.mapping.total_fields.limit` still fits (currently 2000 for the wide schema).
- [ ] **T1.7** Confirm shard count still targets ~13 GB/shard at the chosen scale.

---

## Phase 2 — catalogue expansion (parallelisable with Phase 1)

- [ ] **T2.1 Index-pattern axis as a first-class dimension.** Today **1 of 96** latency templates uses a
      wildcard, and the pushdown matrix uses none. Add single / partial (`mock-json-*`) / full (`mock-*`)
      across a representative subset — fan-out goes 28 → 140 → 281 primary shards, and that is how
      customers query.
- [ ] **T2.2 Type axis in the latency catalogue.** The pushdown matrix says *whether* something pushes down;
      this measures what it *costs* at 183 M docs.
- [ ] **T2.3 Pushdown assertion inside the main runner.** Record per latency point whether the aggregation
      pushed down. Cheap (one `_explain` per template) and it turns every latency number into a diagnosis
      instead of just a measurement.
- [ ] **T2.4 Capture `rows` and warnings on every point.** Partly done for the Use-case pillar; extend to
      Perf and Load. **Truncation at the 10,000-row `size_limit` is currently silent** — no warning, no
      error — so a fast number can mean less work was done.
- [ ] **T2.5 Add the missing query shapes:**
  - [ ] wildcard **non-aggregate** scan (`source=mock-* | head 100000`) — the PIT-exhaustion shape, still
        uncovered
  - [ ] `rex` on a **keyword** field vs on `body` — isolates scripted-aggregation cost from `_source`-load
        cost (this also settles the open question about *why* the 26 s query is slow)
  - [ ] pathological regex (nested quantifiers / backtracking), not just `(?<w>\w+)`
  - [ ] bare-`text` aggregation at low cardinality (`env_text`) vs high (`body`)
  - [ ] cross-index aggregation where field **types conflict** between indices — a known bug area
- [ ] **T2.6 Correctness assertions** *(gated on D5/T1.5)*: cross-index results must equal the sum of
      per-index results. Cross-index merge is exactly where silent wrongness would hide.

---

## Phase 3 — reingest

- [ ] **T3.1** Verify the existing `mock-fidelity-1d` snapshot is actually **restorable** before touching
      anything. A snapshot we have never restored is not a rollback plan.
- [ ] **T3.2** Land Phase 1 changes; review `--dry-run` sample docs.
- [ ] **T3.3** Load `mock2-*` from the loader fleet under systemd (same unattended pattern as the pillar
      runs), `python3 -u`, per-index progress. ~6 h.
- [ ] **T3.4** Verify: doc counts per index, mapping applied, shard sizes ≈13 GB, cluster green, no
      unassigned shards.
- [ ] **T3.5** Spot-check the new fields actually queryable via PPL — every type, one query each.

---

## Phase 4 — snapshot + re-baseline

- [ ] **T4.1** Snapshot `mock2-*` to the S3 repo, then **restore it into a throwaway index** to prove the
      snapshot works (closes the T3.1 gap permanently).
- [ ] **T4.2** Run the full pushdown matrix over `mock2-*` — expect coverage of all types across all
      index patterns.
- [ ] **T4.3** Re-run Perf / Load / Use-case against `mock2-*` and **diff against the `mock-*` baseline**.
      Anything that moved and was not an intended change means the reseed altered something we did not
      model.
- [ ] **T4.4** Establish a **variance baseline**: run one pillar 3× and compute per-query coefficient of
      variation. Without this we cannot tell a regression from noise, and any alert threshold is a guess.
- [ ] **T4.5** Update the setup doc (`Itz4zsOtkhKx`) and tracker (`ctWafvk3X0c2`) with the new dataset facts.

---

## Phase 5 — cleanup and follow-ons

- [ ] **T5.1** Decide whether to retain `mock-*` after one clean comparison (disk allows it).
- [ ] **T5.2** Grant the loader role `ssm:PutParameter` — without it the `dash_user` / `adhoc_user`
      passwords are ephemeral per run and U7 is not reproducible.
- [ ] **T5.3** Treat "duplicate rule exists" as success in `wlm.provision()` so re-provisioning is clean.
- [ ] **T5.4** Only then point the weekly automation at `mock2-*`, so trend data starts on the final data
      model.

---

## Not blocking, but do not lose

- [ ] Correct the two statements now known to be wrong (rex pushes down as a **scripted composite
      aggregation**, not a coordinator-side fallback; and its latency does **not** grow linearly with the
      window) in tracker F6, `results/fidelity-usecase-v1/EXPLAINED.md`, and Chorus `sanzZe3QLdP3`.
- [ ] File F1–F7 as GitHub issues — seven real findings currently live only in a Chorus doc.
- [ ] Load `mock-types` and run the committed 254-point matrix; it needs no reload and answers the type
      questions today.
