import pytest
from witness_cl.campaign_io import (
    JournalClient, UncertainCall, journal_usage, read, save, study_lock, usage,
)
from witness_cl.model_v8 import InferenceBudget
from test_sql_harness_v8 import ScriptedClient


def test_completed_call_recovery_spends_no_second_physical_generation(tmp_path):
    actual = ScriptedClient(lambda *_: {"answer": 17})
    kwargs = dict(phase="ordinary:solve", output_tokens=100, response_schema={"type": "object"})
    records = []
    a = JournalClient(actual, tmp_path).complete(
        [{"role": "user", "content": "x"}], InferenceBudget(), records=records, **kwargs
    )
    recovered = []
    budget = InferenceBudget()
    b = JournalClient(actual, tmp_path).complete(
        [{"role": "user", "content": "x"}], budget, records=recovered, **kwargs
    )
    assert a == b and records == recovered and len(actual.seen) == 1
    assert budget.total_tokens == 10 and usage(records)["total_tokens"] == 10


def test_pending_call_never_automatically_retried(tmp_path):
    save(tmp_path / "000.json", {"state": "pending"})
    client = ScriptedClient(lambda *_: {})
    with pytest.raises(UncertainCall):
        JournalClient(client, tmp_path).complete(
            [],
            InferenceBudget(),
            phase="ordinary:solve",
            records=[],
            output_tokens=100,
            response_schema={},
        )
    assert not client.seen


def test_failed_call_retains_known_and_unknown_costs(tmp_path):
    class Failing:
        def complete(self, *a, records, **kw):
            records.append({"generation_attempted": True, "usage": None, "status": "failed"})
            raise RuntimeError("transport")

    records = []
    with pytest.raises(RuntimeError):
        JournalClient(Failing(), tmp_path).complete(
            [], InferenceBudget(), phase="ordinary:solve", records=records, output_tokens=100
        )
    assert usage(read(tmp_path / "000.json")["calls"])["unknown_usage_calls"] == 1
    assert records[0]["usage"] is None


@pytest.mark.parametrize("raises", [True, False])
def test_missing_backend_receipt_is_unknown_never_zero_or_retried(tmp_path, raises):
    class MissingReceipt:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            if raises:
                raise RuntimeError("lost response")
            return "{}"

    client = MissingReceipt()
    budget = InferenceBudget()
    records = []
    with pytest.raises(RuntimeError):
        JournalClient(client, tmp_path / "episode").complete(
            [], budget, phase="ordinary:solve", records=records, output_tokens=100)
    cost = journal_usage(tmp_path)
    assert cost["calls"] == budget.calls == client.calls == 1
    assert cost["unknown_usage_calls"] == budget.unknown_usage_calls == 1
    assert cost["total_tokens"] is None and cost["known_total_tokens"] == 0
    recovered = []
    with pytest.raises(UncertainCall):
        JournalClient(client, tmp_path / "episode").complete(
            [], InferenceBudget(), phase="ordinary:solve", records=recovered, output_tokens=100)
    assert client.calls == 1 and usage(recovered)["total_tokens"] is None


def test_pending_physical_request_is_in_manifest_cost_without_checkpoint(tmp_path):
    save(tmp_path / "episode" / "000.json", {"state": "pending"})
    result = journal_usage(tmp_path)
    assert result["potential_generation_calls"] == result["unknown_usage_calls"] == 1
    assert result["total_tokens"] is None


def test_failed_measured_call_recovery_preserves_known_cost(tmp_path):
    call = {"status": "failed", "generation_attempted": True,
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
    save(tmp_path / "000.json", {"state": "recorded", "calls": [call]})
    actual = ScriptedClient(lambda *_: {})
    budget, records = InferenceBudget(), []
    with pytest.raises(UncertainCall):
        JournalClient(actual, tmp_path).complete(
            [], budget, phase="ordinary:solve", records=records, output_tokens=100)
    assert not actual.seen and budget.total_tokens == 5 and usage(records)["total_tokens"] == 5


def test_exclusive_study_invocation_and_noncontiguous_call_journal(tmp_path):
    with study_lock(tmp_path):
        with pytest.raises(RuntimeError, match="another invocation"):
            with study_lock(tmp_path):
                pass
    journal = JournalClient(None, tmp_path / "calls")
    save(tmp_path / "calls" / "001.json", {"state": "pending"})
    journal.index = 1
    assert not journal.all_calls_consumed()
