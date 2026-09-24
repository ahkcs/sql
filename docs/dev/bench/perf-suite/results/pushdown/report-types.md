# PPL pushdown matrix — type x operation

| Field | Value |
| --- | --- |
| run_id | pushdown-20260924T185629Z-8d0f |
| host | https://search-ppl-perf-tier2-hfmrk3ra3wgzmo7vnp7juptyny.us-east-1.es.amazonaws.com |
| tier | tier2 |
| suites | ['fidelity', 'types'] |
| indices | ['mock-mixed-pi', 'mock-types'] |
| points | 254 |
| classifier_version | 4 |

Verdicts: **ok** = the operation's own work is pushed to OpenSearch · **FB** = falls back to coordinator-side but row flow is capped · **FB-UNB** = falls back AND no reduction/limit is pushed, so every matching row crosses the wire (the dangerous shape) · **ERR** = query rejected.

_classifier v4: a predicate counts as pushed when its literal appears in FILTER->, when it pushes as a bare field reference (booleans render as $n, possibly inside an AND), or via SCRIPT->. SCRIPT-> is reported as PUSHED_SCRIPT because it evaluates per document. A plan folded to EnumerableValues(tuples=[[]]) is EMPTY_CONSTANT_FOLDED -- the optimizer proved the predicate unsatisfiable, which is optimal rather than a fallback._

## Matrix

**suite `fidelity`** — `mock-mixed-pi`

| type (field) | groupby | dc | count_field | min_max | filter_eq | sort | dedup | top | rare | like | isnull | avg_sum | filter_range | bin | span_time | cidr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| keyword_lowcard <br>`keyword` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - | - |
| keyword_highcard <br>`keyword` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - | - |
| text_bare <br>`text (no subfield)` | **FB-UNB** | **FB-UNB** | **FB-UNB** | ok | - | **FB-UNB** | **FB-UNB** | **FB-UNB** | **FB-UNB** | - | ok | - | - | - | - | - |
| text_multifield <br>`text (+.keyword)` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - | - |
| text_subfield <br>`keyword (subfield)` | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | - | - | - | - | - |
| long <br>`long` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - | - |
| integer <br>`integer` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - | - |
| byte <br>`byte` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - | - |
| date <br>`date` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | ok | - | ok | - |
| object <br>`object` | ok | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |

**suite `types`** — `mock-types`

| type (field) | groupby | dc | count_field | min_max | filter_eq | sort | dedup | top | rare | like | isnull | avg_sum | filter_range | bin | span_time | cidr |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| env_text_bare <br>`text (no subfield)` | **FB-UNB** | **FB-UNB** | **FB-UNB** | ok | - | **FB-UNB** | **FB-UNB** | **FB-UNB** | **FB-UNB** | - | ok | - | - | - | - | - |
| env_keyword <br>`keyword` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - | - |
| env_multifield <br>`text (+.keyword)` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - | - |
| env_alias <br>`alias -> keyword` | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | - | - | - | - |
| boolean <br>`boolean` | ok | ok | ok | - | ok | ok | ok | ok | ok | - | ok | - | - | - | - | - |
| double <br>`double` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - | - |
| float <br>`float` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - | - |
| half_float <br>`half_float` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - | - |
| scaled_float <br>`scaled_float` | ok | ok | ok | ok | ok | ok | ok | ok | ok | - | ok | ok | ok | ok | - | - |
| unsigned_long <br>`unsigned_long` | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | ERR | - | ERR | ERR | ERR | ERR | - | - |
| ip <br>`ip` | ok | ok | ok | ok | - | ok | ok | ok | ok | - | ok | - | - | - | - | - |
| wildcard <br>`wildcard` | ERR | ERR | ERR | - | ERR | ERR | - | ERR | ERR | ERR | ERR | - | - | - | - | - |
| flat_object_leaf <br>`flat_object (leaf)` | ERR | ERR | ERR | - | ERR | ERR | - | ERR | ERR | - | ERR | - | - | - | - | - |
| nested_leaf <br>`nested (leaf)` | ok | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - |

Totals: EMPTY_CONSTANT_FOLDED=1, ERROR=41, FALLBACK_UNBOUNDED=14, PUSHED=192, PUSHED_SCRIPT=6

## Not pushed down

| type | op | verdict | coordinator ops | size=MAX | query |
| --- | --- | --- | --- | --- | --- |
| types/env_text_bare | count_field | FALLBACK_UNBOUNDED | Aggregate,Limit | True | `source=mock-types \| where @timestamp >= '2026-04-10 23:00:00' \| stats count(env_text)` |
| types/env_text_bare | dc | FALLBACK_UNBOUNDED | Aggregate,Limit | True | `source=mock-types \| where @timestamp >= '2026-04-10 23:00:00' \| stats dc(env_text)` |
| types/env_text_bare | dedup | FALLBACK_UNBOUNDED | Calc,Limit,Window | True | `source=mock-types \| where @timestamp >= '2026-04-10 23:00:00' \| dedup env_text \| head 100` |
| types/env_text_bare | groupby | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit | True | `source=mock-types \| where @timestamp >= '2026-04-10 23:00:00' \| stats count() by env_text` |
| types/env_text_bare | rare | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit,Window | True | `source=mock-types \| where @timestamp >= '2026-04-10 23:00:00' \| rare env_text` |
| types/env_text_bare | sort | FALLBACK_UNBOUNDED | Calc,Limit | True | `source=mock-types \| where @timestamp >= '2026-04-10 23:00:00' \| sort env_text \| head 100` |
| types/env_text_bare | top | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit,Window | True | `source=mock-types \| where @timestamp >= '2026-04-10 23:00:00' \| top 10 env_text` |
| fidelity/text_bare | count_field | FALLBACK_UNBOUNDED | Aggregate,Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| stats count(body)` |
| fidelity/text_bare | dc | FALLBACK_UNBOUNDED | Aggregate,Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| stats dc(body)` |
| fidelity/text_bare | dedup | FALLBACK_UNBOUNDED | Calc,Limit,Window | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| dedup body \| head 100` |
| fidelity/text_bare | groupby | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| stats count() by body` |
| fidelity/text_bare | rare | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit,Window | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| rare body` |
| fidelity/text_bare | sort | FALLBACK_UNBOUNDED | Limit | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| sort body \| head 100` |
| fidelity/text_bare | top | FALLBACK_UNBOUNDED | Aggregate,Calc,Limit,Window | True | `source=mock-mixed-pi \| where @timestamp >= '2026-04-10 23:00:00' \| top 10 body` |

## Errors

- **13 points** — `IllegalArgumentException: Field [val_ulong] not found.`
- **11 points** — `AssertionError: Invalid Query`
- **9 points** — `IllegalArgumentException: Field [path_wildcard] not found.`
- **8 points** — `IllegalArgumentException: Field [payload_flat.region] not found.`

Affected: flat_object_leaf, text_subfield, unsigned_long, wildcard

