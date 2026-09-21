#!/usr/bin/env bash
set -euo pipefail
# Deliberate fail-closed stub. Never inject a write token into this checkout.
echo "Publishing is not implemented in this reference package." >&2
echo "Use a separately protected publisher after human approval and immutable artifact verification." >&2
exit 2
