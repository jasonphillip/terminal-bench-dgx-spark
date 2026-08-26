#!/usr/bin/env bash
# Run a fixed Terminal-Bench 2.0 panel against a local OpenAI-compatible endpoint,
# with the multipliers needed for amd64-under-qemu on arm64.
#
# Env:
#   LOCAL_BASE_URL   e.g. http://192.168.1.50:8002/v1        (required)
#   LOCAL_MODEL      served model name at that endpoint       (required)
#   PANEL_SIZE       tasks per run (default 12)
#   TRIALS           attempts per task (default 2)
#   CTX / OUT        context/output token limits advertised to the agent
set -euo pipefail

: "${LOCAL_BASE_URL:?set LOCAL_BASE_URL}"
: "${LOCAL_MODEL:?set LOCAL_MODEL}"
PANEL_SIZE="${PANEL_SIZE:-12}"
TRIALS="${TRIALS:-2}"
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
  --agent-setup-timeout-multiplier 8 \
  --agent-timeout-multiplier 6 \
  --timeout-multiplier 3 \
  -l "$PANEL_SIZE" -n "$TRIALS" \
  --output-dir "$RESULTS_DIR/$JOB"

# append summary: date,trials,errors,mean_reward
python3 - "$RESULTS_DIR/$JOB" "$RESULTS_DIR/scores.csv" <<'PY'
import json, glob, sys, os, csv, datetime
job, out = sys.argv[1], sys.argv[2]
rewards, errors = [], 0
for f in glob.glob(os.path.join(job, "**", "result.json"), recursive=True):
    try:
        r = json.load(open(f))
        v = r.get("reward")
        if v is None: errors += 1
        else: rewards.append(float(v))
    except Exception:
        errors += 1
new = not os.path.exists(out)
with open(out, "a", newline="") as fh:
    w = csv.writer(fh)
    if new: w.writerow(["date", "trials", "errors", "mean_reward"])
    mean = sum(rewards)/len(rewards) if rewards else ""
    w.writerow([datetime.date.today().isoformat(), len(rewards), errors, mean])
print("appended:", out)
PY
