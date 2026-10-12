# Results

`scores.csv` accumulates one row per nightly run since the native-arm64 fix:
`date,valid_trials,errors,mean_reward_valid,in_tokens,out_tokens,invalid_verifier`.
Each new run also writes `<job>.trials.json` with run settings and one sanitized
status and reward record per trial. Missing or unreadable rewards count as errors.

Rows before 2026-08-29 are not included. Under qemu emulation the TB2 verifier
segfaulted before running tests, so every earlier score was invalid rather than zero.
From 2026-08-29 harbor builds each task environment natively with `--force-build`
and `invalid_verifier` has been 0 on every night.

These are trend numbers on a rotating 12-task panel with generous timeouts, driven by
one local model (DeepSeek V4 Flash via opencode). They track my own harness and model
changes over time. They are not comparable to leaderboard runs, and the panel rotates,
so night-to-night variance is mostly task mix. Read the caveats in the top-level README
before quoting anything here.
