"""Run header carried by every results.json (plan §3.4).

The observability sink keys everything off `run_id`, and release evidence needs
to say which code produced a number — so the header travels with the results
rather than being reconstructed at ship time.
"""
import datetime
import os
import subprocess
import uuid

from mock_data import distributions

# Bump when suite/wlm.py GROUPS/PROFILES change (plan §3.3).
WLM_POLICY_VERSION = "1.0"

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=_ROOT,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return None


def tier_for(host):
    return "tier2" if ".es.amazonaws.com" in (host or "") else "tier1"


def header(pillar, host, tier=None, **extra):
    now = datetime.datetime.now(datetime.timezone.utc)
    hdr = {"run_id": "%s-%s-%s" % (pillar, now.strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:4]),
           "pillar": pillar,
           "timestamp": now.isoformat(timespec="seconds"),
           "host": host,
           "tier": tier or tier_for(host),
           "git_sha": git_sha(),
           "schema_version": distributions.SCHEMA_VERSION,
           "wlm_policy_version": WLM_POLICY_VERSION}
    hdr.update(extra)
    return hdr
