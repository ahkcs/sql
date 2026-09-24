# PPL Use-case Report — realistic user scenarios (plan §2.3)

| Field | Value |
| --- | --- |
| run_id | usecase-20260924T163514Z-7dfc |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| tier | tier2 |
| cache_mode | rolling |
| window_step_s | 30 |
| u1_ranges | 1h,1d,7d |
| u3_range | 7d |
| identities | ['admin'] |
| dashboard_variants | ['error_triage', 'ops_overview', 'service_health'] |
| index_patterns | ['mock-kv-pi', 'mock-json-*', 'mock-*'] |

_Rolling window: each iteration slides a constant-width window back by `window_step_s`, so no refresh is served from the shard request cache. (A literal `now-<range>` cannot be used — the dataset ends 2026-04-11.)_

## (1) Per-scenario verdict cards

| Scenario | verdict | median s | p95 s | max s | errors | warnings |
| --- | --- | --- | --- | --- | --- | --- |
| U1 dashboard refresh | GOOD | 0.708 | 1.494 | 1.841 | 0 | 0 |
| U3 investigation session | GOOD | 0.179 | 13.658 | 24.426 | 0 | 0 |

User-facing verdicts: GOOD <5s · ACCEPTABLE 5-10s · POOR >10s. **warnings** counts responses flagged incomplete — a shard that exceeds its per-shard timeout returns partial data at HTTP 200, and results truncate silently at the 10,000-row size limit, so a non-zero count means a "passing" number may reflect less work than the query asked for.


## (2) U1 dashboard refresh — variant x index pattern

| variant | index pattern | range | panels | wall-clock s | avg panel s | slowest panel s | errors | warn | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ops_overview | `mock-*` | 7d | 6 | 1.841 | 1.167 | 1.840 | 0 | 0 | GOOD |
| ops_overview | `mock-*` | 1h | 6 | 1.346 | 0.575 | 1.344 | 0 | 0 | GOOD |
| ops_overview | `mock-json-*` | 7d | 6 | 1.241 | 0.869 | 1.239 | 0 | 0 | GOOD |
| ops_overview | `mock-json-*` | 1h | 6 | 0.973 | 0.620 | 0.971 | 0 | 0 | GOOD |
| ops_overview | `mock-*` | 1d | 6 | 0.957 | 0.488 | 0.956 | 0 | 0 | GOOD |
| error_triage | `mock-*` | 1h | 5 | 0.717 | 0.488 | 0.716 | 0 | 0 | GOOD |
| ops_overview | `mock-kv-pi` | 1h | 6 | 0.714 | 0.460 | 0.712 | 0 | 0 | GOOD |
| ops_overview | `mock-json-*` | 1d | 6 | 0.708 | 0.364 | 0.706 | 0 | 0 | GOOD |
| error_triage | `mock-json-*` | 1h | 5 | 0.544 | 0.343 | 0.543 | 0 | 0 | GOOD |
| ops_overview | `mock-kv-pi` | 7d | 6 | 0.478 | 0.391 | 0.477 | 0 | 0 | GOOD |
| service_health | `mock-*` | 1h | 5 | 0.386 | 0.243 | 0.385 | 0 | 0 | GOOD |
| ops_overview | `mock-kv-pi` | 1d | 6 | 0.337 | 0.181 | 0.336 | 0 | 0 | GOOD |
| error_triage | `mock-kv-pi` | 1h | 5 | 0.249 | 0.164 | 0.247 | 0 | 0 | GOOD |
| service_health | `mock-json-*` | 1h | 5 | 0.222 | 0.168 | 0.221 | 0 | 0 | GOOD |
| service_health | `mock-kv-pi` | 1h | 5 | 0.141 | 0.099 | 0.140 | 0 | 0 | GOOD |

_Page load = slowest panel returning, so wall-clock is the user-facing number._

## (4) U3 investigation session — latency per step (window 7d)

| step | action | s | rows | verdict | missed <5s | |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | broad_count | 0.043 | 1 | GOOD |  | `#` |
| 1 | count_by_sev | 0.170 | 4 | GOOD |  | `#` |
| 2 | filter_error | 0.043 | 1 | GOOD |  | `#` |
| 3 | error_by_service | 0.089 | 120 | GOOD |  | `#` |
| 4 | error_timeline | 0.171 | 168 | GOOD |  | `#` |
| 5 | error_sample | 0.188 | 100 | GOOD |  | `#` |
| 6 | rex_extract | 0.204 | 100 | GOOD |  | `#` |
| 7 | rex_aggregate | 24.426 | 10000 | POOR | **MISS** | `############################` |
| 8 | dedup_pod | 0.497 | 100 | GOOD |  | `#` |
| 9 | sort_recent | 0.347 | 50 | GOOD |  | `#` |

1 of 10 steps missed the <5s target: rex_aggregate.

## (9) Cluster metrics per scenario

| scenario | peak CPU % | peak heap % | peak search queue | Δ rejected | samples |
| --- | --- | --- | --- | --- | --- |
| U1 | 69 | 79 | 0 | 0 | 3 |
| U3 | 69 | 79 | 0 | 0 | 16 |

Full timestamped series per scenario (plus pre/post snapshots, and for U7 the per-group `_wlm/stats` deltas) are attached to results.json.

