# Terminal-Bench 2.0 on NVIDIA DGX Spark (GB10 / arm64)

This repository helps someone run Terminal-Bench 2.0 against a local model on an arm64 DGX Spark. Terminal-Bench task images and verifiers need native arm64 builds for trustworthy scores on this host.

## What this is, in one verifiable line

Seven consecutive nightly runs of a rotating 12-task Terminal-Bench 2.0 panel on one DGX Spark produced 84 valid trials and 0 invalid verifiers once harbor built the task images natively for arm64. <!-- results/scores.csv -->

The mechanism is `--force-build` in place of qemu emulation.

Verify it by reading `results/scores.csv` and the resolution note in this README.

## What works today and its limits

The revised `run/bench.sh` runs a small panel through Harbor and builds task images locally. The seven recorded nights are trend data for a rotating panel. They are not comparable to leaderboard results. A 12-task panel has high variance. Native builds take longer on the first run, and some task Dockerfiles may not build on arm64.

## Setup

This host has Harbor 0.22.0 in its user Python site packages, with `harbor` at `~/.local/bin/harbor`. Install Harbor 0.22.0 with your preferred Python tool installer on another host. Harbor installs OpenCode inside the task container. The recorded trials used OpenCode 1.18.25 through 1.18.27.

Use an arm64 host with Docker available to your user through the `docker` group. Enable IPv4 forwarding for task networking. `--force-build` builds each task image from its Dockerfile on the host. A task image is not guaranteed to build on arm64.

## Quickstart

Set the endpoint and model name to values served by your local OpenAI-compatible server. This is the revised runner. The recorded CSV came from an earlier nightly script, described below.

```bash
export LOCAL_BASE_URL="http://<your-endpoint>:8002/v1"
export LOCAL_MODEL="<served-model-name>"
bash run/smoke.sh
sudo sysctl -w net.ipv4.ip_forward=1
bash run/bench.sh
```

`run/bench.sh` defaults to two attempts per task, two concurrent trials, and timeout multipliers 3/2/2. It creates a timestamped job name. Reusing `JOB` resumes that job.

## One measured result

On 2026-09-04, the recorded CSV reports 12 valid trials, 1 error, 0 invalid verifiers, and mean reward 0.667. Harbor's job `result.json` records one errored trial: `install-windows-3.11` raised `AgentTimeoutError` ("Agent execution timed out after 21600.0 seconds") and still wrote reward 0. The nightly CSV counted Harbor's agent-side exception as an error and included its reward in the 12 valid trials. The evidence bundle counts reward files instead, so it recomputes 12 valid trials, 0 errors, 0 invalid verifiers, and mean reward 0.667. The CSV stays as recorded.

```text
https://github.com/jasonphillip/terminal-bench-dgx-spark/blob/main/results/scores.csv
https://github.com/jasonphillip/terminal-bench-dgx-spark/tree/main/results/evidence/native-2026-09-04
```

## Main engineering decision

I chose native arm64 task builds with `--force-build` over qemu emulation or x86 cloud runners. The first build is slower. The verifiers run natively, so their rewards can pass the validity gate. See `docs/verifier-segfault-case-study.md` for the failure and decision record.

## Recorded-run provenance

A nightly timer script on the harness DGX Spark produced the seven rows dated 2026-08-29 through 2026-09-04. `run/bench.sh` is the revised runner and did not produce those rows. Harbor was 0.22.0 every night. The harness and task containers ran on a third DGX Spark. A remote vLLM endpoint used tensor parallelism across two other DGX Sparks on the same LAN. OpenCode used the `dsv4` OpenAI-compatible provider and model `deepseek-v4-flash`, DeepSeek V4 Flash. The served context limit was 458,752 tokens. OpenCode advertised context 458752 and output 32768.

The OpenCode trial versions were 1.18.25 on 2026-08-29 through 2026-09-01, 1.18.26 on 2026-09-02, and 1.18.27 on 2026-09-03 and 2026-09-04. Each night selected 12 Terminal-Bench 2.0 tasks with one attempt per task, two concurrent trials, `--force-build`, and setup, agent, and overall timeout multipliers 8/6/3. The revised runner defaults to 3/2/2.

The nightly script passed `-x` for every task in its seen list. Exclusion counts were 0, 12, 24, 36, 47, 58, and 69. Harbor's first-12 selection then reached new tasks. A seen-list bug repeated `install-windows-3.11` on 2026-09-01 through 2026-09-04. The bug was fixed on 2026-09-04. The 84 trials cover 81 distinct tasks.

The nightly CSV's `errors` column counted Harbor's errored trials, including agent-side exceptions that still wrote reward 0. The file-based evidence recount counts reward files, so that trial is valid there and adds no error. The revised summarizer counts missing, unreadable, malformed, and nonfinite rewards as errors. It excludes a verifier with a segfault marker from the valid mean. `results/scores.csv` stays as recorded. `results/evidence/` holds recomputed per-trial records and sanitized job metadata. Jobs from 2026-09-05 through 2026-09-09 exist in the job store but are not in the CSV.

## HISTORICAL: TB2 verifiers segfault under qemu

Many TB2 verifiers ran `uvx -p 3.13 ... pytest` under qemu-user. `uvx -p 3.13 python -c pass` alone crashed. The verifier stopped before scoring, so reward 0 did not describe the agent's work. The first three nightly runs had 29 invalid trials out of 30, as documented during the investigation.

Host apt qemu, the latest `tonistiigi/binfmt`, `QEMU_CPU` masking, and `GLIBC_TUNABLES=glibc.pthread.rseq=0` did not fix the crash. Docker-official Python and the uv image's Python ran under the same emulation. The upstream report is astral-sh/uv issue 16024.

```text
https://github.com/astral-sh/uv/issues/16024
```

The 2026-08-28 qemu evidence bundle has 12 invalid verifiers. The native 2026-09-04 bundle has 0. The summarizer still checks `verifier/test-stdout.txt` for segfault markers before accepting a reward. See the case study for the limits of this comparison.

## Read this before comparing numbers

These scores track this harness and model over time. A local model's tokens per second changes the work that fits inside each timeout. The rotating panel changes the task mix each night. Do not compare these scores directly with leaderboard runs.

## Hardware context

External llama.cpp batch-1 measurements report dense models at about 10 tok/s and Qwen3 30B-A3B at up to about 89 tok/s on DGX Spark. External Ollama dense results report 9.4 to 10.1 tok/s. The public figures come from these pages.

```text
https://github.com/DandinPower/llama.cpp_bench/blob/main/dgx_spark/report.md
https://huggingface.co/datasets/G3nadh/dgx-spark-benchmarks
```

Dense decode is too slow for agentic loops by my criterion: at ~10 tok/s a 2,000-token agent turn takes over three minutes. In my own vLLM FP8 runs on 2026-09-04, four 256-token generations measured 50 to 53 tok/s single stream. Those measurements are recorded in the companion repo's evidence folder.

When I started in August 2026 I found no published agentic-benchmark numbers for local models on GB10. That was my own search and I did not run a survey.

Serving notes live in the companion repo.

```text
https://github.com/jasonphillip/dgx-spark-llm-serving
```

## How this was built

I built this with LLM coding agents, Claude Code and Codex, under my direction. I set the requirements, chose the native-build approach, debugged the verifier failure, reviewed every change, and set the acceptance criteria. The agents wrote most of the code and tests.

## License

MIT.
