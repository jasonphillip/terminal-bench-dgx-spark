#!/usr/bin/env bash
# Check Harbor and Docker without starting a trial or contacting a model.
set -euo pipefail

if ! command -v harbor >/dev/null 2>&1; then
  echo "harbor missing from PATH" >&2
  exit 1
fi
harbor --version

if docker info >/dev/null 2>&1; then
  echo "docker reachable"
else
  echo "docker unreachable"
fi

# Rich abbreviates long option names at the default terminal width.
help_text="$(COLUMNS=240 harbor run --help)"
for flag in --force-build --n-attempts --n-concurrent --jobs-dir --job-name \
  --agent-setup-timeout-multiplier --agent-timeout-multiplier \
  --timeout-multiplier --allow-agent-host; do
  if ! grep -Fq -- "$flag" <<<"$help_text"; then
    echo "missing Harbor flag: $flag" >&2
    exit 1
  fi
done
echo "Harbor flags present"

LOCAL_BASE_URL="${LOCAL_BASE_URL:-http://127.0.0.1:8002/v1}" \
LOCAL_MODEL="${LOCAL_MODEL:-<served-model-name>}" \
  bash "$(dirname "$0")/bench.sh" --print-command
