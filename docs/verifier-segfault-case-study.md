# Verifier segfaults under qemu-user on arm64

The first attempt to run Terminal-Bench 2.0 on an arm64 DGX Spark used qemu emulation for amd64 task images. The visible score was often zero. That score was misleading because the verifier could crash before it evaluated the agent's work. The README records 29 invalid trials out of 30 in the first three nightly runs. This case study describes the observed failure, the alternatives tested, and the native-build decision. It uses the historical README account and two exported job bundles. It does not infer agent performance from a crashed verifier.

## Symptom and evidence

A Terminal-Bench trial contains the agent's work and a verifier that checks it. In the affected tasks, the verifier invoked `uvx -p 3.13 ... pytest`. Under qemu-user on arm64, the Python build that uv downloaded segfaulted. The verifier stopped before tests could produce a valid score. Reward 0 then appeared regardless of what the agent had done. The failure was in the scoring path, so a zero reward could not safely be read as an agent failure.

The archived qemu job from 2026-08-28 contains 12 trials. The exported bundle marks all 12 as `invalid_verifier`, with no valid rewards. Its representative verifier excerpt includes `qemu: uncaught target signal 11 (Segmentation fault)` followed by a shell line showing the `uvx -p 3.13 ... pytest` command terminated with a segmentation fault. The excerpt supplies one concrete example. The per-trial records and segfault flags support the count across the full job. The historical README supplies the separate 29-of-30 figure for the first three nights.

## What was tested

The minimal reproduction was smaller than a Terminal-Bench task. `uvx -p 3.13 python -c pass` crashed under qemu-user. That isolated the problem from the task tests and from the agent's output. The README reports that Docker-official Python and the uv image's Python ran under the same emulation. The difference pointed to the Python build fetched by uv. The README described its BOLT/PGO layout as a suspicion, not a proven cause. The related upstream report is astral-sh/uv issue 16024:

```text
https://github.com/astral-sh/uv/issues/16024
```

Several changes to emulation did not resolve the crash. The author tried host apt qemu and the latest `tonistiigi/binfmt` image. `QEMU_CPU` masking also failed. Setting `GLIBC_TUNABLES=glibc.pthread.rseq=0` did not help. These are reported attempts from the historical README. They narrow the practical options for this setup, but they do not prove a universal qemu or uv defect. The uv issue records the upstream context. The job bundle records the actual verifier failures in this run.

## Decision and validity gate

The author chose to build each task image natively for arm64 with Harbor's `--force-build`. This uses the task Dockerfile on the harness host instead of the prebuilt amd64 image under qemu. The other path considered was scoring on x86 cloud runners. Native builds kept the work on the DGX Spark setup and removed emulation from the verifier path. The tradeoff is a slower first build. A task Dockerfile is not guaranteed to build on arm64, so native build success must be checked for each panel.

The summarizer kept a separate validity gate. It scans `verifier/test-stdout.txt` for `Segmentation fault` or `uncaught target signal`. A matching trial is `invalid_verifier` even if a reward file contains zero. Otherwise, a finite parsed reward makes the trial valid. Missing, unreadable, malformed, or nonfinite rewards are errors in the revised summarizer. The gate prevents a verifier crash from lowering the valid-trial mean as though it were an agent result.

The native job bundle from 2026-09-04 records 12 valid trials and 0 invalid verifiers. Its mean reward over valid trials is 0.667 when rounded to three decimals. The seven recorded native nights from 2026-08-29 through 2026-09-04 total 84 valid trials and 0 invalid verifiers. Those counts establish that the selected native panels passed the verifier gate. They do not establish that every Terminal-Bench task builds on arm64 or that the scores are comparable to leaderboard runs. The panels were small and rotated across nights.

The author chose and validated the native-build approach, investigated the verifier failure, and set the acceptance criterion around valid verifier output. LLM coding agents wrote the scripts and tests under the author's direction. The resulting evidence bundles preserve sanitized per-trial status, timing, and reward records without agent transcripts.
