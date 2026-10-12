# Terminal-Bench 2.0 on NVIDIA DGX Spark (GB10 / arm64)

Run [Harbor / Terminal-Bench 2.0](https://www.tbench.ai/) against a **local model served
on NVIDIA DGX Spark** hardware — and against any OpenAI-compatible local endpoint.

## What this is, in one verifiable line

Seven consecutive nightly runs of a rotating 12-task Terminal-Bench 2.0 panel on one DGX Spark produced 84 valid trials and 0 invalid verifiers once harbor built the task images natively for arm64. <!-- results/scores.csv -->

The mechanism is `--force-build` in place of qemu emulation.

Verify it by reading `results/scores.csv` and the resolution note in this README.

The canonical source is https://github.com/jasonphillip/terminal-bench-dgx-spark

Extracted from a private working tree on 2026-08-26.

As far as I can find, nobody publishes agentic-benchmark numbers for local models on GB10
hardware. This repo documents the full working setup, because getting there is non-obvious:
TB2 task images are amd64, DGX Spark is arm64, and the stock agent provider config rejects
common local servers.

## The three problems and their fixes

| Problem | Symptom | Fix |
|---|---|---|
| amd64 task images on arm64 | task containers exit 255 | `--force-build` builds task images natively for arm64 (former workaround: qemu binfmt + `net.ipv4.ip_forward=1`) |
| task setup and execution timeouts | `AgentSetupTimeoutError` | native builds with `--force-build` and setup/agent/task timeout multipliers 3/2/2 (former workaround: setup multiplier 8 under qemu) |
| stock `openai` provider vs local servers | vLLM returns 214 validation errors (`string_type`) | inject an `@ai-sdk/openai-compatible` provider via `--ak opencode_config=` (`configs/opencode-provider.example.json`) |

## Quickstart

```bash
export LOCAL_BASE_URL="http://<your-endpoint>:8002/v1"
export LOCAL_MODEL="<served-model-name>"
# Host prerequisite: task networking requires IPv4 forwarding.
sudo sysctl -w net.ipv4.ip_forward=1
# run/bench.sh passes --force-build so task images build natively for arm64 (no qemu).
bash run/bench.sh
```

Results append to `results/scores.csv` (date, trials, errors, mean reward).

## RESOLVED 2026-08-28: build task images natively instead of emulating

Every TB2 task ships a Dockerfile, and all 36 cached tasks build cleanly for arm64.
Passing `--force-build` to `harbor run` makes harbor build each environment from its
Dockerfile on the local daemon instead of pulling the amd64 prebuilt image. The verifier
then runs natively and the segfault below never happens. Seven consecutive nightly runs
(2026-08-29 to 2026-09-04) produced 84 valid trials and 0 invalid verifiers; see
`results/scores.csv`. The emulation notes below are kept for anyone who still needs
amd64 images for other reasons.

## HISTORICAL: TB2 verifiers segfault under qemu (scores silently zero)

Run `sudo bash setup/enable-amd64-emulation.sh` only if you must run the amd64 prebuilt images instead of building natively.

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
`invalid_verifier` column. **Check that column before believing any score.** Upstream: this is astral-sh/uv **#16024** ("Segfault on amd64 under QEMU", open, labeled
external) — and the uv binary itself can segfault too, so `UV_PYTHON_PREFERENCE=only-system`
alone is not sufficient. The proven better paths (community evidence, Feb 2026): rebuild
task images **natively for arm64** (a SWE-bench native rebuild showed 6.3x speedup with
equivalent resolution rates), or run scoring on real x86 (Harbor cloud runners). Treat any
qemu-scored number as non-citable trend data at best.

## Read this before comparing numbers

Scores produced this way are **trend data, not leaderboard-comparable**:

- Task images are built from each task Dockerfile with `--force-build`, with setup/agent/task timeout multipliers of 3/2/2.
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
