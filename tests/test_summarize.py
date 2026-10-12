import csv
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest


def test_missing_reward_is_counted_and_trials_are_recorded(tmp_path):
    job = tmp_path / "tb2-test"
    for name in ("valid", "missing", "segfault"):
        (job / name / "verifier").mkdir(parents=True)
    (job / "valid" / "verifier" / "reward.txt").write_text("1.0\n")
    (job / "segfault" / "verifier" / "test-stdout.txt").write_text(
        "Segmentation fault\n"
    )
    (job / "segfault" / "verifier" / "reward.txt").write_text("0.0\n")
    scores = tmp_path / "scores.csv"

    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "run/summarize.py"),
         str(job), str(scores)],
        check=True,
    )

    with scores.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["valid_trials"] == "1"
    assert rows[0]["errors"] == "1"
    assert rows[0]["invalid_verifier"] == "1"
    assert rows[0]["mean_reward_valid"] == "1.000"

    data = json.loads((tmp_path / "tb2-test.trials.json").read_text())
    assert len(data["trials"]) == 3
    assert {item["status"] for item in data["trials"]} == {
        "valid", "error", "invalid_verifier"
    }
    assert data["run_config"]["attempts"] == 2
    assert data["run_config"]["concurrency"] == 2
    assert data["run_config"]["job_name"] == "tb2-test"
    assert all(item["task_id_source"] == "missing" for item in data["trials"])
    assert {item["trial_dir"]: item["reward"] for item in data["trials"]} == {
        "valid": 1.0, "missing": None, "segfault": None,
    }


def test_malformed_reward_is_an_error(tmp_path):
    job = tmp_path / "tb2-test"
    verifier = job / "broken" / "verifier"
    verifier.mkdir(parents=True)
    (verifier / "reward.txt").write_text("not a number\n")
    scores = tmp_path / "scores.csv"

    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "run/summarize.py"),
         str(job), str(scores)],
        check=True,
    )

    with scores.open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert (row["valid_trials"], row["errors"], row["invalid_verifier"]) == (
        "0", "1", "0"
    )


@pytest.mark.parametrize("trial_name,result,config,expected,source", [
    (
        "example-task__YCkgJCT",
        {"task_name": "example-task", "task_id": {"path": "/tasks/example-task"},
         "config": {"task": {"path": "/tasks/example-task"}},
         "trial_name": "example-task__YCkgJCT"},
        {"task": {"path": "/tasks/example-task"},
         "trial_name": "example-task__YCkgJCT"},
        "example-task", "result.json.task_name",
    ),
    (
        "long_name_with_underscores_trunca__AbC1234", None,
        {"task": {"path": "/tasks/long_name_with_underscores_and_more"},
         "trial_name": "long_name_with_underscores_trunca__AbC1234"},
        "long_name_with_underscores_and_more", "config.json.task.path",
    ),
    (
        "registry_task__ZxY7654", None,
        {"task": {"name": "terminal-bench/registry_task"},
         "trial_name": "registry_task__ZxY7654"},
        "registry_task", "config.json.task.name",
    ),
    (
        "result_only__AbC1234",
        {"task_name": "result_only", "task_id": {"org": "terminal-bench",
         "name": "result_only"}, "config": {"task": {"name": "terminal-bench/result_only"}},
         "trial_name": "result_only__AbC1234"},
        None, "result_only", "result.json.task_name",
    ),
    ("fallback_name__YCkgJCT", None, None, "fallback_name", "directory_name"),
    ("unknown", None, None, None, "missing"),
])
def test_task_identity_from_harbor_artifacts(
    tmp_path, trial_name, result, config, expected, source
):
    job = tmp_path / "tb2-test"
    trial = job / trial_name
    (trial / "verifier").mkdir(parents=True)
    (trial / "verifier" / "reward.txt").write_text("0.5\n")
    if result is not None:
        (trial / "result.json").write_text(json.dumps(result))
    if config is not None:
        (trial / "config.json").write_text(json.dumps(config))
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "run/summarize.py"),
         str(job), str(tmp_path / "scores.csv")], check=True,
    )
    record = json.loads((tmp_path / "tb2-test.trials.json").read_text())["trials"][0]
    assert (record["task_id"], record["task_id_source"]) == (expected, source)


def test_job_names_are_distinct_and_explicit_job_wins(tmp_path):
    bench = Path(__file__).resolve().parents[1] / "run/bench.sh"
    date = tmp_path / "date"
    counter = tmp_path / "counter"
    date.write_text(
        "#!/bin/sh\n"
        f"n=$(cat {shlex.quote(str(counter))} 2>/dev/null || echo 0)\n"
        "n=$((n + 1))\n"
        f"echo \"$n\" > {shlex.quote(str(counter))}\n"
        "printf '20261012-15363%s\\n' \"$n\"\n"
    )
    date.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
           "LOCAL_BASE_URL": "http://127.0.0.1:8002/v1", "LOCAL_MODEL": "test"}
    env.pop("JOB", None)

    def command(environment):
        return subprocess.check_output(
            ["bash", str(bench), "--print-command"], env=environment, text=True
        )

    first, second = command(env), command(env)
    assert "--job-name tb2-20261012-153631" in first
    assert "--job-name tb2-20261012-153632" in second
    assert command({**env, "JOB": "repeat-a"}).rstrip().endswith("--job-name repeat-a")


def test_nonfinite_reward_is_an_error(tmp_path):
    job = tmp_path / "tb2-test"
    verifier = job / "nonfinite" / "verifier"
    verifier.mkdir(parents=True)
    (verifier / "reward.txt").write_text("nan\n")
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "run/summarize.py"),
         str(job), str(tmp_path / "scores.csv")], check=True,
    )
    record = json.loads((tmp_path / "tb2-test.trials.json").read_text())["trials"][0]
    assert record["status"] == "error"
    assert record["reward"] is None
