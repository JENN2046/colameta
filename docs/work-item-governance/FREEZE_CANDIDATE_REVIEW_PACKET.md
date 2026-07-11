# Work Item Governance freeze-candidate review packet

Review candidate: contracts and implementation for Phases 0–5, reviewed and
released one phase at a time.

Frozen decisions:

- aggregate root is `work_item_id`;
- a Work Item owns many Task Versions and Execution Attempts;
- Ledger location/classification is
  `.colameta/ledger/work-items.sqlite3` / `project_local_durable`;
- creation and legacy import require explicit preview/apply;
- reads, smoke checks, ordinary tools and executor runs never auto-create;
- historical relationships are never inferred or automatically backfilled;
- Commander stays unified but uses three owned projections;
- Runner, connectors, product submission and stable promotion cannot decide
  lifecycle state;
- existing unbound flows remain compatible through the deprecation window;
- stable promotion requires separate exact-commit authorization.

Reviewer checks for every phase:

1. inspect Schema/DB version and the exact diff;
2. run focused unit, SQLite integration, compatibility, architecture and
   security tests;
3. run full `pytest` and `ruff`;
4. verify the four pre-existing `AGENTS*` hashes and exclude them from staging;
5. create a Backup-API snapshot and validate a staged restore with
   `integrity_check` when a Ledger exists;
6. record phase-specific rollback instructions and unresolved risks;
7. do not promote stable runtime without a new exact-head authorization.

Known compatibility debt: legacy `mcp_server.py` and `core_orchestrator.py`
remain available during staged extraction. Their pre-existing workflows are not
silently reclassified as Work Items. Removal is prohibited until unbound and
legacy usage is measured and a distinct deprecation cycle is approved.

## R1 authority and lifecycle closeout

The external Phase 0–5 review identified four authority blockers and three
integration/safety gaps. Freeze review now additionally requires evidence for:

- trusted Principal injection and policy-derived Actor/authority;
- the `submitted -> in_delivery` returned-for-revision Gate;
- an immutable, digest-verified Acceptance Evidence Manifest;
- current-version/nonterminal runtime Attempt dispatch and explicit historical
  binding;
- exclusive restore maintenance lock plus database-generation CAS;
- production Commander/App Submission/Stable Promotion composition paths;
- the named negative tests in `R1_AUTHORITY_AND_LIFECYCLE_CLOSEOUT.md`.

The machine-readable execution record is `R1_CLOSEOUT_RECEIPT.json`. Its
existence is evidence, not release or stable promotion authorization; those
remain separately reviewed exact-source actions.
