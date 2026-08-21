"""Wide-schema variant for stress benchmarking (~3000 fields), OTel-faithful.

Decision (Kai/Peng, 2026-08-21): the customer's `log.**` explosion is a non-OTel
pipeline artifact (the OTel logs data model has no `log` field — arbitrary
key-value data belongs in Attributes and Resource attributes), and the query
catalogue doesn't use it. So we DON'T reproduce `log.**`; instead we reach the
~3000-field target with SPARSE synthetic columns in `attributes.*` and
`resource.attributes.*` (the real OTel attribute bags), on top of the 75-field
base. Each doc populates only a small random subset (sparse), matching how real
apps emit different attribute keys per record.

Toggle with the generator/loader `--wide` path; the 75-field base is unchanged.
"""
import json
import os

HERE = os.path.dirname(__file__)
BASE_TEMPLATE = os.path.join(HERE, "schemas", "mock-index-template.json")
WIDE_TEMPLATE = os.path.join(HERE, "schemas", "mock-index-template-wide.json")

ATTR_EXTRA = 1460           # extra sparse cols under attributes.*
RES_EXTRA = 1465            # extra sparse cols under resource.attributes.*
SPARSE_PER_DOC = 40         # how many extra cols each doc populates (sparsity)
LONG_EVERY = 7              # every 7th extra is a long, the rest keyword
TOTAL_FIELDS_LIMIT = 3500


def _specs():
    """[(dotted_path, es_type)] for every extra sparse column."""
    specs = []
    for i in range(ATTR_EXTRA):
        specs.append(("attributes.x%04d" % i, "long" if len(specs) % LONG_EVERY == 0 else "keyword"))
    for i in range(RES_EXTRA):
        specs.append(("resource.attributes.x%04d" % i, "long" if len(specs) % LONG_EVERY == 0 else "keyword"))
    return specs


EXTRA_SPECS = _specs()


def _insert(props, path, es_type):
    """Insert {path: {type}} into a mappings `properties` tree, creating parents."""
    node = props
    for part in path.split(".")[:-1]:
        node = node.setdefault(part, {"properties": {}})
        node = node.setdefault("properties", {})
    node[path.split(".")[-1]] = {"type": es_type}


def build():
    """Generate schemas/mock-index-template-wide.json from the base + extras."""
    tpl = json.load(open(BASE_TEMPLATE))
    props = tpl["template"]["mappings"]["properties"]
    for path, t in EXTRA_SPECS:
        _insert(props, path, t)
    tpl["template"]["settings"]["index.mapping.total_fields.limit"] = TOTAL_FIELDS_LIMIT
    tpl.setdefault("_meta", {}).update(
        variant="wide",
        extra_fields=len(EXTRA_SPECS),
        note="~3000-field OTel-faithful stress schema: sparse cols in attributes.* "
             "and resource.attributes.* (NO log.** explosion -- non-OTel + unqueried)")
    with open(WIDE_TEMPLATE, "w") as f:
        json.dump(tpl, f, indent=2)
        f.write("\n")
    return WIDE_TEMPLATE


def draw_extras(rng):
    """Sparse subset of extra columns -> {dotted_path: value}, deterministic in rng."""
    out = {}
    for path, t in rng.sample(EXTRA_SPECS, SPARSE_PER_DOC):
        out[path] = rng.randint(0, 1_000_000) if t == "long" else "v%06x" % rng.getrandbits(24)
    return out


if __name__ == "__main__":
    print("wrote", build(), "| extra fields:", len(EXTRA_SPECS))
