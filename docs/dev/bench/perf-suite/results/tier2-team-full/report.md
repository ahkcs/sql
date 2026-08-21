# PPL Perf Report

| Field | Value |
| --- | --- |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| reps | 3 |
| warmup | 1 |
| time_ranges | ['5m', '15m', '1h', '1d'] |
| loaded_docs | 25000000 |

## Latency verdicts

| Verdict | Count |
| --- | ---: |
| FAST | 79 |
| ACCEPTABLE | 8 |
| SLOW | 1 |

## p95 by category (seconds)

| Category | runs | min | median | max |
| --- | ---: | ---: | ---: | ---: |
| bad-queries | 8 | 0.159 | 0.195 | 2.059 |
| browse-table | 4 | 0.046 | 0.056 | 0.069 |
| dedup | 8 | 0.167 | 2.527 | 7.088 |
| eval-stats | 8 | 0.043 | 0.048 | 0.447 |
| field-extract | 4 | 0.037 | 0.040 | 0.043 |
| rex | 8 | 0.511 | 3.484 | 29.863 |
| simple-search | 8 | 0.453 | 1.322 | 48.881 |
| stacked | 8 | 0.036 | 0.045 | 0.093 |
| stats-aggregate | 16 | 0.041 | 0.050 | 0.297 |
| timechart | 8 | 0.038 | 0.042 | 0.338 |
| top-n | 8 | 0.053 | 0.059 | 0.103 |

## Slowest 10 (by p95)

| Query | range | p95_s | verdict | known_slow |
| --- | --- | ---: | --- | --- |
| search_body_like | 1d | 48.881 | SLOW | False |
| rex_body_word_HIGH | 1d | 29.863 | ACCEPTABLE | True |
| rex_http_method | 1d | 27.047 | ACCEPTABLE | False |
| search_body_like | 1h | 8.604 | ACCEPTABLE | False |
| dedup_pod_HIGHCARD | 1h | 7.088 | ACCEPTABLE | True |
| rex_body_word_HIGH | 1h | 6.174 | ACCEPTABLE | True |
| dedup_pod_HIGHCARD | 1d | 6.087 | ACCEPTABLE | True |
| rex_http_method | 1h | 5.150 | ACCEPTABLE | False |
| dedup_pod_HIGHCARD | 5m | 5.067 | ACCEPTABLE | True |
| dedup_pod_HIGHCARD | 15m | 4.793 | FAST | True |

## Cluster metrics (final)

| Metric | Value |
| --- | --- |
| cluster_status | green |
| cpu_max_pct | 5 |
| heap_max_pct | 61 |
| search_queue | 0 |
| active_shards | 121 |
| search_rejected_delta | 0 |
| old_gc_ms_delta | 0 |
