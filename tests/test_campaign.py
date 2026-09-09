from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from tools import campaign
from witness_cl.campaign_io import read, save, sha
from test_sql_harness_v8 import ScriptedClient


def setup(out, kind="development", arms=None):
    return campaign.freeze(
        out,
        kind=kind,
        seeds=[901971],
        arms=arms or ["full_history", "delayed"],
        conditions=["reuse"],
        runtime_config={},
        runtime_receipt={},
        client_config={"model": "explicit-offline-test-double", "context_tokens": 65536},
        old_replicates=1,
        allow_test_double=True,
    )


def client():
    return ScriptedClient(
        lambda *_: {"reasoning": "This is a software test response.",
                    "final_answer": {"action": "QUERY", "sql": "SELECT 0", "params": {}, "answer": True}}
    )


def test_checkpoint_resume_keeps_schedule_and_no_model_call_repetition(tmp_path):
    out = tmp_path / "study"
    setup(out)
    model = client()
    first = campaign.run(out, model, max_new_records=5)
    assert first["status"] == "checkpointed" and len(model.seen) == 5
    second = campaign.run(out, model, max_new_records=3)
    assert second["status"] == "checkpointed" and len(model.seen) == 8
    assert second["completed_records"] == 8
    result = campaign.audit(out)
    assert result["records_replayed"] == 8 and result["network_calls"] == 0


def test_frozen_panel_replays_and_does_not_learn(tmp_path):
    out = tmp_path / "study"
    frozen = setup(out, arms=["full_history"])
    result = campaign.run(out, client())
    assert result["status"] == "completed"
    assert result["completed_records"] == 72
    audit = campaign.audit(out)
    assert audit["complete"]
    records = campaign.load_records(out)
    assert all(
        r["before_snapshot"] == r["trace"]["memory"] for r in records if r["phase"] != "ordinary"
    )
    assert not campaign.summarize(records, frozen)["claim_confirmed"]


def test_qualification_has_all_four_cells_and_no_early_correctness_stop(tmp_path):
    out = tmp_path / "study"
    setup(out, kind="qualification", arms=["full_history"])
    result = campaign.run(out, client())
    assert result["completed_records"] == 32
    summary = read(out / "summary.json")
    assert len(summary["qualification_cells"]) == 4 and not summary["qualified"]
    assert all(x["n"] == 8 for x in summary["qualification_cells"])
    assert campaign.audit(out)["complete"]


def test_corrupted_completed_episode_cannot_be_resumed_or_reported_as_valid(tmp_path):
    out = tmp_path / "study"
    setup(out)
    campaign.run(out, client(), max_new_records=1)
    path = next((out / "episodes").glob("*.json"))
    record = read(path)
    record["trace"]["reward"] = 1.0
    save(path, record)
    with pytest.raises(ValueError):
        campaign.audit(out)
    model = client()
    with pytest.raises(ValueError):
        campaign.run(out, model, max_new_records=1)
    assert not model.seen


def test_before_after_use_paired_randomness_but_streams_are_independent():
    assert campaign.sampling_seed(1, "old_before", 0) == campaign.sampling_seed(1, "old_after", 0)
    assert campaign.sampling_seed(1, "old_before", 0) != campaign.sampling_seed(2, "old_before", 0)


def test_freeze_never_overwrites(tmp_path):
    out = tmp_path / "study"
    setup(out)
    with pytest.raises(ValueError):
        setup(out)


@pytest.mark.parametrize("field", ["sampling_seed", "episode_nonce", "episode_index", "key"])
def test_schedule_derived_identity_cannot_be_changed_in_saved_trace(tmp_path, field):
    out = tmp_path / "study"
    setup(out)
    campaign.run(out, client(), max_new_records=1)
    path = next((out / "episodes").glob("*.json"))
    record = read(path)
    if field in {"sampling_seed", "key"}:
        record[field] = 31 if field == "sampling_seed" else "forged"
    else:
        record["trace"][field] = 31 if field == "episode_index" else "forged"
    save(path, record)
    with pytest.raises(ValueError):
        campaign.audit(out)
    with pytest.raises(ValueError):
        campaign.run(out, client(), max_new_records=0)


def test_raw_receipt_modification_rejected_before_any_new_generation(tmp_path):
    out = tmp_path / "study"
    setup(out)
    campaign.run(out, client(), max_new_records=1)
    path = next((out / "calls").glob("*/*.json"))
    receipt = read(path)
    receipt["calls"][0]["content"] = "{}"
    save(path, receipt)
    model = client()
    with pytest.raises(ValueError, match="raw call journal"):
        campaign.run(out, model, max_new_records=1)
    assert not model.seen


def test_schedule_holes_and_orphans_are_rejected(tmp_path):
    out = tmp_path / "study"
    frozen = setup(out)
    campaign.run(out, client(), max_new_records=2)
    first = campaign.planned_records(frozen)[0]
    (out / "episodes" / (first["key"] + ".json")).unlink()
    with pytest.raises(ValueError, match="contiguous"):
        campaign.load_records(out)
    save(out / "episodes" / "unplanned.json", {})
    with pytest.raises(ValueError, match="unplanned"):
        campaign.load_records(out)


def test_completed_uncheckpointed_call_recovers_without_new_generation(tmp_path):
    out = tmp_path / "study"
    setup(out)
    model = client()
    campaign.run(out, model, max_new_records=1)
    next((out / "episodes").glob("*.json")).unlink()
    result = campaign.run(out, model, max_new_records=1)
    assert len(model.seen) == 1 and result["completed_records"] == 1
    assert campaign.audit(out)["records_replayed"] == 1


def test_pending_call_halts_with_unknown_cost_and_no_retry(tmp_path):
    out = tmp_path / "study"
    frozen = setup(out)
    first = campaign.planned_records(frozen)[0]
    save(out / "calls" / first["key"] / "000.json", {"state": "pending"})
    model = client()
    result = campaign.run(out, model)
    assert result["status"] == "unknown_usage" and not model.seen
    assert result["cost"]["total_tokens"] is None
    assert result["cost"]["unknown_usage_calls"] == 1
    with pytest.raises(ValueError):
        campaign.run(out, model)
    assert not model.seen


def test_process_interruption_without_episode_still_preserves_unknown_cost(tmp_path):
    class Interrupted:
        def complete(self, *args, **kwargs):
            raise KeyboardInterrupt()

    out = tmp_path / "study"
    setup(out)
    with pytest.raises(KeyboardInterrupt):
        campaign.run(out, Interrupted())
    result = read(out / "manifest.json")
    assert result["completed_records"] == 0 and result["cost"]["total_tokens"] is None
    assert result["cost"]["unknown_usage_calls"] == 1


def test_frozen_cli_runs_its_own_bundle_and_detects_tampering(tmp_path):
    out = tmp_path / "study"
    setup(out)
    campaign.run(out, client(), max_new_records=1)
    command = [sys.executable, str(Path(campaign.__file__)), "audit", "--out", str(out)]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout)["records_replayed"] == 1
    frozen_file = out / "sources/src/witness_cl/campaign_env.py"
    frozen_file.write_text(frozen_file.read_text() + "\n# tampered\n")
    failed = subprocess.run(command, capture_output=True, text=True)
    assert failed.returncode != 0 and "frozen source changed" in failed.stderr


def test_environment_change_and_semantic_parameter_tampering_are_not_ignored(tmp_path):
    frozen = setup(tmp_path / "study")
    frozen["environment"]["sqlite"] = "other"
    with pytest.raises(ValueError, match="environment"):
        campaign.check_freeze(frozen)
    first = {"params": {"elapsed_seconds": 1}}
    second = {"params": {"elapsed_seconds": 2}}
    assert campaign.semantic(first) != campaign.semantic(second)


def test_exact_real_wire_generation_policy_is_validated_without_network(tmp_path):
    from witness_cl.model_campaign import build_client
    from witness_cl.model_v8 import InferenceBudget

    config = read(Path(campaign.ROOT) / "configs/campaign_runtime.json")
    key = tmp_path / "key"
    key.write_text("test-only")
    model = build_client(config, key)

    def post(path, body, timeout):
        if path.endswith("input_tokens"):
            return {"input_tokens": 12}
        return {"model": config["model"]["alias"],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}

    model._post = post
    records = []
    model.complete([], InferenceBudget(), phase="ordinary:solve", records=records,
                   output_tokens=4096, response_schema={"type": "object"})
    frozen = {"contains_test_double_calls": False, "client_config": model.snapshot_config()}
    call = records[0]
    assert campaign.validate_call(call, frozen, model.decoding.seed)["total_tokens"] == 15
    for key, value in (("cache_prompt", True), ("repeat_last_n", -1), ("stream", True),
                       ("unfrozen_argument", 1)):
        altered = deepcopy(call)
        altered["request_config"][key] = value
        with pytest.raises(ValueError):
            campaign.validate_call(altered, frozen, model.decoding.seed)


def test_main_studies_cannot_bypass_missing_qualification_or_confirmation_power():
    options = dict(kind="development", seeds=[123], conditions=["reuse"], client_config={},
                   source_hashes={})
    with pytest.raises(ValueError, match="qualification"):
        campaign._prerequisites(**options)
    options["kind"] = "qualification"
    assert campaign._prerequisites(**options) == ({}, {})


def test_live_runtime_identity_checks_process_model_backend_and_conversion(tmp_path, monkeypatch):
    config = read(Path(campaign.ROOT) / "configs/campaign_runtime.json")
    backend = tmp_path / "backend"
    binary = backend / "build/bin/llama-server"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"fixture-server")
    converter = backend / "convert_hf_to_gguf.py"
    converter.write_bytes(b"fixture-converter")
    model = tmp_path / "cache/models" / config["model"]["filename"]
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fixture-model")
    identity = {"commit": config["backend"]["commit"], "converter_sha256": sha(converter),
                "binary_sha256": sha(binary), "shared_libraries_sha256": {}}
    conversion = model.parent.parent / "conversion.json"
    save(conversion, {"status": "verified", "model": config["model"], "backend": identity,
                      "output_sha256": sha(model)})
    command = [str(binary), "--model", str(model), "--alias", config["model"]["alias"],
               "--host", "127.0.0.1", "--port", "18085", "--ctx-size", "65536",
               "--parallel", "1", "--cache-type-k", "f16", "--cache-type-v", "f16",
               "--rope-scaling", "none", "--no-context-shift"]
    process = tmp_path / "proc/1"
    process.mkdir(parents=True)
    (process / "cmdline").write_bytes(b"\0".join(word.encode() for word in command) + b"\0")
    (process / "exe").symlink_to(binary)
    receipt = {"status": "running", "config": config, "pid": 1, "command": command,
               "backend": identity, "model_sha256": sha(model),
               "conversion_receipt_sha256": sha(conversion)}
    frozen = {"runtime_config": config, "runtime_receipt": receipt}
    monkeypatch.setattr(campaign.subprocess, "check_output",
                        lambda args, **kw: config["backend"]["commit"] if args[-1] == "HEAD" else "")
    assert campaign.runtime_identity(frozen, proc_root=tmp_path / "proc")["model_sha256"] == sha(model)
    model.write_bytes(b"changed-model")
    with pytest.raises(ValueError, match="model bytes"):
        campaign.runtime_identity(frozen, proc_root=tmp_path / "proc")
    model.write_bytes(b"fixture-model")
    binary.write_bytes(b"changed-binary")
    with pytest.raises(ValueError, match="binary"):
        campaign.runtime_identity(frozen, proc_root=tmp_path / "proc")
