#!/usr/bin/env bash
# Run a fixed Terminal-Bench 2.0 panel against a local OpenAI-compatible endpoint,
# building each task environment natively (--force-build) so the TB2 verifier runs
# without qemu. Harbor 0.22.0 uses -k for attempts and -n for concurrency.
# Multipliers are sized from 84 native trials (setup max 124s, agent p90 4638s);
# the old 8/6/3 values were for emulation.
#
# Env:
#   LOCAL_BASE_URL   e.g. http://192.168.1.50:8002/v1        (required)
#   LOCAL_MODEL      served model name at that endpoint       (required)
#   PANEL_SIZE       tasks per run (default 12)
#   TRIALS           attempts per task (default 2)
#   CONCURRENCY      concurrent trials (default 2)
#   CTX / OUT        context/output token limits advertised to the agent
set -euo pipefail

: "${LOCAL_BASE_URL:?set LOCAL_BASE_URL}"
: "${LOCAL_MODEL:?set LOCAL_MODEL}"
PANEL_SIZE="${PANEL_SIZE:-12}"
TRIALS="${TRIALS:-2}"
CONCURRENCY="${CONCURRENCY:-2}"
SETUP_TIMEOUT_MULTIPLIER=3
AGENT_TIMEOUT_MULTIPLIER=2
TIMEOUT_MULTIPLIER=2
export PANEL_SIZE TRIALS CONCURRENCY SETUP_TIMEOUT_MULTIPLIER AGENT_TIMEOUT_MULTIPLIER TIMEOUT_MULTIPLIER
CTX="${CTX:-131072}"
OUT="${OUT:-32768}"
HOST_IP="$(echo "$LOCAL_BASE_URL" | sed -E 's#https?://([^:/]+).*#\1#')"
RESULTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/results"
JOB="tb2-$(date +%F)"

# The provider block is the load-bearing part: the stock `openai` provider fails
# schema validation against vLLM (214 "string_type" errors). openai-compatible works.
OPENCODE_CONFIG=$(cat <<EOF
{"provider":{"local":{"npm":"@ai-sdk/openai-compatible","name":"Local endpoint","options":{"baseURL":"$LOCAL_BASE_URL","apiKey":"local"},"models":{"$LOCAL_MODEL":{"name":"$LOCAL_MODEL","limit":{"context":$CTX,"output":$OUT}}}}}}
EOF
)

harbor run -d terminal-bench@2.0 -a opencode -m "local/$LOCAL_MODEL" \
  --ak "opencode_config=$OPENCODE_CONFIG" \
  --allow-agent-host "$HOST_IP" \
  --force-build \
  --agent-setup-timeout-multiplier "$SETUP_TIMEOUT_MULTIPLIER" \
  --agent-timeout-multiplier "$AGENT_TIMEOUT_MULTIPLIER" \
  --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
  -l "$PANEL_SIZE" -k "$TRIALS" -n "$CONCURRENCY" \
  --jobs-dir "$RESULTS_DIR" --job-name "$JOB"

# A segfaulted verifier is invalid, even when it emitted a reward.
python3 "$(dirname "$0")/summarize.py" "$RESULTS_DIR/$JOB" "$RESULTS_DIR/scores.csv"
