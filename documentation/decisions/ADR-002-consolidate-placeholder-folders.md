# ADR-002: Consolidate placeholder-only folders into ROADMAP.md

- Status: Accepted
- Date: 2026-09-16
- Supersedes: none (amends the folder layout established by ADR-001; does
  not reverse ADR-001's real decisions, e.g. the webhook compatibility
  boundary and the six real schemas remain unchanged)

## Context

ADR-001 established `processing/`, `warehouse/`, `platform/`, `dashboards/`,
`services/`, and `docker/` as top-level ownership boundaries, each further
subdivided (e.g. `processing/bronze`, `warehouse/bronze`, `platform/monitoring`,
`services/monitoring`). By design, most of these subdivisions were deferred:
each contained exactly one README stating "reserved for future work," with
zero code.

After the project owner reported the repository felt confusingly large and
scattered, an audit (full verbatim content of every placeholder README, see
session record) found: the `processing/` vs `warehouse/` split (executable
code vs. data contracts) and the `platform/` vs `services/` split (policy vs.
runtime) were genuine, consistently-applied, documented patterns — not
accidental duplication. But with zero code in either half of most of these
pairs, the split added ~20 folders of pure navigation overhead for no
present benefit. One file, `platform/preflight.py`, turned out to be real,
working code sitting inside an otherwise-placeholder tree, and was not
referenced by anything else in the codebase.

The project owner explicitly authorized breaking from ADR-001's folder
conventions in service of a simpler structure.

## Decision

- Consolidate every placeholder-only folder's content into a single
  root-level `ROADMAP.md`, replacing ~20 folders with one file.
- Delete: `processing/{bronze,quality,replay,validation}`, the entire
  `warehouse/` tree, `platform/{alerting,configuration,logging,monitoring,security}`,
  the entire `dashboards/` tree, `services/{monitoring,notification}`,
  `docker/{monitoring,nginx}`.
- Keep `processing/silver/` (now has real code) and `processing/gold/` (kept
  empty, as the next real target once KPI definitions are approved).
- Move `platform/preflight.py` to `shared/preflight_cli.py` (it's a thin CLI
  wrapper around `shared/preflight.py` and doesn't need its own top-level
  ownership folder); confirmed via full-repo grep that nothing imports or
  invokes it under its old path.
- `api_scripts/{sessions,teachers,transactions}` are explicitly NOT folded
  into ROADMAP.md — they follow a different, already-working pattern (the
  job-registry placeholder used by every other `api_scripts/` folder) and
  are already adequately documented in `documentation/API_JOBS.md`.

## Consequences

- Folder count drops from ~35 top-level-and-nested directories to ~15,
  matching what actually has code in it.
- Anyone extending Silver/Gold, monitoring, notifications, or dashboards now
  reads one file (`ROADMAP.md`) instead of hunting across a dozen scattered
  READMEs.
- If `processing/`/`warehouse/` or `platform/`/`services/` splits are needed
  again in the future (e.g. once Gold has real code and a genuinely distinct
  contract-definition need emerges), re-introduce them deliberately with
  actual content, not as an empty placeholder ahead of any implementation.
