import importlib.util
import json
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "export_evidence", Path(__file__).resolve().parents[1] / "run/export_evidence.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture_job(tmp_path, *, names, exceptions=None, missing=()):
    job = tmp_path / "job"
    job.mkdir()
    provider = {"provider": {"dsv4": {"options": {
        "baseURL": "http://192.168.1.7:8002/v1", "apiKey": "planted-key"},
        "models": {"model": {"limit": {}}}}}}
    (job / "config.json").write_text(json.dumps({
        "job_name": "nightly-test", "agents": [{"name": "opencode",
        "model_name": "dsv4/model", "kwargs": {"opencode_config": provider}}],
        "datasets": [{"name": "terminal-bench", "version": "2.0",
                      "n_tasks": len(names)}], "n_concurrent_trials": 1}))
    (job / "result.json").write_text(json.dumps({
        "stats": {"n_errored_trials": len(exceptions or {})}}))
    for index, name in enumerate(names):
        trial = job / f"{name}__AbC{index}"
        verifier = trial / "verifier"
        verifier.mkdir(parents=True)
        (verifier / "reward.txt").write_text("0.0")
        if name not in missing:
            (trial / "result.json").write_text(json.dumps({
                "task_name": name, "started_at": f"2026-09-04T02:0{index}:00Z",
                "exception_info": (exceptions or {}).get(name)}))
    return job


def test_missing_result_counts_as_incomplete(tmp_path):
    job = fixture_job(tmp_path, names=["qemu-alpine-ssh", "install-windows-3.11"],
                      missing={"install-windows-3.11"})
    out = tmp_path / "out"
    summary = module.export(job, out)
    assert summary["total_trials"] == 2
    assert summary["incomplete"] == 1
    assert summary["valid_reward_fraction"] == 0.5
    trial = next(t for t in json.loads((out / "trials.json").read_text())
                 if t["task_name"] == "install-windows-3.11")
    assert trial["status"] == "incomplete"
    assert trial["reason"] == "missing result.json"


def test_valid_reward_preserves_agent_exception(tmp_path):
    job = fixture_job(tmp_path, names=["install-windows-3.11"], exceptions={
        "install-windows-3.11": {"exception_type": "AgentTimeoutError",
                                 "exception_message": "Agent execution timed out"}})
    out = tmp_path / "out"
    summary = module.export(job, out)
    trial = json.loads((out / "trials.json").read_text())[0]
    assert (trial["status"], trial["reward"], trial["exception_type"]) == (
        "valid", 0.0, "AgentTimeoutError")
    assert summary["errored_trials"] == 1
    assert summary["harbor_errored_trials"] == 1


def test_sanitization_preserves_names_and_drops_sessions(tmp_path):
    names = ["qemu-alpine-ssh", "install-windows-3.11", "sanitize-git-repo",
             "count-dataset-tokens", "tokenizer-repair"]
    job = fixture_job(tmp_path, names=names, exceptions={
        "qemu-alpine-ssh": {"exception_type": "Failure",
            "exception_message": "see https://claude.ai/session/planted"},
        "install-windows-3.11": {"exception_type": "Failure",
            "exception_message": "bad apiKey=planted-key"},
        "sanitize-git-repo": {"exception_type": "Failure",
            "exception_message": "API session ses_abc123 failed"},
        "tokenizer-repair": {"exception_type": "Failure",
            "exception_message": "Harbor id 123e4567-e89b-12d3-a456-426614174000"}})
    out = tmp_path / "out"
    module.export(job, out)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["task_list"] == names
    trials = json.loads((out / "trials.json").read_text())
    assert [t["task_name"] for t in trials] == names
    assert trials[0]["exception_message"] is None
    assert trials[1]["exception_message"] == "bad <redacted-credential>"
    assert trials[2]["exception_message"] is None
    assert trials[4]["exception_message"] is None
    bundle = "\n".join(p.read_text() for p in out.iterdir())
    for forbidden in ("192.168.1.7", "/home/", "apiKey", "planted-key",
                      "claude.ai", "session"):
        assert forbidden.lower() not in bundle.lower()


def test_export_sanitizes_and_classifies(tmp_path):
    job = tmp_path / "nightly-test"
    job.mkdir()
    provider = {"provider": {"dsv4": {"npm": "@ai-sdk/openai-compatible",
                "name": "Local", "options": {"baseURL": "http://192.168.1.7:8002/v1",
                "apiKey": "private-key"},
                "models": {"deepseek-v4-flash": {"limit": {"context": 458752,
                                                        "output": 32768}}}}}}
    config = {"job_name": "nightly-test", "jobs_dir": "/home/alice/jobs",
              "agent_setup_timeout_multiplier": 8.0, "agent_timeout_multiplier": 6.0,
              "timeout_multiplier": 3.0, "n_concurrent_trials": 2,
              "environment": {"force_build": True},
              "agents": [{"name": "opencode", "model_name": "dsv4/deepseek-v4-flash",
                          "extra_allowed_hosts": ["192.168.1.7"],
                          "kwargs": {"opencode_config": provider}}],
              "datasets": [{"name": "terminal-bench", "version": "2.0",
                            "exclude_task_names": ["old-task"], "n_tasks": 4}]}
    (job / "config.json").write_text(json.dumps(config))
    (job / "result.json").write_text(json.dumps({
        "started_at": "2026-09-04T02:00:00", "finished_at": "2026-09-04T03:00:00"}))
    for index, (name, reward, stdout) in enumerate([
        ("valid", "1.0", "ok\n"),
        ("missing", None, "failed\n"),
        ("nan", "nan", "failed\n"),
        ("segfault", "0.0", "Segmentation fault at 192.168.1.7 /home/alice/x apiKey=abc\n"
         "https://claude.ai/session/private token=abc secret=abc\n"),
    ]):
        trial = job / f"{name}__AbC1234"
        verifier = trial / "verifier"
        verifier.mkdir(parents=True)
        if reward is not None:
            (verifier / "reward.txt").write_text(reward)
        (verifier / "test-stdout.txt").write_text(stdout)
        (trial / "result.json").write_text(json.dumps({
            "task_name": name, "started_at": f"2026-09-04T02:0{index}:00Z",
            "finished_at": f"2026-09-04T02:0{index}:10Z",
            "agent_info": {"version": "1.18.27"},
            "exception_info": {"exception_type": "Failed",
                               "exception_message": "see /home/alice/log session token=abc"}
        }))
    out = tmp_path / "out"
    summary = module.export(job, out, "0.22.0")
    assert summary == {"total_trials": 4, "valid": 1, "error": 2,
                       "invalid_verifier": 1, "incomplete": 0,
                       "errored_trials": 4, "harbor_errored_trials": None,
                       "mean_reward_valid": 1.0,
                       "valid_reward_fraction": 0.25}
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["task_list"] == ["valid", "missing", "nan", "segfault"]
    assert manifest["base_url"] == "http://<inference-host>:8002/v1"
    assert manifest["attempts"] == 1
    assert manifest["elapsed_seconds"] == 3600
    trials = json.loads((out / "trials.json").read_text())
    assert [trial["status"] for trial in trials] == [
        "valid", "error", "error", "invalid_verifier"]
    assert trials[-1]["verifier_segfault"] is True
    assert trials[-1]["reward"] is None
    assert trials[1]["exception_type"] == "Failed"
    assert "--force-build" in (out / "command.txt").read_text()
    assert "-x old-task" in (out / "command.txt").read_text()
    bundle = "\n".join(path.read_text() for path in out.iterdir())
    for forbidden in ("192.168.1.7", "/home/", "apiKey", "private-key",
                      "token", "secret", "claude.ai", "session"):
        assert forbidden not in bundle.lower()


def test_malformed_reward_and_qemu_marker(tmp_path):
    verifier = tmp_path / "verifier"
    verifier.mkdir()
    (verifier / "reward.txt").write_text("broken\n")
    assert module.classify(tmp_path) == ("error", None, False)
    (verifier / "test-stdout.txt").write_text("qemu: uncaught target signal 11\n")
    assert module.classify(tmp_path) == ("invalid_verifier", None, True)
