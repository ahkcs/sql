# PPL pushdown matrix — type x operation

| Field | Value |
| --- | --- |
| run_id | pushdown-20260923T163753Z-9e7b |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| tier | tier2 |
| index | mock-mixed-pi |
| points | 107 |
| classifier_version | 2 |

Verdicts: **ok** = the operation's own work is pushed to OpenSearch · **FB** = falls back to coordinator-side but row flow is capped · **FB-UNB** = falls back AND no reduction/limit is pushed, so every matching row crosses the wire (the dangerous shape) · **ERR** = query rejected.

_verdicts recomputed with classifier v2: reads flags from PushDownContext only, requires the op own work to push (time-range FILTER no longer counts), and treats requestedTotalSize=MAX as a risk only when no reduction/limit pushed_

## Matrix

| type (field) | groupby | dc | count_field | min_max | filter_eq | sort | dedup | top | rare | like | isnull | avg_sum | filter_range | bin | span_time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| keyword_lowcard <br>`keyword` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - |
| keyword_highcard <br>`keyword` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - |
| text_bare <br>`text (no subfield)` | **FB-UNB** | **FB-UNB** | **FB-UNB** | ok | ok | **FB-UNB** | **FB-UNB** | **FB-UNB** | **FB-UNB** | ok | ok | - | - | - | - |
| text_multifield <br>`text (+.keyword)` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - |
| text_subfield <br>`keyword (subfield)` | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | - | - | - | - |
| long <br>`long` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - |
| integer <br>`integer` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - |
| byte <br>`byte` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - |
| date <br>`date` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | FB | - | ok | - | ok |
| object <br>`object` | ok | - | - | - | - | - | - | - | - | - | - | - | - | - | - |

Totals: ERROR=11, FALLBACK=1, FALLBACK_UNBOUNDED=7, PUSHED=88

## Not pushed down

| type | op | verdict | coordinator ops | size=MAX | query |
| --- | --- | --- | --- | --- | --- |
| date | isnull | FALLBACK | - | False | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| where isnull(@timestamp) \| head 100` |
| text_bare | count_field | FALLBACK_UNBOUNDED | Aggregate,Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| stats count(body)` |
| text_bare | dc | FALLBACK_UNBOUNDED | Aggregate,Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| stats dc(body)` |
| text_bare | dedup | FALLBACK_UNBOUNDED | Calc,Limit,Window | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| dedup body \| head 100` |
| text_bare | groupby | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| stats count() by body` |
| text_bare | rare | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit,Window | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| rare body` |
| text_bare | sort | FALLBACK_UNBOUNDED | Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| sort body \| head 100` |
| text_bare | top | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit,Window | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| top 10 body` |

## Errors

- **11 points** — `AssertionError: Invalid Query`

Affected: text_subfield

## Untested types (coverage gap)

Not present in the fidelity dataset, so their pushdown behaviour is unverified — needs a mapping change plus reload, or a small side index: `boolean`, `double`, `float`, `scaled_float`, `half_float`, `unsigned_long`, `ip`, `nested`, `flattened`, `wildcard`, `alias`.

