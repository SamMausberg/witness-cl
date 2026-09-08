# Safety and retention boundaries

The shipped DSL evaluates arithmetic only. It cannot call a shell, access files,
make network requests, modify permissions, execute an arbitrary string, or change
its own code. A parser rejects extra fields and unknown operations. These are
specific implementation restrictions, not a comprehensive security proof.

Environment feedback is a trusted input to the learning theorem. User text,
retrieved documents, model confidence and self-critique are not authoritative
reward. A real deployment needs authenticated tool results, provenance and
cross-checks. Prompt injection can contaminate memory long after the original
text disappears; typed records reduce an attack surface but do not establish
semantic correctness. Freeze the safety policy and permission checks outside
all learned prompts, adapters and skills.

Scope and version keys must come from public authenticated metadata. An LLM's
belief that the task is the same is not proof of sameness. Hidden drift can cause
a wrong certified action before feedback detects it, as the release demonstrates.
For irreversible or high-stakes actions, require independent current validation
or a safe abstention path; post-hoc quarantine is insufficient.

Paired audits run only in authorized, non-effectful simulators or isolated test
environments. A higher average reward can still include a harmful minority of
cases, so safety constraints need separate validation and enforcement. Never
interpret an e-process for benchmark reward as a general AI safety certificate.

A hash-linked ledger detects a partial edit when the expected chain head is held
outside the log. It does not authenticate the source or stop an attacker who can
rewrite the entire log and trusted head. The reference is single-writer and is
not crash-recovering distributed storage. Model-service credentials come only
from a runtime environment variable and are not bundled or logged.

No-forgetting is not a license to retain personal data forever. Support authorized
deletion and retention limits. Delete or invalidate certificates, learned entries
and derived adapters depending on erased evidence; rebuild surviving state only
from still-authorized records. Deletion is an explicit exception to retention
and is not implemented as a complete privacy/unlearning mechanism here.
