"""Export a small, sanitized evidence bundle from an existing Harbor job."""

import argparse
import datetime as dt
import json
import math
import re
import shlex
from pathlib import Path


SEGFAULT_MARKERS = ("Segmentation fault", "uncaught target signal")
URL = re.compile(r"https?://[^\s\"'<>]+", re.I)
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
HOME_PATH = re.compile(r"/home/[^\s\"'<>),;]+")
CREDENTIAL = re.compile(
    r"(?i)\b(?:api.?key|token|secret)\b\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)
SESSION_ID = re.compile(
    r"(?i)session|\b(?:ses|sess)[_-][A-Za-z0-9_-]+\b|"
    r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b"
)


def has_private_identifier(value):
    """Reject selected fields that still identify a session or private endpoint."""
    return bool(SESSION_ID.search(value) or re.search(r"claude\.ai|api.?key|/home/", value, re.I)
                or IPV4.search(value))


def public_name(value):
    """Preserve public names exactly, or omit an unsafe value."""
    return value if isinstance(value, str) and not has_private_identifier(value) else None


def sanitize_text(value):
    """Sanitize one selected free-text field; omit it if a session marker remains."""
    if not isinstance(value, str):
        return None
    if SESSION_ID.search(value) or any("claude.ai" in match.group().lower()
                                       for match in URL.finditer(value)):
        return None
    value = CREDENTIAL.sub("<redacted-credential>", value)
    value = HOME_PATH.sub("<home>", value)
    value = IPV4.sub("<host>", value)
    return None if has_private_identifier(value) else value


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
            "options": {"baseURL": sanitize_text(provider_config.get("options", {}).get("baseURL", "")) or ""},
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
        if public_name(task) is not None:
            args += ["-x", task]
    args += ["--jobs-dir", "<home>", "--job-name", public_name(config["job_name"]) or "<omitted>"]
    return (sanitize_text(shlex.join(args)) or "") + "\n"


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
        if trial.is_dir():
            data = load(trial / "result.json") if (trial / "result.json").is_file() else None
            ordered.append(((data or {}).get("started_at") or "", trial.name, trial, data))
    ordered.sort()
    records, versions = [], set()
    exception_count = 0
    for _, name, trial, data in ordered:
        status, reward, segfault = classify(trial) if data is not None else ("incomplete", None, False)
        version = (data or {}).get("agent_info", {}).get("version")
        if version:
            safe_version = public_name(version)
            if safe_version is not None:
                versions.add(safe_version)
        exception = (data or {}).get("exception_info") or {}
        exception_count += bool(exception)
        started_at, finished_at = (data or {}).get("started_at"), (data or {}).get("finished_at")
        record = {
            "task_name": public_name((data or {}).get("task_name") or name.rsplit("__", 1)[0]),
            "trial_dir": public_name(name),
            "started_at": public_name(started_at), "finished_at": public_name(finished_at),
            "elapsed_seconds": elapsed(started_at, finished_at),
            "status": status, "reward": reward,
            "exception_type": public_name(exception.get("exception_type")),
            "exception_message": sanitize_text(exception.get("exception_message")),
            "verifier_segfault": segfault,
        }
        if data is None:
            record["reason"] = "missing result.json"
        records.append(record)
    counts = {status: sum(r["status"] == status for r in records)
              for status in ("valid", "error", "invalid_verifier", "incomplete")}
    rewards = [r["reward"] for r in records if r["status"] == "valid"]
    summary = {"total_trials": len(records), **counts,
               "errored_trials": exception_count,
               "harbor_errored_trials": result.get("stats", {}).get("n_errored_trials"),
               "mean_reward_valid": sum(rewards) / len(rewards) if rewards else None,
               "valid_reward_fraction": counts["valid"] / len(records) if records else None}
    manifest = {
        "job_name": public_name(config["job_name"]), "dataset_name": public_name(dataset["name"]),
        "dataset_version": public_name(dataset["version"]),
        "task_list": [r["task_name"] for r in records],
        "exclude_count": len(dataset.get("exclude_task_names", [])),
        "model_name": public_name(model), "provider_name": public_name(provider),
        "inference_location": "remote vLLM endpoint on the LAN",
        "base_url": re.sub(r"(?<=://)[^/:]+", "<inference-host>",
                           sanitize_text(provider_config.get("options", {}).get("baseURL", "")) or ""),
        "context_limit": limits.get("context"), "output_limit": limits.get("output"),
        "timeout_multipliers": {
            "agent_setup": config.get("agent_setup_timeout_multiplier"),
            "agent": config.get("agent_timeout_multiplier"),
            "overall": config.get("timeout_multiplier")},
        "concurrency": config.get("n_concurrent_trials"),
        "attempts": config.get("n_attempts", 1),
        "force_build": config.get("environment", {}).get("force_build", False),
        "harbor_version": public_name(harbor_version), "opencode_versions": sorted(versions),
        "started_at": public_name(result.get("started_at")),
        "finished_at": public_name(result.get("finished_at")),
        "elapsed_seconds": elapsed(result.get("started_at"), result.get("finished_at")),
    }
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
        excerpt = "\n".join(clean for line in lines[-40:]
                            if (clean := sanitize_text(line)) is not None) + "\n"
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
