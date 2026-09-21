#!/usr/bin/env bash
set -euo pipefail

# Install as scripts/verify.sh. Supply a profile; never silently skip checks.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
PROFILE="${1:-}"
BACKEND_DIR="${2:-.}"
FRONTEND_DIR="${3:-.}"
case "$PROFILE" in
  backend|frontend|combined) ;;
  *) echo "Usage: bash scripts/verify.sh backend|frontend|combined [backend-dir] [frontend-dir]" >&2; exit 2 ;;
esac

git rev-parse --is-inside-work-tree >/dev/null
git diff --check
git diff --cached --check

verify_backend() (
  cd "$BACKEND_DIR"
  if [[ -f ./gradlew ]]; then
    bash ./gradlew test build
  elif [[ -f ./mvnw ]]; then
    bash ./mvnw verify
  else
    echo "Required backend wrapper missing: gradlew or mvnw" >&2
    exit 2
  fi
)

verify_frontend() (
  cd "$FRONTEND_DIR"
  test -f package.json || { echo "Required package.json missing" >&2; exit 2; }
  test -f package-lock.json || { echo "Required npm lockfile missing" >&2; exit 2; }
  # Required scripts must terminate in CI. Define test:ci (e.g. vitest run).
  node -e 'const p=require("./package.json"); for(const k of ["lint","typecheck","test:ci","build"]) if(typeof p.scripts?.[k]!=="string" || !p.scripts[k].trim()) throw Error("Required npm script missing: "+k)'
  npm ci
  npm run lint
  npm run typecheck
  npm run test:ci
  npm run build
)

case "$PROFILE" in
  backend) verify_backend ;;
  frontend) verify_frontend ;;
  combined) verify_backend; verify_frontend ;;
esac
echo "Verification passed ($PROFILE). This does not replace runtime or security validation."
