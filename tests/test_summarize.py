import csv
import json
import subprocess
import sys
from pathlib import Path


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
