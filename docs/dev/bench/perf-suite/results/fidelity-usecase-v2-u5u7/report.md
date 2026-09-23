# PPL Use-case Report — realistic user scenarios (plan §2.3)

| Field | Value |
| --- | --- |
| run_id | usecase-20260923T210329Z-5414 |
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
| U5 multi-user mixed | GOOD | 0.045 | 0.155 | 8.752 | 0 |
| U7 WLM noisy-neighbor | PASS | - | - | - | - |

User-facing verdicts: GOOD <5s · ACCEPTABLE 5-10s · POOR >10s.


## (6) U5 multi-user mixed — per user vs solo baseline

| user | n | solo median s | mixed median s | median x | solo p95 s | mixed p95 s | p95 x | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| adhoc_rex | 92 | 22.198 | 6.868 | 0.31 | 23.472 | 7.788 | 0.33 | ACCEPTABLE |
| alert | 15486 | 0.036 | 0.037 | 1.03 | 0.037 | 0.047 | 1.28 | GOOD |
| browse | 3858 | 0.210 | 0.152 | 0.72 | 0.476 | 0.171 | 0.36 | GOOD |
| dashboard | 4169 | 0.144 | 0.143 | 0.99 | 0.470 | 0.157 | 0.33 | GOOD |
| session | 12302 | 0.469 | 0.047 | 0.10 | 0.479 | 0.059 | 0.12 | GOOD |

_x = mixed / solo; >1 means the user degraded under concurrent load._

## (8) U7 noisy-neighbor isolation — WLM off vs on

| phase | dashboards p95 s | dashboards median s | dash errors | adhoc n | adhoc errors | adhoc 429 |
| --- | --- | --- | --- | --- | --- | --- |
| solo | 0.152 | 0.142 | 0 | - | - | - |
| wlm_off | 111.288 | 54.080 | 0 | 85 | 0 | 0 |
| wlm_on | 0.258 | 0.153 | 0 | 1724 | 1481 | 0 |

- dashboards-user p95 degradation vs solo: **WLM off 732.16x -> WLM on 1.70x**
- adhoc group delta (from `_wlm/stats`): `{'completions': 158677, 'rejections': 150910, 'cancellations': 1453}`

| gate | result |
| --- | --- |
| dash_p95_degradation_wlm_on_le_2x | PASS |
| dash_errors_wlm_on_is_zero | PASS |
| adhoc_rejections_delta_gt_0 | PASS |
| adhoc_not_starved | PASS |

## (9) Cluster metrics per scenario

| scenario | peak CPU % | peak heap % | peak search queue | Δ rejected | samples |
| --- | --- | --- | --- | --- | --- |
| U5 | 100 | 79 | 2 | 0 | 152 |
| U7 | 99 | 79 | 545 | 0 | 227 |

Full timestamped series per scenario (plus pre/post snapshots, and for U7 the per-group `_wlm/stats` deltas) are attached to results.json.

