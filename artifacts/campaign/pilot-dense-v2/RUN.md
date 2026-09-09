# Frozen 32-stream pilot

The pilot contains seeds 101100–101131, all three independently learning arms,
and 17,664 assigned episodes. The first four streams were already running when
the author requested the extension; the manifest records 29 completed episode
files at that amendment. All four are retained. The remaining 28 streams froze
before any of their model calls. The two blocks have identical learner,
generator, model, decoding and execution-limit identities.

The dense BF16 model server is on localhost port 18086. Its model/backend hashes
and launch identity are in `../runtime-dense/server.json`. The first block is
`../dense-v2/development`; the second is `additional-28`. The running supervisor
waits for the existing first-block sequence, verifies its complete replay audit,
then runs the entire second block, replay and census. Its last command creates
the complete descriptive pilot report. There are no auxiliary or confirmation
commands in `collection-plan.json`.

Use these files for status, without interpreting partial outcome estimates:

- `../dense-v2/sequence-status.json` and `../dense-v2/development/manifest.json`
- `supervisor/status.json` and `supervisor/commands/`
- `additional-28/manifest.json` after that block starts
- `report/report.json` and `report/REPORT.md`

The supervisor was launched with the copied control/reporting closure:

```bash
.venv/bin/python artifacts/campaign/pilot-dense-v2/report-sources/tools/campaign_supervisor.py \
  --out artifacts/campaign/pilot-dense-v2/supervisor \
  --plan artifacts/campaign/pilot-dense-v2/collection-plan.json
```

Do not start another supervisor while its recorded process is alive. Do not
modify either study's `sources` directory or `report-sources`. Complete commands
are not repeated on a normal supervisor restart. Failed or uncertain commands
stop and require inspection of their original receipts; there is no automatic
replacement call or stream. The serving process must remain available while
this frozen pilot runs.

Once both blocks are complete, the reporter independently regenerates the full
mechanism census and exports all 96 stream/arm summaries and all 6,144 paired old
observations. Zero-event streams remain in the denominator. Admission, later
corroboration, eligibility, retrieval, execution and qualifying chains have
separate counts. Fixed-program interventions do not claim agent-deletion effects.

Collection completion requires scientific review before proceeding. Report the
pilot's actual result, including a zero census or ceiling. Retention variance
uses 32 stream differences, not 2,048 independent old instances per arm. The old
419-stream sizing scenario and out-of-distribution confirmation template are
held. Choose and freeze a calibrated target population and feasible analysis
before any confirmation; see `docs/campaign/PILOT_DISTRIBUTION.md` from the repo
root. Final manuscript claims and the authorized push to `main` follow the
completed evidence and review, not an unfinished or selectively reported pilot.
