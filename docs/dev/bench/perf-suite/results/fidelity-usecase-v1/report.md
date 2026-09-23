# PPL Use-case Report — realistic user scenarios (plan §2.3)

| Field | Value |
| --- | --- |
| run_id | usecase-20260923T184148Z-73f6 |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| tier | tier2 |
| cache_mode | rolling |
| window_step_s | 30 |
| identities | ['admin', 'dash_user', 'adhoc_user'] |
| dashboard_variants | ['error_triage', 'ops_overview', 'service_health'] |
| index_patterns | ['mock-kv-pi', 'mock-json-*', 'mock-*'] |

_Rolling window: each iteration slides a constant-width window back by `window_step_s`, so no refresh is served from the shard request cache. (A literal `now-<range>` cannot be used — the dataset ends 2026-04-11.)_

## (1) Per-scenario verdict cards

| Scenario | verdict | median s | p95 s | max s | errors |
| --- | --- | --- | --- | --- | --- |
| U1 dashboard refresh | GOOD | 0.543 | 1.138 | 1.292 | 0 |
| U2 auto-refresh | GOOD | 0.162 | 0.293 | 0.294 | 0 |
| U3 investigation session | GOOD | 0.169 | 14.576 | 26.114 | 0 |
| U4 alert-rule | GOOD | 0.049 | 0.054 | 0.058 | 0 |
| U5 multi-user mixed | GOOD | 0.046 | 0.159 | 26.643 | 0 |
| U6 long-range | GOOD | 0.080 | 0.150 | 0.165 | 0 |
| U7 WLM noisy-neighbor | PASS | - | - | - | - |

User-facing verdicts: GOOD <5s · ACCEPTABLE 5-10s · POOR >10s.


## (2) U1 dashboard refresh — variant x index pattern

| variant | index pattern | panels | wall-clock s | avg panel s | slowest panel s | errors | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ops_overview | `mock-*` | 6 | 1.292 | 0.593 | 1.291 | 0 | GOOD |
| ops_overview | `mock-json-*` | 6 | 0.908 | 0.545 | 0.907 | 0 | GOOD |
| error_triage | `mock-*` | 5 | 0.710 | 0.382 | 0.709 | 0 | GOOD |
| ops_overview | `mock-kv-pi` | 6 | 0.685 | 0.489 | 0.683 | 0 | GOOD |
| error_triage | `mock-json-*` | 5 | 0.543 | 0.297 | 0.542 | 0 | GOOD |
| service_health | `mock-*` | 5 | 0.404 | 0.245 | 0.403 | 0 | GOOD |
| service_health | `mock-json-*` | 5 | 0.259 | 0.207 | 0.258 | 0 | GOOD |
| error_triage | `mock-kv-pi` | 5 | 0.220 | 0.153 | 0.219 | 0 | GOOD |
| service_health | `mock-kv-pi` | 5 | 0.128 | 0.108 | 0.127 | 0 | GOOD |

_Page load = slowest panel returning, so wall-clock is the user-facing number._

## (3) U2 auto-refresh trend — wall-clock per refresh (cadence 30s)

| refresh | t+s | wall s | slowest panel s | errors | |
| --- | --- | --- | --- | --- | --- |
| 0 | 0.3 | 0.294 | 0.293 | 0 | `############################` |
| 1 | 30.3 | 0.292 | 0.290 | 0 | `############################` |
| 2 | 60.2 | 0.156 | 0.154 | 0 | `###############` |
| 3 | 90.3 | 0.161 | 0.159 | 0 | `###############` |
| 4 | 120.4 | 0.271 | 0.269 | 0 | `##########################` |
| 5 | 150.3 | 0.157 | 0.155 | 0 | `###############` |
| 6 | 180.3 | 0.153 | 0.151 | 0 | `###############` |
| 7 | 210.4 | 0.164 | 0.162 | 0 | `################` |
| 8 | 240.4 | 0.158 | 0.156 | 0 | `###############` |
| 9 | 270.4 | 0.162 | 0.160 | 0 | `###############` |

First refresh 0.294s -> last 0.162s (stable). 10 refreshes, p95 0.293s.

## (4) U3 investigation session — latency per step

| step | action | s | verdict | missed <5s | |
| --- | --- | --- | --- | --- | --- |
| 0 | broad_count | 0.060 | GOOD |  | `#` |
| 1 | count_by_sev | 0.100 | GOOD |  | `#` |
| 2 | filter_error | 0.115 | GOOD |  | `#` |
| 3 | error_by_service | 0.082 | GOOD |  | `#` |
| 4 | error_timeline | 0.149 | GOOD |  | `#` |
| 5 | error_sample | 0.189 | GOOD |  | `#` |
| 6 | rex_extract | 0.210 | GOOD |  | `#` |
| 7 | rex_aggregate | 26.114 | POOR | **MISS** | `############################` |
| 8 | dedup_pod | 0.474 | GOOD |  | `#` |
| 9 | sort_recent | 0.315 | GOOD |  | `#` |

1 of 10 steps missed the <5s target: rex_aggregate.

## (5) U4 alert-rule cadence

| cadence s | evaluations | within budget | missed | median s | p95 s | errors |
| --- | --- | --- | --- | --- | --- | --- |
| 60 | 10 | 10 | 0 | 0.049 | 0.054 | 0 |

## (6) U5 multi-user mixed — per user vs solo baseline

| user | n | solo median s | mixed median s | median x | solo p95 s | mixed p95 s | p95 x | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adhoc_rex | 77 | 23.511 | 7.291 | 0.31 | 25.760 | 13.861 | 0.54 | ACCEPTABLE |
| alert | 15186 | 0.048 | 0.038 | 0.78 | 0.337 | 0.050 | 0.15 | GOOD |
| browse | 3737 | 0.517 | 0.157 | 0.30 | 0.621 | 0.176 | 0.28 | GOOD |
| dashboard | 4018 | 0.492 | 0.148 | 0.30 | 0.519 | 0.163 | 0.31 | GOOD |
| session | 12036 | 0.408 | 0.048 | 0.12 | 0.430 | 0.062 | 0.14 | GOOD |

_x = mixed / solo; >1 means the user degraded under concurrent load._

## (7) U6 long-range latency curve — same query, widening range

| range | s | verdict | |
| --- | --- | --- | --- |
| 1h | 0.069 | GOOD | `############` |
| 6h | 0.072 | GOOD | `############` |
| 1d | 0.080 | GOOD | `##############` |
| 3d | 0.089 | GOOD | `###############` |
| 7d | 0.165 | GOOD | `############################` |

Growth 1h -> 7d: 2.4x.

## (8) U7 noisy-neighbor isolation — WLM off vs on

| phase | dashboards p95 s | dashboards median s | dash errors | adhoc n | adhoc errors | adhoc 429 |
| --- | --- | --- | --- | --- | --- | --- |
| solo | 0.153 | 0.146 | 0 | - | - | - |
| wlm_off | 0.168 | 0.147 | 0 | 21 | 0 | 0 |
| wlm_on | 0.156 | 0.144 | 0 | 19 | 9 | 0 |

- dashboards-user p95 degradation vs solo: **WLM off 1.10x -> WLM on 1.02x**
- adhoc group delta (from `_wlm/stats`): `{'completions': 1065, 'rejections': 189, 'cancellations': 343}`

| gate | result |
| --- | --- |
| dash_p95_degradation_wlm_on_le_2x | PASS |
| dash_errors_wlm_on_is_zero | PASS |
| adhoc_rejections_delta_gt_0 | PASS |
| adhoc_not_starved | PASS |

## (9) Cluster metrics per scenario

| scenario | peak CPU % | peak heap % | peak search queue | Δ rejected | samples |
| --- | --- | --- | --- | --- | --- |
| U1 | 8 | 77 | 0 | 0 | 1 |
| U2 | 45 | 79 | 0 | 0 | 60 |
| U3 | 43 | 65 | 0 | 0 | 56 |
| U4 | 58 | 65 | 0 | 0 | 120 |
| U5 | 65 | 79 | 7 | 0 | 135 |
| U6 | 18 | 77 | 0 | 0 | 1 |
| U7 | 100 | 79 | 3 | 0 | 188 |

Full timestamped series per scenario (plus pre/post snapshots, and for U7 the per-group `_wlm/stats` deltas) are attached to results.json.

