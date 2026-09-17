"""Named OpenSearch identities for WLM-classified runs (plan §3.3).

WLM classification is user-based, so any scenario that needs a specific workload
group must authenticate as that group's user. Credentials come from the
environment — one pair per configured user — so nothing lands in results.json or
in the repo:

    export PPL_ADMIN_AUTH=admin:...        # provisioning + metrics
    export PPL_DASH_AUTH=dash_user:...     # -> dashboards workload group
    export PPL_ADHOC_AUTH=adhoc_user:...   # -> adhoc workload group

`--as-user dash_user` on the runners resolves through here. A literal
`user:pass` is passed through unchanged, which keeps the old `--auth` behaviour.
"""
import os

ENV_BY_NAME = {
    "admin": "PPL_ADMIN_AUTH",
    "dash_user": "PPL_DASH_AUTH",
    "adhoc_user": "PPL_ADHOC_AUTH",
}


def auth_for(name, default=None):
    """Resolve an identity name (or a literal user:pass) to a user:pass string."""
    if not name:
        return default
    if ":" in name:
        return name
    env = ENV_BY_NAME.get(name)
    if env is None:
        raise SystemExit("unknown identity %r (known: %s)"
                         % (name, ", ".join(sorted(ENV_BY_NAME))))
    val = os.environ.get(env)
    if not val:
        raise SystemExit("identity %r requires %s=user:pass in the environment" % (name, env))
    return val


def configured():
    """Identity names that actually have credentials in the environment."""
    return [n for n, e in ENV_BY_NAME.items() if os.environ.get(e)]


def split(auth):
    """user:pass -> (user, pass); None -> (None, None)."""
    if not auth or ":" not in auth:
        return None, None
    user, _, pw = auth.partition(":")
    return user, pw
