# Security scope

Witness-CL is a research system, not a production isolation or alignment system.
Its SQL executor rejects writes, attachments, extensions, file functions and
unapproved physical or virtual relations. It bounds queries, result sizes and
execution work. The local model server uses loopback networking and a temporary
authentication file; the model receives no shell or network tools.

These controls depend on Python, SQLite, the host process and the pinned model
backend. Lean verifies the stated mathematical contracts, not these complete
implementations. The current tests include a SQLite 3.53.1 compatibility repair:
the JSON table-valued functions can be available before appearing in the module
inventory. Their documented names are explicitly denied as well.

Do not commit model-server keys, provider credentials, private prompts or real
user databases. Runtime keys and downloaded weights belong outside the checkout.
Report a security issue to the repository maintainer through GitHub's private
vulnerability reporting when available; include a minimal reproducer using
synthetic data, the affected revision and the actual SQLite/backend versions.
