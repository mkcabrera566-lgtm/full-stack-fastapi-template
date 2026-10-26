# Ticket management V1 implementation plan

> Execute inline using the planning, test-driven-development, and verification skills. The user's request authorizes direct implementation on a feature branch.

**Goal:** Add authenticated ticket CRUD without changing existing authentication, Items, frontend, or stored data.

**Architecture:** Extend the existing SQLModel models and API router. Reuse JWT authentication and ownership rules. Add an additive Alembic revision and isolated SQLite tests using the real API and authentication dependencies.

**Tech stack:** Repository-locked Python 3.14, uv, FastAPI, Pydantic, SQLModel, Alembic, pytest.

**Spec:** User request in this chat; concrete business defaults below are implementation decisions.

## Constraints and decisions

- Branch: `codex/ticket-management-v1`; work in the current clean checkout.
- No Docker, AI, frontend work, new dependencies, or connections/migrations against an existing database.
- UUID IDs; required trimmed title (1–255), required trimmed description (1–10000); priority `low`, `medium` (default), `high`, `urgent`.
- Server owns `id`, `owner_id`, `created_at`, and initial `open` status. Reject unknown input fields.
- Status graph: `open -> in_progress -> resolved -> closed`; `resolved -> in_progress` permits reopening. Same-status PATCH is idempotent; all other transitions return 409, including for administrators.
- Ordinary users access only their own tickets; administrators access all. Missing ticket: 404; another user's ticket: 403; invalid input: 422.
- List uses `{data, count}`, descending creation time and UUID tie-break, `skip >= 0`, `1 <= limit <= 100`.
- Existing PostgreSQL tests require explicit opt-in and a dedicated test URL; default pytest runs use only in-memory SQLite. Keep original tests and cleanup code behind the opt-in guard.

## Review focus

- PATCH distinguishes omitted fields from explicit null and rejects immutable fields.
- Ownership filters apply to both list data and count; writes cannot reassign ownership.
- Invalid transitions must not partially persist other edits; PostgreSQL row locks serialize concurrent writes.
- Deleting a user preserves existing behavior and cascades their tickets.
- Migration and model constraints must agree; SQLite is not evidence of PostgreSQL compatibility.

## Tasks

- [x] 1. Write API and model behavior tests first, establish safe test configuration, and observe missing-ticket failures.
- [x] 2. Implement Ticket schemas, enums, relationship, ownership-aware routes, and state transitions. Run isolated tests.
- [x] 3. Add the migration, verify its upgrade/downgrade against an ephemeral database and compile PostgreSQL SQL offline.
- [x] 4. Run default pytest and repository static checks, review changes, and document Windows commands, results, learning pointers, and database limitations.

## Verification and review record

- Observed ticket lifecycle fail with 404 before adding the routes; observed missing migration and revision-head failures before adding the revision.
- Reproduced backend-only missing-frontend failure; added a regression and mounted assets conditionally.
- Real authentication against SQLite exposed string UUID lookup failure. Added malformed/missing-user subject regressions before parsing UUID in the original authentication dependency.
- Final default suite: 98 passed, 58 PostgreSQL integration tests skipped, one upstream TestClient deprecation warning.
- Ruff checks/format, mypy (21 files), ty, new migration checks, workflow YAML parse and git whitespace checks pass.
- Windows portable coverage entrypoint: 98 passed; ticket routes 100% statement coverage, overall backend 69%. Offline run does not satisfy the existing 90% whole-backend coverage gate; original PostgreSQL tests remain unexecuted.
- Independent read-only review found one Important CI integration issue: the old test script would skip its selected tests after opt-in protection. Fixed with portable suite orchestration, explicit disposable CI test URL, and appended coverage. Three runner regressions observed RED then GREEN.
- Review's minor mode-assumption issue was addressed with the same integration fix: the connection-prohibition test skips in explicitly selected PostgreSQL mode.
- Coverage excludes Alembic scripts, whose revision discovery imports historical non-package modules; migration correctness remains covered by explicit schema/SQL tests. Existing CI coverage threshold is unchanged.
- No existing database connection, online migration, Docker invocation, merge or push performed. Changes remain on the requested feature branch.
