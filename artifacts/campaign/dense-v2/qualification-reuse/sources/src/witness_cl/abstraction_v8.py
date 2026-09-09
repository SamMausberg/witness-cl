"""Model-proposed SQL relations checked against their own observed answer.

Discovery is an empirical program proposal, not a predefined feature dictionary.
One reconstructed training answer does not prove the relation's semantics.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import math
from .fragments_v8 import Fragment, PreparedQuery
from .memory_v8 import Entry, canonical, json_object, MAX_ENTRIES, MAX_MEMORY_BYTES
from .sql_env_v8 import MAX_SELECTS

PROPOSAL_PROMPT = '''Propose one reusable executable SQL relation from your own completed, correct episode. You may synthesize NEW SQL to factor out useful joins, transformations and filters; you are not limited to copying a query. Use only the actual schema/data observations and confirmed answer supplied here. No hidden answers or future tasks are available.
Choose source_index of a successful SELECT whose one numeric cell equals your confirmed answer. Propose a generalized SELECT relation with useful named columns and typed literal parameters, together with an outer SELECT that uses that relation as the CTE reused and reconstructs the source answer. For example a relation can expose normalized per-row values and an outer query can aggregate them. This example is a structural suggestion, not a supplied domain implementation. Prefer useful literal holes rather than baking in filter values. The host will actually execute the composition and compare its result with your own observed successful answer, consuming one of your remaining SELECT attempts. A matching witness is evidence only for this instance; future composition and rebinding are separate tests. Do not use a constant-answer outer query or an unused CTE as a claimed generalization.
Choose guard_index of a successful, complete observation that witnesses applicability, preferably catalog conventions unaffected by fresh transaction rows. A future use may check that exact observation again. Explain scope and uncertainty in at most512 characters.
Return JSON {"proposal":null} if no useful supported abstraction can be proposed. Otherwise return {"proposal":{"source_index":0,"guard_index":0,"sql":"SELECT ... AS useful_column FROM ... WHERE field=:filter","params":{"filter":"observed value"},"outer_sql":"SELECT SUM(useful_column) FROM reused","outer_params":{},"description":"..."}}. Use only :named literal bindings and no semicolons/comments. The proposal is data; it cannot approve itself or change any tool or limit.'''

_SCALAR = {'anyOf': [{'type': 'number'}, {'type': 'string'}, {'type': 'null'}]}
_PARAMS = {'type': 'object', 'additionalProperties': _SCALAR}
_FIELDS = {'source_index': {'type': 'integer', 'minimum': 0, 'maximum': 7},
           'guard_index': {'type': 'integer', 'minimum': 0, 'maximum': 7},
           'sql': {'type': 'string'}, 'params': _PARAMS,
           'outer_sql': {'type': 'string'}, 'outer_params': _PARAMS,
           'description': {'type': 'string', 'minLength': 1, 'maxLength': 512}}
PROPOSAL_SCHEMA = {'type': 'object', 'properties': {'proposal': {'anyOf': [
    {'type': 'null'}, {'type': 'object', 'properties': _FIELDS,
                     'required': list(_FIELDS), 'additionalProperties': False}]}},
    'required': ['proposal'], 'additionalProperties': False}


def proposal_messages(trace):
    # Explicit boundary: no evaluator metadata, seed, phase or other-arm state.
    return [{'role': 'system', 'content': PROPOSAL_PROMPT},
            {'role': 'user', 'content': canonical({
                'question': trace['question'], 'schema': trace['schema'],
                'queries': [{k: row[k] for k in ('sql', 'params', 'columns', 'rows', 'error',
                            'truncated', 'attempt', 'purpose', 'learning_check') if k in row}
                            for row in trace['queries']], 'answer': trace['answer'],
                'feedback_reward': trace['reward'],
                'remaining_learning_selects': MAX_SELECTS - len(trace['queries'])})}]


def scalar_result(row):
    if row['error'] is not None or row['truncated'] is not False:
        raise ValueError('a complete successful scalar query is required')
    rows = row['rows']
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError('one row and one numeric cell are required')
    x = rows[0][0]
    if not finite_scalar(x):
        raise ValueError('finite scalar witness required')
    return x


def finite_scalar(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def equal_scalar(x, y):
    return finite_scalar(x) and finite_scalar(y) and abs(x-y) <= 1e-6*(1+abs(y))


def _completed(trace):
    if (trace.get('status') != 'completed' or type(trace.get('reward')) not in (int, float)
            or trace['reward'] != 1.):
        raise ValueError('a correct completed own episode is required')


def _prefix_digest(trace, length):
    evidence = {k: trace[k] for k in ('question', 'schema', 'answer', 'reward')}
    evidence['queries'] = trace['queries'][:length]
    return hashlib.sha256(canonical(evidence).encode()).hexdigest()


def _charged_prefix(queries):
    if not 1 <= len(queries) <= MAX_SELECTS:
        raise ValueError('charged queries must fit the shared episode SELECT cap')
    if any(type(row.get('attempt')) is not int or row['attempt'] != index + 1
           for index, row in enumerate(queries)):
        raise ValueError('every observed query requires a contiguous charged attempt')


@dataclass(frozen=True)
class Proposal:
    fragment: Fragment
    guard: Fragment
    request: PreparedQuery
    expected_guard: str
    description: str
    source_index: int
    guard_index: int
    witnessed_value: int | float
    model_fields: str
    eligible_query_count: int
    eligible_prefix_digest: str


def prepare_proposal(text, trace):
    _completed(trace)
    x = json_object(text)
    if set(x) != {'proposal'}:
        raise ValueError('proposal envelope required')
    fields = x['proposal']
    if fields is None:
        return None
    if not isinstance(fields, dict) or set(fields) != set(_FIELDS):
        raise ValueError('unsupported model-proposed fields')
    n = len(trace['queries'])
    _charged_prefix(trace['queries'])
    if n >= MAX_SELECTS:
        raise ValueError('no SELECT attempt remains for reconstruction')
    for index in ('source_index', 'guard_index'):
        if type(fields[index]) is not int or not 0 <= fields[index] < n:
            raise ValueError('only pre-proposal own query witnesses are eligible')
    src, guard = (trace['queries'][fields[key]] for key in ('source_index', 'guard_index'))
    value = scalar_result(src)
    if not equal_scalar(value, trace['answer']):
        raise ValueError('witness query must reproduce the confirmed answer')
    if guard['error'] is not None or guard['truncated'] is not False:
        raise ValueError('a complete successful applicability observation is required')
    description = fields['description']
    if type(description) is not str or not description or len(description) > 512:
        raise ValueError('description cap')
    fragment = Fragment.from_query(fields['sql'], fields['params'])
    guard_fragment = Fragment.from_query(guard['sql'], guard['params'])
    request = fragment.compose(fields['outer_sql'], fields['outer_params'], alias='reused')
    return Proposal(fragment, guard_fragment, request,
                    canonical({k: guard[k] for k in ('columns', 'rows', 'truncated')}),
                    description, fields['source_index'], fields['guard_index'], value,
                    canonical(fields), n, _prefix_digest(trace, n))


def admit_verified(memory, proposal, trace, verification_index):
    """Trusted host admission after an actual charged read; model fields cannot self-approve."""
    _completed(trace)
    if memory.arm not in ('fragments', 'fragments_unchecked'):
        raise ValueError('only fragment memory after correct own feedback')
    if type(verification_index) is not int or verification_index != proposal.eligible_query_count:
        raise ValueError('verification must immediately follow the frozen witness prefix')
    if len(trace['queries']) != verification_index + 1:
        raise ValueError('one proposal and one verification per episode')
    _charged_prefix(trace['queries'])
    if _prefix_digest(trace, verification_index) != proposal.eligible_prefix_digest:
        raise ValueError('the pre-proposal own witness prefix changed')
    check = trace['queries'][verification_index]
    if (check['purpose'] != 'abstraction_reconstruction' or check.get('learning_check') is not True
            or check['sql'] != proposal.request.sql or check['params'] != proposal.request.parameters):
        raise ValueError('missing exact executed reconstruction request')
    if not equal_scalar(scalar_result(check), proposal.witnessed_value):
        raise ValueError('new relation failed observed-answer reconstruction')
    evidence = canonical({k: trace[k] for k in ('question', 'queries', 'answer', 'reward')})
    provenance = hashlib.sha256(evidence.encode()).hexdigest()
    entry = Entry(proposal.description, canonical(proposal.fragment.to_dict()),
                  canonical(proposal.guard.to_dict()), proposal.expected_guard, provenance)
    if len(canonical(entry.payload()).encode()) > MAX_MEMORY_BYTES:
        raise ValueError('entry byte cap')
    pending = [e for e in memory.entries if e.template_key() != entry.template_key()] + [entry]
    while (len(pending) > MAX_ENTRIES or len(canonical({'insights': memory.insights,
                                  'entries': [e.payload() for e in pending]}).encode()) > MAX_MEMORY_BYTES):
        pending.pop(0)
    event = {'kind': 'abstraction_reconstructed', 'evidence_digest': provenance,
                          'fragment_digest': proposal.fragment.digest,
                          'source_query_index': proposal.source_index,
                          'guard_query_index': proposal.guard_index,
                          'verification_query_index': verification_index,
                          'scope': 'one_own_observed_answer_only',
                          'new_sql_text': all(proposal.fragment.sql != r['sql']
                                              for r in trace['queries'][:verification_index])}
    # Construct every fallible field before mutating the library or journal.
    memory.entries = pending
    memory.events.append(event)
    while memory.peak_memory_bytes < memory.memory_bytes():
        memory.peak_memory_bytes = memory.memory_bytes()
    return entry
