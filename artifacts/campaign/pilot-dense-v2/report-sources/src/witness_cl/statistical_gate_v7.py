"""A bounded, model-free promotion gate for fresh paired rewards.

This is a conventional test-supermartingale, not an alignment certificate.
Every started audit spends alpha permanently. Policies and scope are frozen
before fresh observations; the caller is responsible for their actual execution,
reward provenance, stationary scope sampling and durable non-rollback storage.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import uuid


_MAX_AUDITS = 4096
_MAX_PAIRS = 64


def _text(value, name, limit=256):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} must be a nonempty bounded string')
    return value


def _reward(value):
    if type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value):
        raise ValueError('rewards must be finite Python int/float values in [0,1]')
    return float(value) if value else 0.0


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


@dataclass(frozen=True)
class AuditToken:
    gate_id: str
    audit_index: int
    candidate_digest: str
    incumbent_digest: str
    scope: str


@dataclass(frozen=True)
class GateResult:
    status: str  # collecting, accepted, inconclusive
    audit_index: int
    candidate_digest: str
    incumbent_digest: str
    scope: str
    pairs: int
    allocated_alpha: float
    allocated_alpha_exact: str
    log_wealth: float
    log_threshold: float
    journal_hash: str


@dataclass
class _Audit:
    token: AuditToken
    alpha: Fraction
    log_threshold: float
    status: str = 'collecting'
    pairs: int = 0
    log_wealth: float = 0.0
    capital: Fraction = Fraction(1)


class PairedBettingGate:
    """One active audit, fixed bet 1/2, no tolerance, and no alpha refunds.

    `start` freezes opaque policy digests and a public scope. `observe_pair`
    consumes globally unique sample IDs. Accepted audits certify positive scoped
    mean difference only under the documented conditional sampling assumptions.
    A terminal audit cannot receive more samples; start a new, charged audit.
    """

    def __init__(self, alpha_total=0.05, *, max_pairs=64, max_audits=1024):
        if (type(alpha_total) not in (int, float) or not 0 < alpha_total < 1
                or not math.isfinite(alpha_total)):
            raise ValueError('alpha_total must be a finite number strictly between 0 and 1')
        if type(max_pairs) is not int or not 1 <= max_pairs <= _MAX_PAIRS:
            raise ValueError('max_pairs must be an integer from 1 through 64')
        if type(max_audits) is not int or not 1 <= max_audits <= _MAX_AUDITS:
            raise ValueError('max_audits must be an integer from 1 through 4096')
        self._alpha_total = float(alpha_total)
        self._alpha_exact = Fraction.from_float(self._alpha_total)
        if not float(self._alpha_exact / (max_audits * (max_audits + 1))):
            raise ValueError('last configured alpha allocation would underflow float reporting')
        self._max_pairs, self._max_audits = max_pairs, max_audits
        self._gate_id = uuid.uuid4().hex
        self._audits: list[_Audit] = []
        self._used_samples: set[str] = set()
        self._events: list[dict] = []
        self._journal_hash = self._initial_hash()

    @property
    def alpha_total(self):
        return self._alpha_total

    @property
    def max_pairs(self):
        return self._max_pairs

    @property
    def max_audits(self):
        return self._max_audits

    @property
    def started_audits(self):
        return len(self._audits)

    @property
    def allocated_alpha_total_exact(self):
        n = self.started_audits
        return self._alpha_exact * n / (n + 1)

    @property
    def allocated_alpha_total(self):
        return float(self.allocated_alpha_total_exact)

    @property
    def pairs_seen(self):
        return len(self._used_samples)

    @property
    def journal_hash(self):
        return self._journal_hash

    @property
    def active_token(self):
        if self._audits and self._audits[-1].status == 'collecting':
            return self._audits[-1].token
        return None

    def _config(self):
        return dict(alpha_total=self.alpha_total, max_pairs=self.max_pairs,
                    max_audits=self.max_audits)

    def _initial_hash(self):
        return hashlib.sha256(_canonical(dict(format='witness-cl-paired-gate-v7',
                                              gate_id=self._gate_id, config=self._config()))).hexdigest()

    def _prepared_hash(self, event):
        return hashlib.sha256(bytes.fromhex(self._journal_hash) + _canonical(event)).hexdigest()

    def _commit_event(self, event, next_hash):
        self._events.append(event)
        self._journal_hash = next_hash

    def _record(self, token, *, active=False):
        if (type(token) is not AuditToken or token.gate_id != self._gate_id
                or type(token.audit_index) is not int
                or not 1 <= token.audit_index <= self.started_audits):
            raise ValueError('foreign or invalid audit token')
        record = self._audits[token.audit_index - 1]
        if token != record.token:
            raise ValueError('candidate, incumbent or scope differs from frozen token')
        if active and (record is not self._audits[-1] or record.status != 'collecting'):
            raise ValueError('stale or completed audit token')
        return record

    def start(self, candidate_digest: str, incumbent_digest: str, scope: str) -> AuditToken:
        candidate_digest = _text(candidate_digest, 'candidate_digest')
        incumbent_digest = _text(incumbent_digest, 'incumbent_digest')
        scope = _text(scope, 'scope')
        if self.active_token is not None:
            raise RuntimeError('finish the active audit before starting another')
        if self.started_audits >= self.max_audits:
            raise RuntimeError('configured audit cap exhausted; no automatic reset is permitted')
        j = self.started_audits + 1
        allocation = self._alpha_exact / (j * (j + 1))
        token = AuditToken(self._gate_id, j, candidate_digest, incumbent_digest, scope)
        record = _Audit(token, allocation, -math.log(float(allocation)))
        event = dict(kind='start', audit_index=j, candidate_digest=candidate_digest,
                     incumbent_digest=incumbent_digest, scope=scope,
                     allocated_alpha_exact=str(allocation))
        next_hash = self._prepared_hash(event)
        self._audits.append(record)
        self._commit_event(event, next_hash)
        return token

    def result(self, token: AuditToken) -> GateResult:
        r = self._record(token)
        return GateResult(r.status, token.audit_index, token.candidate_digest,
                          token.incumbent_digest, token.scope, r.pairs, float(r.alpha),
                          str(r.alpha), r.log_wealth, r.log_threshold, self.journal_hash)

    def observe_pair(self, token: AuditToken, candidate_reward, incumbent_reward,
                     sample_id: str, *, candidate_digest=None, incumbent_digest=None,
                     scope=None) -> GateResult:
        r = self._record(token, active=True)
        for name, given in (('candidate_digest', candidate_digest),
                            ('incumbent_digest', incumbent_digest), ('scope', scope)):
            if given is not None and _text(given, name) != getattr(token, name):
                raise ValueError(f'{name} differs from frozen audit identity')
        sample_id = _text(sample_id, 'sample_id', limit=512)
        if sample_id in self._used_samples:
            raise ValueError('sample_id was already consumed by this gate')
        candidate, incumbent = _reward(candidate_reward), _reward(incumbent_reward)
        pairs = r.pairs + 1
        log_wealth = r.log_wealth + math.log1p(0.5 * (candidate - incumbent))
        # Exact arithmetic on the represented rewards prevents upward floating
        # rounding from authorizing a crossing. The public statistic is the
        # specified sumlog1p; the extra check can only make acceptance stricter.
        factor = 1 + (Fraction.from_float(candidate) - Fraction.from_float(incumbent)) / 2
        capital = r.capital * factor
        accepted = log_wealth >= r.log_threshold and capital * r.alpha >= 1
        status = 'accepted' if accepted else ('inconclusive' if pairs == self.max_pairs else 'collecting')
        event = dict(kind='pair', audit_index=token.audit_index, sample_id=sample_id,
                     candidate_reward=candidate, incumbent_reward=incumbent, status=status)
        next_hash = self._prepared_hash(event)
        r.pairs, r.log_wealth, r.capital, r.status = pairs, log_wealth, capital, status
        self._used_samples.add(sample_id)
        self._commit_event(event, next_hash)
        return self.result(token)

    def finish_inconclusive(self, token: AuditToken) -> GateResult:
        r = self._record(token, active=True)
        event = dict(kind='finish_inconclusive', audit_index=token.audit_index)
        next_hash = self._prepared_hash(event)
        r.status = 'inconclusive'
        self._commit_event(event, next_hash)
        return self.result(token)

    def snapshot(self) -> dict:
        """JSON-compatible trusted checkpoint; this method performs no I/O."""
        return dict(format_version=1, gate_id=self._gate_id, config=self._config(),
                    events=[dict(event) for event in self._events],
                    journal_hash=self.journal_hash, started_audits=self.started_audits,
                    allocated_alpha_total_exact=str(self.allocated_alpha_total_exact))

    @classmethod
    def from_snapshot(cls, snapshot: dict, *, minimum_started_audits=0,
                      expected_journal_hash=None) -> PairedBettingGate:
        """Validate and replay a trusted journal without resetting error spending.

        The optional counter/head must come from trusted external state to reject
        an older, internally consistent checkpoint. An unkeyed hash alone cannot
        authenticate provenance or prevent wholesale rewriting/rollback.
        """
        keys = {'format_version', 'gate_id', 'config', 'events', 'journal_hash',
                'started_audits', 'allocated_alpha_total_exact'}
        if (type(snapshot) is not dict or set(snapshot) != keys
                or type(snapshot['format_version']) is not int or snapshot['format_version'] != 1):
            raise ValueError('invalid journal checkpoint format')
        if type(minimum_started_audits) is not int or minimum_started_audits < 0:
            raise ValueError('minimum_started_audits must be a nonnegative integer')
        count = snapshot['started_audits']
        if type(count) is not int or count < minimum_started_audits:
            raise ValueError('checkpoint counter is invalid or older than trusted minimum')
        if expected_journal_hash is not None and snapshot['journal_hash'] != expected_journal_hash:
            raise ValueError('checkpoint does not match trusted journal head')
        config = snapshot['config']
        if type(config) is not dict or set(config) != {'alpha_total', 'max_pairs', 'max_audits'}:
            raise ValueError('invalid journal configuration')
        restored = cls(**config)
        restored._gate_id = _text(snapshot['gate_id'], 'gate_id')
        restored._journal_hash = restored._initial_hash()
        events = snapshot['events']
        if (type(events) is not list or len(events) > restored.max_audits * (restored.max_pairs + 2)
                or count > restored.max_audits):
            raise ValueError('journal exceeds configured limits')
        try:
            for event in events:
                if type(event) is not dict or type(event.get('audit_index')) is not int:
                    raise ValueError('invalid journal event')
                if event.get('kind') == 'start':
                    restored.start(event['candidate_digest'], event['incumbent_digest'], event['scope'])
                elif event.get('kind') == 'pair':
                    restored.observe_pair(restored.active_token, event['candidate_reward'],
                                          event['incumbent_reward'], event['sample_id'])
                elif event.get('kind') == 'finish_inconclusive':
                    restored.finish_inconclusive(restored.active_token)
                else:
                    raise ValueError('unknown journal event')
                if restored._events[-1] != event:
                    raise ValueError('journal event does not match validated replay')
        except (KeyError, TypeError, RuntimeError) as exc:
            raise ValueError('invalid journal event sequence') from exc
        if (restored.started_audits != count or restored.journal_hash != snapshot['journal_hash']
                or str(restored.allocated_alpha_total_exact) != snapshot['allocated_alpha_total_exact']):
            raise ValueError('journal checkpoint totals or hash do not match replay')
        return restored


def constant_difference_min_pairs(difference, allocated_alpha, *, cap=64):
    """Exact zero-variance power diagnostic, not a stochastic sample-size bound.

    Return the first n<=cap where (1+d/2)^n reaches 1/alpha, or None.
    Passing the gate can require an extra pair at a floating reporting boundary.
    """
    if (type(difference) not in (int, float) or not -1 <= difference <= 1
            or not math.isfinite(difference)):
        raise ValueError('difference must be finite and in [-1,1]')
    if (type(allocated_alpha) not in (int, float) or not 0 < allocated_alpha < 1
            or not math.isfinite(allocated_alpha)):
        raise ValueError('allocated_alpha must be strictly between 0 and 1')
    if type(cap) is not int or not 1 <= cap <= 64:
        raise ValueError('cap must be from 1 through 64')
    factor = 1 + Fraction.from_float(float(difference)) / 2
    allocation = Fraction.from_float(float(allocated_alpha))
    capital = Fraction(1)
    for n in range(1, cap + 1):
        capital *= factor
        if capital * allocation >= 1:
            return n
    return None
