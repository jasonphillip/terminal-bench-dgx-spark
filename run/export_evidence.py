"""Export a small, sanitized evidence bundle from an existing Harbor job."""

import argparse
import datetime as dt
import json
import math
import re
import shlex
from pathlib import Path


SEGFAULT_MARKERS = ("Segmentation fault", "uncaught target signal")


def sanitize(value):
    """Scrub paths, network addresses, credentials, and private links."""
    if isinstance(value, dict):
        return {sanitize(str(k)): sanitize(v) for k, v in value.items()
                if not re.search(r"api.?key|token|secret", str(k), re.I)}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"https?://[^\s\"'<>]*claude\.ai[^\s\"'<>]*", "<redacted-link>", value, flags=re.I)
    value = re.sub(r"https?://[^\s\"'<>]*/sessions?/[^\s\"'<>]*", "<redacted-link>", value, flags=re.I)
    value = re.sub(r"/home/[^\s\"'<>),;]+", "<home>", value)
    value = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<host>", value)
    value = re.sub(r"(?i)\b(?:api.?key|token|secret)\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,}]+)", "<redacted>", value)
    return re.sub(r"(?i)api.?key|token|secret|session", "<redacted>", value)


def elapsed(start, finish):
    if not start or not finish:
        return None
    def parse(value):
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return round((parse(finish) - parse(start)).total_seconds(), 3)


def load(path):
    return json.loads(path.read_text())


def classify(trial):
    """Match summarize.py: segfault first, then finite reward, else error."""
    verifier = trial / "verifier"
    stdout = verifier / "test-stdout.txt"
    segfault = stdout.is_file() and any(
        marker in stdout.read_text(errors="replace") for marker in SEGFAULT_MARKERS
    )
    if segfault:
        return "invalid_verifier", None, True
    try:
        reward = float((verifier / "reward.txt").read_text().strip())
        if math.isfinite(reward):
            return "valid", reward, False
    except (OSError, ValueError):
        pass
    return "error", None, False


def command(config, provider_config, provider, model, dataset):
    agent = config["agents"][0]
    safe_provider = {
        "provider": {provider: {
            "npm": provider_config.get("npm"),
            "name": provider_config.get("name"),
            "options": {"baseURL": sanitize(provider_config.get("options", {}).get("baseURL", ""))},
            "models": {model: {"limit": provider_config["models"][model].get("limit", {})}},
        }}
    }
    base_url = safe_provider["provider"][provider]["options"]["baseURL"]
    base_url = re.sub(r"(?<=://)[^/:]+", "<inference-host>", base_url)
    safe_provider["provider"][provider]["options"]["baseURL"] = base_url
    args = ["harbor", "run", "-d", f"{dataset['name']}@{dataset['version']}",
            "-a", agent["name"], "-m", f"{provider}/{model}",
            "--ak", "opencode_config=" + json.dumps(safe_provider, separators=(",", ":"))]
    if agent.get("extra_allowed_hosts"):
        args += ["--allow-agent-host", "<host>"]
    if config.get("environment", {}).get("force_build"):
        args.append("--force-build")
    for key, flag in (("agent_setup_timeout_multiplier", "--agent-setup-timeout-multiplier"),
                      ("agent_timeout_multiplier", "--agent-timeout-multiplier"),
                      ("timeout_multiplier", "--timeout-multiplier")):
        if key in config:
            args += [flag, str(config[key])]
    args += ["-l", str(dataset["n_tasks"]), "-k", str(config.get("n_attempts", 1)),
             "-n", str(config["n_concurrent_trials"])]
    for task in dataset.get("exclude_task_names", []):
        args += ["-x", sanitize(task)]
    args += ["--jobs-dir", "<home>", "--job-name", sanitize(config["job_name"])]
    return sanitize(shlex.join(args)) + "\n"


def export(job, out, harbor_version=None):
    config, result = load(job / "config.json"), load(job / "result.json")
    dataset, agent = config["datasets"][0], config["agents"][0]
    provider, model = agent["model_name"].split("/", 1)
    raw_provider = agent["kwargs"]["opencode_config"]
    raw_provider = json.loads(raw_provider) if isinstance(raw_provider, str) else raw_provider
    provider_config = raw_provider["provider"][provider]
    limits = provider_config["models"][model]["limit"]
    ordered = []
    for trial in job.iterdir():
        if trial.is_dir() and (trial / "result.json").is_file():
            data = load(trial / "result.json")
            ordered.append((data.get("started_at") or "", trial.name, trial, data))
    ordered.sort()
    records, versions = [], set()
    for _, name, trial, data in ordered:
        status, reward, segfault = classify(trial)
        version = data.get("agent_info", {}).get("version")
        if version:
            versions.add(version)
        exception = data.get("exception_info") or {}
        records.append(sanitize({
            "task_name": data.get("task_name"), "trial_dir": name,
            "started_at": data.get("started_at"), "finished_at": data.get("finished_at"),
            "elapsed_seconds": elapsed(data.get("started_at"), data.get("finished_at")),
            "status": status, "reward": reward,
            "exception_type": exception.get("exception_type") if status != "valid" else None,
            "exception_message": exception.get("exception_message") if status != "valid" else None,
            "verifier_segfault": segfault,
        }))
    counts = {status: sum(r["status"] == status for r in records)
              for status in ("valid", "error", "invalid_verifier")}
    rewards = [r["reward"] for r in records if r["status"] == "valid"]
    summary = {"total_trials": len(records), **counts,
               "mean_reward_valid": sum(rewards) / len(rewards) if rewards else None,
               "completion_rate": counts["valid"] / len(records) if records else None}
    manifest = sanitize({
        "job_name": config["job_name"], "dataset_name": dataset["name"],
        "dataset_version": dataset["version"],
        "task_list": [r["task_name"] for r in records],
        "exclude_count": len(dataset.get("exclude_task_names", [])),
        "model_name": model, "provider_name": provider,
        "inference_location": "remote vLLM endpoint on the LAN",
        "base_url": re.sub(r"(?<=://)[^/:]+", "<inference-host>",
                           sanitize(provider_config.get("options", {}).get("baseURL", ""))),
        "context_limit": limits.get("context"), "output_limit": limits.get("output"),
        "timeout_multipliers": {
            "agent_setup": config.get("agent_setup_timeout_multiplier"),
            "agent": config.get("agent_timeout_multiplier"),
            "overall": config.get("timeout_multiplier")},
        "concurrency": config.get("n_concurrent_trials"),
        "attempts": config.get("n_attempts", 1),
        "force_build": config.get("environment", {}).get("force_build", False),
        "harbor_version": harbor_version, "opencode_versions": sorted(versions),
        "started_at": result.get("started_at"), "finished_at": result.get("finished_at"),
        "elapsed_seconds": elapsed(result.get("started_at"), result.get("finished_at")),
    })
    out.mkdir(parents=True, exist_ok=True)
    for filename, data in (("manifest.json", manifest), ("trials.json", records),
                           ("summary.json", summary)):
        (out / filename).write_text(json.dumps(data, indent=2) + "\n")
    (out / "command.txt").write_text(command(config, provider_config, provider, model, dataset))
    representative = next((trial for _, _, trial, data in ordered
                           if classify(trial)[0] == "invalid_verifier" and
                           (trial / "verifier" / "test-stdout.txt").is_file()), None)
    if representative is None:
        representative = next((trial for _, _, trial, data in ordered
                               if (trial / "verifier" / "test-stdout.txt").is_file()), None)
    excerpt = ""
    if representative:
        lines = (representative / "verifier" / "test-stdout.txt").read_text(errors="replace").splitlines()
        excerpt = "\n".join(sanitize(line) for line in lines[-40:]) + "\n"
    (out / "verifier-excerpt.txt").write_text(excerpt)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--harbor-version")
    args = parser.parse_args()
    print(json.dumps(export(args.job_dir, args.out_dir, args.harbor_version)))


if __name__ == "__main__":
    main()
