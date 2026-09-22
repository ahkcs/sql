# PPL Perf Report — per-query latency isolation (plan §2.1)

| Field | Value |
| --- | --- |
| run_id | perf-20260921T222749Z-40e4 |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| tier | tier2 |
| git_sha | None |
| reps | 3 |
| warmup | 1 |
| time_ranges | ['5m', '15m', '1h', '1d', '3d', '7d'] |
| loaded_docs | 183000000 |
| templates | 96 | 
| measured points | 576 |

## Latency verdicts

| Verdict | Count |
| --- | ---: |
| FAST | 491 |
| ACCEPTABLE | 23 |
| SLOW | 42 |
| ERROR | 20 |

## (1) Per-query latency curve — p95 seconds per time range

| Query | group | 5m | 15m | 1h | 1d | 3d | 7d |
|  --- | --- | --- | --- | --- | --- | --- | --- |
| cmd_addcoltotals | command | 0.089 | 2.967 | 0.084 | 1.128 | 0.079 | 0.077 |
| cmd_addtotals | command | 1.816 | 1.902 | 1.297 | 0.053 | 2.710 | 1.569 |
| cmd_append | command | 0.048 | 0.048 | 0.046 | 0.046 | 0.046 | 0.048 |
| cmd_appendcol | command | 0.067 | 0.097 | 0.066 | 0.080 | 0.105 | 0.170 |
| cmd_appendpipe | command | 0.062 | 0.062 | 0.059 | 0.060 | 0.059 | 0.059 |
| cmd_bin | command | 0.063 | 0.062 | 0.074 | 0.528 | 1.474 | 3.358 |
| cmd_chart | command | 0.047 | 0.047 | 0.049 | 0.058 | 0.088 | 0.141 |
| cmd_convert | command | 0.265 | 0.263 | 0.261 | 0.301 | 0.266 | 0.257 |
| cmd_dedup | command | 0.201 | 0.283 | 0.246 | 0.317 | 0.360 | 0.534 |
| cmd_eval | command | 0.174 | 0.173 | 0.176 | 0.175 | 0.173 | 0.170 |
| cmd_eventstats | command | 7.868 | 20.542 | 81.871 | 174.629 | 184.323 | 168.214 |
| cmd_expand | command | 0.216 | 0.224 | 0.223 | 0.220 | 0.226 | 0.214 |
| cmd_fieldformat | command | 0.166 | 0.169 | 0.168 | 0.168 | 0.169 | 0.163 |
| cmd_fields | command | 0.163 | 0.123 | 0.076 | 0.074 | 0.076 | 0.061 |
| cmd_fillnull | command | 0.174 | 0.174 | 0.173 | 0.177 | 0.174 | 0.170 |
| cmd_flatten | command | 0.311 | 0.311 | 0.310 | 0.309 | 0.309 | 0.302 |
| cmd_grok | command | 0.185 | 0.178 | 0.178 | 0.176 | 0.181 | 0.174 |
| cmd_head | command | 0.160 | 0.161 | 0.165 | 0.164 | 0.166 | 0.158 |
| cmd_join | command | 0.257 | 0.260 | 0.247 | 0.245 | 0.244 | 0.217 |
| cmd_lookup | command | 0.189 | 0.183 | 0.183 | 0.186 | 0.186 | 0.177 |
| cmd_multisearch | command | 0.178 | 0.077 | 0.129 | 0.132 | 0.123 | 0.066 |
| cmd_mvcombine | command | 0.054 | 0.052 | 0.061 | 0.060 | 0.054 | 0.051 |
| cmd_mvexpand | command | 0.224 | 0.229 | 0.233 | 0.223 | 0.230 | 0.213 |
| cmd_nomv | command | 0.183 | 0.177 | 0.198 | 0.179 | 0.192 | 0.202 |
| cmd_parse | command | 0.175 | 0.174 | 0.173 | 0.174 | 0.174 | 0.170 |
| cmd_patterns | command | 0.176 | 0.175 | 0.177 | 0.175 | 0.177 | 0.173 |
| cmd_rare | command | 0.075 | 2.991 | 0.067 | 1.898 | 1.676 | 0.073 |
| cmd_regex | command | 0.814 | 11.663 | 34.777 | 60.612 | 74.547 | 87.234 |
| cmd_rename | command | 0.190 | 0.177 | 0.175 | 0.172 | 0.169 | 0.163 |
| cmd_replace | command | 0.263 | 0.261 | 0.263 | 0.259 | 0.263 | 0.263 |
| cmd_reverse | command | 0.412 | 0.163 | 0.162 | 0.162 | 0.164 | 0.163 |
| cmd_rex | command | 0.175 | 0.193 | 0.198 | 0.175 | 0.174 | 0.172 |
| cmd_search | command | 0.177 | 0.215 | 0.199 | 0.195 | 0.250 | 0.224 |
| cmd_sort | command | 0.184 | 0.169 | 0.172 | 0.171 | 0.166 | 0.168 |
| cmd_spath | command | 0.230 | 0.184 | 0.182 | 0.187 | 0.241 | 0.183 |
| cmd_stats | command | 0.040 | 0.039 | 0.039 | 0.039 | 0.040 | 0.044 |
| cmd_streamstats | command | 7.206 | 22.688 | 80.730 | 179.944 | 158.932 | 3.437 |
| cmd_subquery | command | 0.221 | 0.227 | 0.249 | 0.233 | 0.230 | 0.224 |
| cmd_table | command | 0.058 | 0.060 | 0.057 | 0.056 | 0.060 | 0.053 |
| cmd_timechart | command | 0.049 | 0.051 | 0.044 | 0.064 | 0.086 | 0.157 |
| cmd_top | command | 0.400 | 1.828 | 2.933 | 0.094 | 1.602 | 2.832 |
| cmd_transpose | command | 0.154 | 0.149 | 0.129 | 0.133 | 0.143 | 0.191 |
| cmd_trendline | command | 0.066 | 0.061 | 0.059 | 0.061 | 0.061 | 0.063 |
| cmd_union | command | 0.075 | 0.072 | 0.101 | 0.079 | 0.132 | 0.091 |
| cmd_where | command | 0.177 | 0.171 | 0.178 | 0.198 | 0.175 | 0.165 |
| fmt_pod_mock-json-dd | format | 0.908 | 0.210 | 0.193 | 0.309 | 0.351 | 0.399 |
| fmt_pod_mock-json-ecs | format | 1.036 | 0.248 | 0.183 | 0.296 | 0.303 | 0.664 |
| fmt_pod_mock-json-fid | format | 0.387 | 0.191 | 0.228 | 0.285 | 0.194 | 0.656 |
| fmt_pod_mock-json-http | format | 0.589 | 0.177 | 0.187 | 0.284 | 0.258 | 0.174 |
| fmt_pod_mock-json-spring | format | 0.484 | 0.181 | 0.181 | 0.284 | 0.323 | 0.615 |
| fmt_pod_mock-kv-pi | format | 0.158 | 0.169 | 0.177 | 0.267 | 0.157 | 0.361 |
| fmt_pod_mock-kv-quoted-wi | format | 0.531 | 0.205 | 0.192 | 0.296 | 0.340 | 0.564 |
| fmt_pod_mock-mixed-pi | format | 0.500 | 0.177 | 0.190 | 0.300 | 0.344 | 0.165 |
| fmt_pod_mock-multi-format | format | 0.553 | 0.174 | 0.188 | 0.267 | 0.166 | 0.375 |
| fmt_pod_mock-nested-cape | format | 0.917 | 0.180 | 0.183 | 0.293 | 0.330 | 0.500 |
| fmt_rex_mock-json-dd | format | 3.526 | 6.617 | 43.194 | 54.408 | 85.510 | 136.956 |
| fmt_rex_mock-json-ecs | format | 3.321 | 8.097 | 21.585 | 53.799 | 76.465 | 131.970 |
| fmt_rex_mock-json-fid | format | 3.161 | 6.023 | 21.721 | 34.102 | 88.097 | 131.622 |
| fmt_rex_mock-json-http | format | 3.201 | 5.904 | 26.445 | 56.046 | 88.707 | 76.824 |
| fmt_rex_mock-json-spring | format | 3.215 | 6.414 | 22.097 | 61.399 | 73.002 | 99.801 |
| fmt_rex_mock-kv-pi | format | 2.121 | 4.700 | 14.043 | 51.372 | 77.741 | 138.187 |
| fmt_rex_mock-kv-quoted-wi | format | 3.204 | 6.092 | 21.337 | 35.068 | 80.842 | 148.285 |
| fmt_rex_mock-mixed-pi | format | 3.220 | 6.923 | 21.148 | 63.422 | 90.955 | 123.342 |
| fmt_rex_mock-multi-format | format | 3.240 | 8.365 | 24.808 | 65.225 | 82.323 | 100.177 |
| fmt_rex_mock-nested-cape | format | 3.312 | 8.562 | 38.869 | 52.765 | 83.053 | 137.336 |
| fmt_scan_mock-json-dd | format | 0.560 | 0.190 | 0.251 | 0.205 | 0.219 | 0.176 |
| fmt_scan_mock-json-ecs | format | 0.484 | 0.224 | 0.178 | 0.197 | 0.242 | 0.171 |
| fmt_scan_mock-json-fid | format | 0.590 | 0.265 | 0.187 | 0.196 | 0.229 | 0.181 |
| fmt_scan_mock-json-http | format | 0.599 | 0.180 | 0.184 | 0.201 | 0.226 | 0.172 |
| fmt_scan_mock-json-spring | format | 0.352 | 0.185 | 0.194 | 0.212 | 0.221 | 0.187 |
| fmt_scan_mock-kv-pi | format | 0.617 | 0.197 | 0.198 | 0.208 | 0.231 | 0.178 |
| fmt_scan_mock-kv-quoted-wi | format | 0.313 | 0.181 | 0.179 | 0.264 | 0.218 | 0.172 |
| fmt_scan_mock-mixed-pi | format | 0.571 | 0.227 | 0.213 | 0.205 | 0.236 | 0.192 |
| fmt_scan_mock-multi-format | format | 0.351 | 0.300 | 0.192 | 0.208 | 0.222 | 0.171 |
| fmt_scan_mock-nested-cape | format | 0.463 | 0.340 | 0.196 | 0.194 | 0.254 | 0.178 |
| fmt_sev_mock-json-dd | format | 0.108 | 0.091 | 0.059 | 0.086 | 0.158 | 0.146 |
| fmt_sev_mock-json-ecs | format | 0.106 | 0.053 | 0.050 | 0.076 | 0.118 | 0.149 |
| fmt_sev_mock-json-fid | format | 0.133 | 0.056 | 0.056 | 0.077 | 0.129 | 0.144 |
| fmt_sev_mock-json-http | format | 0.138 | 0.050 | 0.060 | 0.058 | 0.127 | 0.152 |
| fmt_sev_mock-json-spring | format | 0.116 | 0.052 | 0.083 | 0.080 | 0.116 | 0.147 |
| fmt_sev_mock-kv-pi | format | 0.104 | 0.041 | 0.039 | 0.051 | 0.067 | 0.044 |
| fmt_sev_mock-kv-quoted-wi | format | 0.117 | 0.055 | 0.057 | 0.091 | 0.128 | 0.150 |
| fmt_sev_mock-mixed-pi | format | 0.108 | 0.048 | 0.050 | 0.072 | 0.118 | 0.148 |
| fmt_sev_mock-multi-format | format | 0.113 | 0.053 | 0.048 | 0.082 | 0.119 | 0.143 |
| fmt_sev_mock-nested-cape | format | 0.114 | 0.047 | 0.055 | 0.077 | 0.117 | 0.154 |
| scn_big_sort_head | scenario | 0.410 | 0.389 | 0.384 | 0.428 | 0.393 | 0.404 |
| scn_body_like_LEADWILD | scenario | 6.443 | 12.351 | 40.891 | 64.180 | 75.326 | 86.585 |
| scn_cross_index_pod | scenario | 0.911 | 1.004 | 0.689 | 0.819 | 0.886 | 1.003 |
| scn_eval_then_stats | scenario | 0.056 | 0.052 | 0.064 | 0.236 | 0.582 | 1.357 |
| scn_stacked_sev_region | scenario | 0.085 | 0.057 | 0.054 | 0.080 | 0.125 | 0.204 |
| agg_dc_HIGHCARD | agg-func | 0.491 | 0.075 | 0.074 | 0.129 | 0.184 | 0.267 |
| agg_dc_service | agg-func | 0.080 | 0.067 | 0.044 | 0.052 | 0.075 | 0.092 |
| agg_numeric_longfield | agg-func | 0.106 | 0.090 | 0.056 | 0.100 | 0.170 | 0.279 |
| agg_percentile | agg-func | 0.080 | 0.062 | 0.052 | 0.089 | 0.187 | 0.377 |
| agg_stddev | agg-func | 0.052 | 0.045 | 0.051 | 0.069 | 0.093 | 0.167 |
| agg_var | agg-func | 0.067 | 0.048 | 0.058 | 0.058 | 0.085 | 0.131 |

## (2) Per-format aggregate — mean p95 (s) by body format

| Format | pod | rex | scan | sev | overall |
| --- | ---: | ---: | ---: | ---: | ---: |
| json-dd | 0.395 | 55.035 | 0.267 | 0.108 | 13.951 |
| json-ecs | 0.455 | 49.206 | 0.249 | 0.092 | 12.501 |
| json-fid | 0.324 | 47.454 | 0.275 | 0.099 | 12.038 |
| json-http | 0.278 | 42.855 | 0.260 | 0.098 | 10.873 |
| json-spring | 0.345 | 44.321 | 0.225 | 0.099 | 11.248 |
| kv-pi | 0.215 | 48.027 | 0.272 | 0.058 | 12.143 |
| kv-quoted-wi | 0.355 | 49.138 | 0.221 | 0.100 | 12.453 |
| mixed-pi | 0.279 | 51.502 | 0.274 | 0.091 | 13.036 |
| multi-format | 0.287 | 47.356 | 0.241 | 0.093 | 11.994 |
| nested-cape | 0.401 | 53.983 | 0.271 | 0.094 | 13.687 |

_Probes: sev=count-by-severity, pod=count-by-pod (high-card), rex=rex-on-body, scan=filtered scan. Mean over all ranges._

## Per-command p95 (s) — command axis

| Command | 5m | 15m | 1h | 1d | 3d | 7d | known_slow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| addcoltotals | 0.089 | 2.967 | 0.084 | 1.128 | 0.079 | 0.077 | False |
| addtotals | 1.816 | 1.902 | 1.297 | 0.053 | 2.710 | 1.569 | False |
| append | 0.048 | 0.048 | 0.046 | 0.046 | 0.046 | 0.048 | False |
| appendcol | 0.067 | 0.097 | 0.066 | 0.080 | 0.105 | 0.170 | False |
| appendpipe | 0.062 | 0.062 | 0.059 | 0.060 | 0.059 | 0.059 | False |
| bin | 0.063 | 0.062 | 0.074 | 0.528 | 1.474 | 3.358 | False |
| chart | 0.047 | 0.047 | 0.049 | 0.058 | 0.088 | 0.141 | False |
| convert | 0.265 | 0.263 | 0.261 | 0.301 | 0.266 | 0.257 | False |
| dedup | 0.201 | 0.283 | 0.246 | 0.317 | 0.360 | 0.534 | False |
| eval | 0.174 | 0.173 | 0.176 | 0.175 | 0.173 | 0.170 | False |
| eventstats | 7.868 | 20.542 | 81.871 | 174.629 | 184.323 | 168.214 | True |
| expand | 0.216 | 0.224 | 0.223 | 0.220 | 0.226 | 0.214 | False |
| fieldformat | 0.166 | 0.169 | 0.168 | 0.168 | 0.169 | 0.163 | False |
| fields | 0.163 | 0.123 | 0.076 | 0.074 | 0.076 | 0.061 | False |
| fillnull | 0.174 | 0.174 | 0.173 | 0.177 | 0.174 | 0.170 | False |
| flatten | 0.311 | 0.311 | 0.310 | 0.309 | 0.309 | 0.302 | False |
| grok | 0.185 | 0.178 | 0.178 | 0.176 | 0.181 | 0.174 | False |
| head | 0.160 | 0.161 | 0.165 | 0.164 | 0.166 | 0.158 | False |
| join | 0.257 | 0.260 | 0.247 | 0.245 | 0.244 | 0.217 | True |
| lookup | 0.189 | 0.183 | 0.183 | 0.186 | 0.186 | 0.177 | False |
| multisearch | 0.178 | 0.077 | 0.129 | 0.132 | 0.123 | 0.066 | False |
| mvcombine | 0.054 | 0.052 | 0.061 | 0.060 | 0.054 | 0.051 | False |
| mvexpand | 0.224 | 0.229 | 0.233 | 0.223 | 0.230 | 0.213 | False |
| nomv | 0.183 | 0.177 | 0.198 | 0.179 | 0.192 | 0.202 | False |
| parse | 0.175 | 0.174 | 0.173 | 0.174 | 0.174 | 0.170 | False |
| patterns | 0.176 | 0.175 | 0.177 | 0.175 | 0.177 | 0.173 | True |
| rare | 0.075 | 2.991 | 0.067 | 1.898 | 1.676 | 0.073 | False |
| regex | 0.814 | 11.663 | 34.777 | 60.612 | 74.547 | 87.234 | True |
| rename | 0.190 | 0.177 | 0.175 | 0.172 | 0.169 | 0.163 | False |
| replace | 0.263 | 0.261 | 0.263 | 0.259 | 0.263 | 0.263 | False |
| reverse | 0.412 | 0.163 | 0.162 | 0.162 | 0.164 | 0.163 | False |
| rex | 0.175 | 0.193 | 0.198 | 0.175 | 0.174 | 0.172 | False |
| search | 0.177 | 0.215 | 0.199 | 0.195 | 0.250 | 0.224 | False |
| sort | 0.184 | 0.169 | 0.172 | 0.171 | 0.166 | 0.168 | False |
| spath | 0.230 | 0.184 | 0.182 | 0.187 | 0.241 | 0.183 | False |
| stats | 0.040 | 0.039 | 0.039 | 0.039 | 0.040 | 0.044 | False |
| streamstats | 7.206 | 22.688 | 80.730 | 179.944 | 158.932 | 3.437 | True |
| subquery | 0.221 | 0.227 | 0.249 | 0.233 | 0.230 | 0.224 | False |
| table | 0.058 | 0.060 | 0.057 | 0.056 | 0.060 | 0.053 | False |
| timechart | 0.049 | 0.051 | 0.044 | 0.064 | 0.086 | 0.157 | False |
| top | 0.400 | 1.828 | 2.933 | 0.094 | 1.602 | 2.832 | False |
| transpose | 0.154 | 0.149 | 0.129 | 0.133 | 0.143 | 0.191 | False |
| trendline | 0.066 | 0.061 | 0.059 | 0.061 | 0.061 | 0.063 | False |
| union | 0.075 | 0.072 | 0.101 | 0.079 | 0.132 | 0.091 | False |
| where | 0.177 | 0.171 | 0.178 | 0.198 | 0.175 | 0.165 | False |

## (3) Known-slow sheet — p95 seconds

| Query | range | p95 | max | verdict |
| --- | --- | ---: | ---: | --- |
| cmd_eventstats | 3d | 184.323 | 193.864 | ERROR |
| cmd_streamstats | 1d | 179.944 | 180.108 | ERROR |
| cmd_eventstats | 1d | 174.629 | 183.691 | ERROR |
| cmd_eventstats | 7d | 168.214 | 176.953 | ERROR |
| cmd_streamstats | 3d | 158.932 | 167.119 | ERROR |
| fmt_rex_mock-kv-quoted-wi | 7d | 148.285 | 148.773 | SLOW |
| fmt_rex_mock-kv-pi | 7d | 138.187 | 141.056 | SLOW |
| fmt_rex_mock-nested-cape | 7d | 137.336 | 137.725 | SLOW |
| fmt_rex_mock-json-dd | 7d | 136.956 | 137.035 | SLOW |
| fmt_rex_mock-json-ecs | 7d | 131.970 | 134.791 | SLOW |
| fmt_rex_mock-json-fid | 7d | 131.622 | 134.815 | SLOW |
| fmt_rex_mock-mixed-pi | 7d | 123.342 | 124.518 | SLOW |
| fmt_rex_mock-multi-format | 7d | 100.177 | 100.229 | SLOW |
| fmt_rex_mock-json-spring | 7d | 99.801 | 100.021 | SLOW |
| fmt_rex_mock-mixed-pi | 3d | 90.955 | 91.104 | SLOW |
| fmt_rex_mock-json-http | 3d | 88.707 | 88.766 | SLOW |
| fmt_rex_mock-json-fid | 3d | 88.097 | 88.300 | SLOW |
| cmd_regex | 7d | 87.234 | 87.459 | SLOW |
| scn_body_like_LEADWILD | 7d | 86.585 | 86.605 | SLOW |
| fmt_rex_mock-json-dd | 3d | 85.510 | 85.545 | SLOW |
| fmt_rex_mock-nested-cape | 3d | 83.053 | 84.880 | SLOW |
| fmt_rex_mock-multi-format | 3d | 82.323 | 82.575 | SLOW |
| cmd_eventstats | 1h | 81.871 | 81.883 | SLOW |
| fmt_rex_mock-kv-quoted-wi | 3d | 80.842 | 82.584 | SLOW |
| cmd_streamstats | 1h | 80.730 | 80.975 | SLOW |
| fmt_rex_mock-kv-pi | 3d | 77.741 | 81.086 | SLOW |
| fmt_rex_mock-json-http | 7d | 76.824 | 76.968 | SLOW |
| fmt_rex_mock-json-ecs | 3d | 76.465 | 79.701 | SLOW |
| scn_body_like_LEADWILD | 3d | 75.326 | 75.327 | SLOW |
| cmd_regex | 3d | 74.547 | 74.687 | SLOW |
| fmt_rex_mock-json-spring | 3d | 73.002 | 73.148 | SLOW |
| fmt_rex_mock-multi-format | 1d | 65.225 | 66.345 | SLOW |
| scn_body_like_LEADWILD | 1d | 64.180 | 64.259 | SLOW |
| fmt_rex_mock-mixed-pi | 1d | 63.422 | 65.223 | SLOW |
| fmt_rex_mock-json-spring | 1d | 61.399 | 62.273 | SLOW |
| cmd_regex | 1d | 60.612 | 60.627 | SLOW |
| fmt_rex_mock-json-http | 1d | 56.046 | 56.072 | SLOW |
| fmt_rex_mock-json-dd | 1d | 54.408 | 54.528 | SLOW |
| fmt_rex_mock-json-ecs | 1d | 53.799 | 56.087 | SLOW |
| fmt_rex_mock-nested-cape | 1d | 52.765 | 52.822 | SLOW |

## (4) Wide-range movers — p95 growth 1d -> 7d

| Query | 1d | 3d | 7d | 7d/1d |
| --- | ---: | ---: | ---: | ---: |
| cmd_top | 0.094 | 1.602 | 2.832 | 30.1x |
| cmd_addtotals | 0.053 | 2.710 | 1.569 | 29.6x |
| cmd_bin | 0.528 | 1.474 | 3.358 | 6.4x |
| scn_eval_then_stats | 0.236 | 0.582 | 1.357 | 5.8x |
| agg_percentile | 0.089 | 0.187 | 0.377 | 4.2x |
| fmt_rex_mock-kv-quoted-wi | 35.068 | 80.842 | 148.285 | 4.2x |
| fmt_rex_mock-json-fid | 34.102 | 88.097 | 131.622 | 3.9x |
| agg_numeric_longfield | 0.100 | 0.170 | 0.279 | 2.8x |
| fmt_rex_mock-kv-pi | 51.372 | 77.741 | 138.187 | 2.7x |
| fmt_sev_mock-json-http | 0.058 | 0.127 | 0.152 | 2.6x |
| fmt_rex_mock-nested-cape | 52.765 | 83.053 | 137.336 | 2.6x |
| scn_stacked_sev_region | 0.080 | 0.125 | 0.204 | 2.5x |
| fmt_rex_mock-json-dd | 54.408 | 85.510 | 136.956 | 2.5x |
| cmd_timechart | 0.064 | 0.086 | 0.157 | 2.5x |
| fmt_rex_mock-json-ecs | 53.799 | 76.465 | 131.970 | 2.5x |

## Errors (verdict=ERROR)

| Query | range | err_types |
| --- | --- | --- |
| cmd_addcoltotals | 15m | RuntimeException |
| cmd_addtotals | 5m | RuntimeException |
| cmd_addtotals | 15m | RuntimeException |
| cmd_addtotals | 1h | RuntimeException |
| cmd_addtotals | 3d | RuntimeException |
| cmd_addtotals | 7d | RuntimeException |
| cmd_eventstats | 1d | RuntimeException |
| cmd_eventstats | 3d | RuntimeException |
| cmd_eventstats | 7d | RuntimeException |
| cmd_rare | 15m | RuntimeException |
| cmd_rare | 1d | RuntimeException |
| cmd_rare | 3d | RuntimeException |
| cmd_streamstats | 15m | RuntimeException |
| cmd_streamstats | 1d | RuntimeException |
| cmd_streamstats | 3d | RuntimeException |
| cmd_streamstats | 7d | RuntimeException |
| cmd_top | 15m | RuntimeException |
| cmd_top | 1h | RuntimeException |
| cmd_top | 3d | RuntimeException |
| cmd_top | 7d | RuntimeException |

_Commands documented but rejected by this build's grammar (excluded from the run): xyseries, timewrap, foreach._

## (5) Cluster metrics — baseline / mid-run / final

| Phase | cluster_status | cpu_max_pct | heap_max_pct | search_active | search_queue | search_rejected | old_gc_ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | green | 4 | 70 | 0 | 0 | 0 | 0 |
| mid-0 | green | 3 | 55 | 0 | 0 | 0 | 0 |
| mid-1 | green | 4 | 59 | 0 | 0 | 0 | 0 |
| mid-2 | green | 33 | 78 | 0 | 0 | 0 | 0 |
| mid-3 | green | 7 | 75 | 0 | 0 | 0 | 0 |
| mid-4 | green | 29 | 52 | 0 | 0 | 0 | 0 |
| mid-5 | green | 13 | 76 | 0 | 0 | 0 | 0 |
| mid-6 | green | 80 | 79 | 27 | 0 | 0 | 0 |
| mid-7 | green | 4 | 77 | 0 | 0 | 0 | 0 |
| mid-8 | green | 14 | 69 | 0 | 0 | 0 | 0 |
| mid-9 | green | 43 | 76 | 30 | 0 | 0 | 0 |
| mid-10 | green | 27 | 77 | 0 | 0 | 0 | 0 |
| final | green | 7 | 78 | 0 | 0 | 0 | 0 |

Deltas (post-pre): search_rejected_delta=0, old_gc_ms_delta=0
