from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from witness_cl.ace_memory import ACEMemory, ACE_COMMIT, generator_schema
from witness_cl._vendor.ace.playbook_utils import apply_curator_operations


class Client:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, messages, budget, **kwargs):
        self.calls.append((deepcopy(messages), kwargs))
        kwargs["records"].append({"phase": kwargs["phase"], "usage": {
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply) if isinstance(reply, dict) else reply


def stage(memory, *, correct=True):
    memory.finish({"learn": True, "phase": "ordinary", "question": "Observed question",
                   "answer": 7, "feedback": {"correct": correct},
                   "hidden_answer": "SECRET_EVALUATOR"},
                  [{"role": "user", "content": "actual public observation",
                    "metadata": {"secret": "SECRET_METADATA"}}])


def update(memory, operations):
    stage(memory)
    client = Client([{"bullet_tags": []}, {"reasoning": "observed", "operations": operations}])
    records = []
    memory.update(client, object(), records)
    return client, records


def test_exact_official_add_merge_counter_behavior_and_public_boundary(capsys):
    memory = ACEMemory()
    before = memory.playbook
    operations = [{"type": "ADD", "section": "CODE SNIPPETS & TEMPLATES",
                   "content": "SELECT SUM(amount) FROM items WHERE group_name = :group"}]
    expected, next_id = apply_curator_operations(before, operations, 1)
    client, records = update(memory, operations)
    assert (memory.playbook, memory.next_id) == (expected, next_id)
    assert len(records) == 2
    assert [r["phase"] for r in records] == ["ace:reflector:reflection", "ace:curator:reflection"]
    assert "SECRET" not in json.dumps(client.calls, default=str)
    memory.decode_generator(json.dumps({"reasoning": "apply code", "bullet_ids": ["code-00001"],
                                       "final_answer": {"action": "ANSWER", "content": "7"}}))
    stage(memory)
    client = Client([{"bullet_tags": [{"id": "code-00001", "tag": "helpful"}]},
                     {"reasoning": "nothing new", "operations": [{"type": "DELETE", "id": "code-00001"}]}])
    memory.update(client, object(), [])
    assert "helpful=1 harmful=0" in memory.playbook
    assert "SELECT SUM" in memory.playbook  # Official DELETE is a no-op.


def test_generator_uses_official_roles_and_nested_native_action():
    memory = ACEMemory()
    action_schema = {"type": "object", "properties": {"action": {"type": "string"}}}
    messages = memory.generator_messages("question", [{"role": "user", "content": "rows"}], action_schema)
    assert "curated playbook" in messages[0]["content"]
    assert "rows" in messages[0]["content"]
    assert generator_schema(action_schema)["properties"]["final_answer"] == action_schema
    action = memory.decode_generator('{"reasoning":"r","bullet_ids":["invented"],"final_answer":{"action":"QUERY"}}')
    assert action == {"action": "QUERY"}
    assert memory.used_ids == []


def test_rejected_update_closes_episode_and_next_episode_updates():
    memory = ACEMemory()
    before = memory.playbook
    stage(memory)
    client = Client([{"bullet_tags": []}, {"reasoning": "bad", "operations": "not a list"}])
    event = memory.update(client, object(), [])
    assert event["status"] == "rejected"
    assert memory.pending is None and memory.playbook == before
    update(memory, [{"type": "ADD", "section": "OTHERS", "content": "next episode succeeds"}])
    assert "next episode succeeds" in memory.playbook


def test_transport_failure_retains_receipt_and_is_not_silenced():
    memory = ACEMemory()
    stage(memory)
    records = []
    with pytest.raises(RuntimeError, match="unknown usage"):
        memory.update(Client([RuntimeError("unknown usage")]), object(), records)
    assert len(records) == 1 and memory.pending is None
    assert memory.events[-1]["status"] == "failed"


def test_snapshot_restores_pending_generator_citations_exactly():
    memory = ACEMemory()
    update(memory, [{"type": "ADD", "section": "OTHERS", "content": "observed"}])
    memory.decode_generator('{"bullet_ids":["misc-00001"],"final_answer":{"action":"ANSWER","content":"7"}}')
    stage(memory)
    snapshot = memory.snapshot()
    restored = ACEMemory.from_snapshot(json.loads(json.dumps(snapshot)))
    assert restored.snapshot() == snapshot
    assert restored.state_digest() == memory.state_digest()
    restored.pending["question"] = "new"
    assert memory.pending["question"] != "new"
    snapshot["upstream_commit"] = "wrong"
    with pytest.raises(ValueError):
        ACEMemory.from_snapshot(snapshot)


def test_vendor_hashes_match_declared_official_copy():
    root = Path(__file__).parents[1] / "src/witness_cl/_vendor/ace"
    manifest = json.loads((root / "PROVENANCE.json").read_text())
    assert manifest["commit"] == ACE_COMMIT
    assert "Apache License" in (root / "LICENSE.txt").read_text()
    for filename, record in manifest["files"].items():
        if "local_sha256" in record:
            assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == record["local_sha256"]


def test_byte_cap_rejects_whole_delta_without_rewriting_old_bullets():
    memory = ACEMemory(max_playbook_bytes=1024)
    before = memory.playbook
    update(memory, [{"type": "ADD", "section": "OTHERS", "content": "x" * 2000}])
    assert memory.playbook == before
    assert memory.events[-1]["status"] == "rejected"
