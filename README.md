# Terminal-Bench 2.0 on NVIDIA DGX Spark (GB10 / arm64)

Run [Harbor / Terminal-Bench 2.0](https://www.tbench.ai/) against a **local model served
on NVIDIA DGX Spark** hardware — and against any OpenAI-compatible local endpoint.

As far as I can find, nobody publishes agentic-benchmark numbers for local models on GB10
hardware. This repo documents the full working setup, because getting there is non-obvious:
TB2 task images are amd64, DGX Spark is arm64, and the stock agent provider config rejects
common local servers.

## The three problems and their fixes

| Problem | Symptom | Fix |
|---|---|---|
| amd64 task images on arm64 | task containers exit 255 | qemu binfmt + `net.ipv4.ip_forward=1` (`setup/enable-amd64-emulation.sh`) |
| emulation is slow | `AgentSetupTimeoutError` | `--agent-setup-timeout-multiplier 8` (and generous agent/task multipliers) |
| stock `openai` provider vs local servers | vLLM returns 214 validation errors (`string_type`) | inject an `@ai-sdk/openai-compatible` provider via `--ak opencode_config=` (`configs/opencode-provider.example.json`) |

## Quickstart

```bash
# one-time host prep (arm64 host running amd64 task images)
sudo bash setup/enable-amd64-emulation.sh

# point at your local endpoint and run a 12-task panel
export LOCAL_BASE_URL="http://<your-endpoint>:8002/v1"
export LOCAL_MODEL="<served-model-name>"
bash run/bench.sh
```

Results append to `results/scores.csv` (date, trials, errors, mean reward).

## KNOWN ISSUE: TB2 verifiers segfault under qemu (scores silently zero)

Bisected 2026-08-28: many TB2 task verifiers run `uvx -p 3.13 ... pytest`, and the
**python-build-standalone binary uv downloads segfaults under qemu-user on arm64** —
`uvx -p 3.13 python -c pass` alone crashes. The verifier dies before scoring, so the
trial reads reward 0 *regardless of what the agent did*. In my first three nightly runs,
29/30 trials were invalid this way.

Tested without success: host apt qemu, tonistiigi/binfmt latest (QEMU v9), `QEMU_CPU`
masking, `GLIBC_TUNABLES=glibc.pthread.rseq=0`. Docker-official python and the uv
docker image's python both run fine under the same emulation — the crash is specific to
uv's standalone build (BOLT/PGO layout suspected).

Mitigation in `run/bench.sh`: every trial's `verifier/test-stdout.txt` is scanned for
segfault markers; invalid trials are excluded from the mean and counted in an
`invalid_verifier` column. **Check that column before believing any score.** Candidate
real fixes (untested): inject `UV_PYTHON_PREFERENCE=only-system` + a system python 3.13
into task images, or a qemu build that survives BOLT-optimized binaries.

## Read this before comparing numbers

Scores produced this way are **trend data, not leaderboard-comparable**:

- Task images run under qemu emulation (slower; generous timeout multipliers).
- A local model's tokens/sec changes how much work fits inside timeouts.
- Small fixed panels (6–12 tasks) have high variance; the first-6-alphabetical TB2 tasks
  are all hard — a 0/6 night is signal about the panel, not only the model.

The honest use of this setup: track **your own** harness/model changes over time on a
fixed panel. Do not put these numbers next to leaderboard runs.

## Hardware context

Measured on DGX Spark (GB10, 128 GB unified, ~273 GB/s memory bandwidth). Decode is
bandwidth-bound: dense ~32B models decode at ~10 tok/s (unusable for agentic loops);
MoE models with small active parameter counts are the workable class (e.g.
Qwen3-30B-A3B ~44–89 tok/s single-stream on my units). Serving notes live in a companion
repo: [dgx-spark-llm-serving](https://github.com/jasonphillip/dgx-spark-llm-serving).

## License

MIT.
