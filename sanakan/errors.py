"""Structured lifecycle errors, so retry policy does not parse error messages."""
class RevalidationRequired(ValueError):
    """The old result is stale; do not retry publishing the same patch."""
