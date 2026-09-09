# Version 7 research execution boundaries

The user's continuing research request authorizes this local implementation,
small bounded numerical online training, proofs, tests, paper and private-repo
updates. The separate request to remove the background automation remains in
force: no automation is created or resumed.

This phase uses synthetic local SQLite tables with bounded values, row counts
and execution work. Database setup creates an ephemeral in-memory fixture; after
setup, query-only mode and a restrictive authorizer permit only fixed reads and
approved aggregate functions. Learners receive immutable query results and
subsequent scalar ordinary feedback. They cannot execute SQL or change tools,
authority, filenames, reward code, routing, environment state or another policy.
This is an application boundary for trusted reference code, not hostile-process
isolation or a defense against arbitrary Python executing in the same process.

The mutable learner fits small scalar regression weights after its own ordinary
feedback. Earlier v6 ranker weights remain frozen and archived; there is no new
LLM training, model inference, networked tool action, paid compute or deployment.
The source grammar and caps are explicit priors. Installed models are immutable
feature/weight tuples. The evaluator owns hidden report definitions and gold SQL.
Audit examples never train numerical proposals; all later candidates face fresh
audit streams. Seeds and labels are not available through the learner API.

The statistical error allocation concerns stationary scoped mean reward. Fixed
public report dispatch separately preserves untouched policies by identity.
Neither property is a guarantee of alignment, broad capability retention,
arbitrary drift tolerance or unconstrained lifelong learning. The finite payload
bounds hold for the bounded experiment; they do not prove constant-memory
learning over unlimited new reports. Query budgets include actual post-setup
SELECT attempts, with database construction and measured CPU costs disclosed
separately.

Completed experimental directories are immutable. Development results may expose
bugs, but any correction must be documented before the final freeze; untouched
evaluation seeds cannot be used to select algorithm or protocol. Historical
papers and raw v4/v5/v6 artifacts remain preserved. Remote operations are limited
to the user-requested private research repository and verification of its CI.
