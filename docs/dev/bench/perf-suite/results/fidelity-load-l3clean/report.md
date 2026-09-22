# PPL Load Report — steady-state under concurrency (plan §2.2)

| Field | Value |
| --- | --- |
| run_id | load-20260922T212656Z-0fc7 |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| tier | tier2 |
| time_range | 1h |
| work_size | 96 |
| ramp_work | full |
| ramp_work_size | 96 |
| ramp_max | 50 |
| ramp_step | 5 |
| levels | 5,10,20 |
| seed | 1337 |

## (4) Sustained load — per-minute trend (N=10, 1800s)

- pass 96% · latency drift 15.600% · heap growth -1% · 1108 requests

| minute | reqs | p50 s | p95 s | heap % | CPU % |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 65 | 0.181 | 1.343 | 79 | 63 |
| 1 | 48 | 0.150 | 82.013 | 79 | 46 |
| 2 | 40 | 0.258 | 81.864 | 79 | 52 |
| 3 | 8 | 44.701 | 120.111 | 79 | 65 |
| 4 | 19 | 2.847 | 120.111 | 79 | 55 |
| 5 | 57 | 0.913 | 79.998 | 79 | 73 |
| 6 | 38 | 0.215 | 76.887 | 79 | 56 |
| 7 | 31 | 0.201 | 120.040 | 79 | 49 |
| 8 | 29 | 2.539 | 93.473 | 79 | 100 |
| 9 | 11 | 31.314 | 120.112 | 79 | 65 |
| 10 | 59 | 0.612 | 88.552 | 79 | 47 |
| 11 | 11 | 0.565 | 106.494 | 79 | 49 |
| 12 | 27 | 1.560 | 120.101 | 79 | 38 |
| 13 | 39 | 0.172 | 90.752 | 79 | 74 |
| 14 | 21 | 0.793 | 120.111 | 79 | 73 |
| 15 | 34 | 0.277 | 102.237 | 79 | 41 |
| 16 | 36 | 2.200 | 92.027 | 79 | 40 |
| 17 | 28 | 3.393 | 90.256 | 79 | 50 |
| 18 | 88 | 0.290 | 83.885 | 79 | 66 |
| 19 | 45 | 0.646 | 87.867 | 79 | 43 |
| 20 | 70 | 0.164 | 83.806 | 79 | 37 |
| 21 | 32 | 0.178 | 120.035 | 79 | 55 |
| 22 | 41 | 0.263 | 86.219 | 79 | 47 |
| 23 | 12 | 5.025 | 120.111 | 79 | 79 |
| 24 | 38 | 0.741 | 106.633 | 79 | 33 |
| 25 | 36 | 0.318 | 101.225 | 79 | 52 |
| 26 | 18 | 4.278 | 120.111 | 79 | 38 |
| 27 | 83 | 0.367 | 92.665 | 79 | 59 |
| 28 | 13 | 2.725 | 104.072 | 79 | 63 |
| 29 | 21 | 0.502 | 120.111 | 79 | 51 |
| 30 | 8 | 83.035 | 120.111 | 79 | 43 |
| 31 | 2 | 102.741 | 118.376 | 76 | 62 |

## (5) Cluster-metrics time series

Full timestamped series attached to results.json: baseline + final snapshots, per-phase pre/post, and 618 sampler samples across all phases. Peak CPU/heap/queue and Δ rejections in the tables above are computed from this series (§4.3 exit criteria).
