# PPL Perf Report

| Field | Value |
| --- | --- |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| reps | 3 |
| warmup | 1 |
| time_ranges | ['5m', '15m', '1h', '1d'] |
| loaded_docs | 183000000 |

## Latency verdicts

| Verdict | Count |
| --- | ---: |
| FAST | 75 |
| ACCEPTABLE | 10 |
| SLOW | 3 |

## p95 by category (seconds)

| Category | runs | min | median | max |
| --- | ---: | ---: | ---: | ---: |
| bad-queries | 8 | 0.353 | 0.689 | 1.252 |
| browse-table | 4 | 0.074 | 0.096 | 0.196 |
| dedup | 8 | 0.465 | 3.763 | 21.875 |
| eval-stats | 8 | 0.056 | 0.081 | 0.234 |
| field-extract | 4 | 0.059 | 0.107 | 0.130 |
| rex | 8 | 3.215 | 14.909 | 61.820 |
| simple-search | 8 | 0.850 | 2.189 | 61.704 |
| stacked | 8 | 0.062 | 0.106 | 0.177 |
| stats-aggregate | 16 | 0.053 | 0.099 | 0.593 |
| timechart | 8 | 0.081 | 0.186 | 0.252 |
| top-n | 8 | 0.129 | 0.153 | 0.261 |

## Slowest 10 (by p95)

| Query | range | p95_s | verdict | known_slow |
| --- | --- | ---: | --- | --- |
| rex_body_word_HIGH | 1d | 61.820 | SLOW | True |
| search_body_like | 1d | 61.704 | SLOW | False |
| rex_http_method | 1d | 52.595 | SLOW | False |
| rex_body_word_HIGH | 1h | 23.945 | ACCEPTABLE | True |
| rex_http_method | 1h | 23.604 | ACCEPTABLE | False |
| dedup_pod_HIGHCARD | 1d | 21.875 | ACCEPTABLE | True |
| dedup_pod_HIGHCARD | 1h | 18.022 | ACCEPTABLE | True |
| dedup_pod_HIGHCARD | 15m | 10.484 | ACCEPTABLE | True |
| search_error | 1d | 9.609 | ACCEPTABLE | False |
| search_body_like | 1h | 7.677 | ACCEPTABLE | False |

## Cluster metrics (final)

| Metric | Value |
| --- | --- |
| cluster_status | green |
| cpu_max_pct | 11 |
| heap_max_pct | 78 |
| search_queue | 0 |
| active_shards | 647 |
| search_rejected_delta | 0 |
| old_gc_ms_delta | 0 |
