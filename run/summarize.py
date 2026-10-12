"""Append a Harbor job summary and write sanitized per-trial records."""

import csv
import datetime
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def task_id(trial):
    """Return the task name and the trial artifact that supplied it."""
    for filename in ("result.json", "config.json"):
        path = trial / filename
        if not path.is_file():
            continue
        try:
            config = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(config, dict):
            continue
        name = config.get("task_name")
        if isinstance(name, str) and name:
            return name, f"{filename}.task_name"
        if filename == "result.json":
            registry_id = config.get("task_id")
            if isinstance(registry_id, dict):
                name = registry_id.get("name")
                if isinstance(name, str) and name:
                    return name, "result.json.task_id.name"
                path = registry_id.get("path")
                if isinstance(path, str) and path.rstrip("/"):
                    return Path(path.rstrip("/")).name, "result.json.task_id.path"
        # TrialResult embeds TrialConfig; a standalone config.json has the
        # same task shape. Local/Git tasks use path; registry tasks use name.
        nested = config.get("config") if filename == "result.json" else config
        task = nested.get("task") if isinstance(nested, dict) else None
        if isinstance(task, dict):
            path = task.get("path")
            if isinstance(path, str) and path.rstrip("/"):
                return Path(path.rstrip("/")).name, f"{filename}.task.path"
            name = task.get("name")
            if isinstance(name, str) and name.rsplit("/", 1)[-1]:
                return name.rsplit("/", 1)[-1], f"{filename}.task.name"
    match = re.fullmatch(r"(.+)__([A-Za-z0-9]{7})", trial.name)
    return (match.group(1), "directory_name") if match else (None, "missing")


def harbor_version():
    if not shutil.which("harbor"):
        return None
    try:
        result = subprocess.run(
            ["harbor", "--version"], capture_output=True, text=True,
            check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or result.stderr.strip() or None


def summarize(job, out):
    today = datetime.date.today().isoformat()
    try:
        stats = json.loads((job / "result.json").read_text()).get("stats", {})
    except (OSError, ValueError, AttributeError):
        stats = {}
    rewards = []
    records = []
    for trial in sorted(path for path in job.iterdir() if path.is_dir()):
        verifier = trial / "verifier"
        stdout = verifier / "test-stdout.txt"
        status, reward = "error", None
        if stdout.is_file() and any(
            marker in stdout.read_text(errors="replace")
            for marker in ("Segmentation fault", "uncaught target signal")
        ):
            status = "invalid_verifier"
        else:
            try:
                reward = float((verifier / "reward.txt").read_text().strip())
                if not math.isfinite(reward):
                    reward = None
                else:
                    status = "valid"
                    rewards.append(reward)
            except (OSError, ValueError):
                pass
        identity, identity_source = task_id(trial)
        records.append({
            "trial_dir": trial.name, "task_id": identity,
            "task_id_source": identity_source,
            "status": status, "reward": reward,
        })

    config = {
        "date": today,
        "job_name": job.name,
        "model": os.environ.get("LOCAL_MODEL"),
        "harbor_version": harbor_version(),
        "panel_size": int(os.environ.get("PANEL_SIZE", "12")),
        "attempts": int(os.environ.get("TRIALS", "2")),
        "concurrency": int(os.environ.get("CONCURRENCY", "2")),
        "multipliers": {
            "agent_setup_timeout": int(os.environ.get("SETUP_TIMEOUT_MULTIPLIER", "3")),
            "agent_timeout": int(os.environ.get("AGENT_TIMEOUT_MULTIPLIER", "2")),
            "timeout": int(os.environ.get("TIMEOUT_MULTIPLIER", "2")),
        },
    }
    trial_out = out.with_name(f"{job.name}.trials.json")
    trial_out.write_text(json.dumps({"run_config": config, "trials": records}, indent=2) + "\n")

    errors = sum(record["status"] == "error" for record in records)
    invalid = sum(record["status"] == "invalid_verifier" for record in records)
    new = not out.exists()
    with out.open("a", newline="") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["date", "valid_trials", "errors", "mean_reward_valid",
                             "in_tokens", "out_tokens", "invalid_verifier"])
        mean = f"{sum(rewards) / len(rewards):.3f}" if rewards else ""
        writer.writerow([today, len(rewards), errors, mean,
                         stats.get("n_input_tokens", ""),
                         stats.get("n_output_tokens", ""), invalid])
    print("appended:", out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: summarize.py JOB_DIR SCORES_CSV")
    summarize(Path(sys.argv[1]), Path(sys.argv[2]))
