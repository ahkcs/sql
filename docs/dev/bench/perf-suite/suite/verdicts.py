"""Latency verdicts and failure classification (plan §2.5, §4.6)."""

# Baseline verdicts (perf + load pillars), by elapsed seconds.
FAST, ACCEPTABLE, SLOW, TIMEOUT, ERROR = "FAST", "ACCEPTABLE", "SLOW", "TIMEOUT", "ERROR"
TIMEOUT_S = 300


def latency_verdict(elapsed_s, ok):
    if not ok:
        return ERROR
    if elapsed_s < 5:
        return FAST
    if elapsed_s < 30:
        return ACCEPTABLE
    if elapsed_s < TIMEOUT_S:
        return SLOW
    return TIMEOUT


# User-facing verdicts (use-case pillar), by dashboard/step seconds.
GOOD, UC_ACCEPTABLE, POOR = "GOOD", "ACCEPTABLE", "POOR"


def usecase_verdict(elapsed_s):
    if elapsed_s < 5:
        return GOOD
    if elapsed_s < 10:
        return UC_ACCEPTABLE
    return POOR


# Failure classes (§4.6)
BLOCKER, REGRESSION, KNOWN_SLOW, NEW_SLOW, NOISE = (
    "BLOCKER", "REGRESSION", "KNOWN-SLOW", "NEW-SLOW", "NOISE")
