# Roadmap — deferred and reserved work

This file replaces ~20 folders that previously existed purely to hold a
single "reserved for future work" README each (`processing/{bronze,quality,
replay,validation}`, the entire `warehouse/` tree, `platform/{alerting,
configuration,logging,monitoring,security}`, the entire `dashboards/` tree,
`services/{monitoring,notification}`, `docker/{monitoring,nginx}`). None of
them contained any code. Consolidating their content here (see ADR-002)
makes the actual size of the working codebase honest: everything with real
code lives in a real folder; everything else is a line item below.

Nothing in this file is a commitment or a timeline — it's a record of
documented-but-unbuilt responsibilities, kept in one place instead of
scattered across a folder tree, so the repo's structure reflects what
actually exists.

## Data layers

**Silver processing** (`processing/silver/`) — partially built. Typed/
normalized transforms exist today for `students`, `class_id_lookup`, and
`enrollment_reports` (single Bronze source each, no reconciliation needed).
Still deferred, pending a business decision on which source is authoritative:
- **Courses/catalogue**: 3 competing Bronze tables (`course_catalog`,
  `course_batch_merge`, `course_catalogue_raw`) with different inclusion
  rules (Archived batches in/out, ID-exclusion list vs. keyword filter).
- **Attendance**: 2 sources measuring different things (`report55_batch_attendance_summary`
  + `report55_session_attendance` vs. `class_session_attendance`) — likely
  stay as separate Silver entities rather than merge, but confirm.
- **Enrollment**: `course_enrollments` (per-class, from student sync) vs.
  `enrollment_reports` (historical event log, different endpoint).

**Gold processing** (`processing/gold/`, kept as an empty folder — the next
one to fill in). Needs, before any code is written: approved KPI
definitions and formulas (e.g. what "retention" or "active student" means),
target grains/dimensions, refresh expectations, and reconciliation tests.
Consumed by whatever dashboard tool is chosen (Power BI was assumed in
earlier planning docs, not yet confirmed).

**Data quality / validation / replay** (previously `processing/quality/`,
`processing/validation/`, `processing/replay/`, plus a `processing/bronze/`
folder whose only described responsibility — "promotion orchestration" — had
no content beyond what's already stated in `processing/README.md`). Reserved
for: reusable schema/type/business-rule validators, quality rules and
reconciliation evidence, and controlled reprocessing from Bronze/quarantine
data. Build these as part of implementing the first real Silver/Gold model
that needs them, not speculatively ahead of time.

**Bronze/Silver/Gold contracts** (previously the entire `warehouse/` tree —
`warehouse/bronze`, `warehouse/silver`, `warehouse/gold`). This was meant to
document the *shape* of each layer's data separately from the code that
produces it. In practice the distinction added a parallel folder tree with
no content of its own beyond restating what the corresponding `processing/`
README already said. Data contracts now live as comments/migrations next to
the tables themselves (`database/migrations/`) plus this file — no separate
contracts-only folder.

## Platform policy (previously `platform/{alerting,configuration,logging,monitoring,security}`)

These were policy statements, not code:
- **Alerting**: no framework exists (an earlier one in the webhook service
  was removed as confirmed dead code — see `services/edmingle_webhook/docs/architecture.md`).
  Build real alerting only when there's an actual delivery channel decision
  (email/Slack/Teams) and failure paths to wire it into.
- **Configuration**: policy already effectively is "runtime parsing lives in
  `shared/config/`, secrets never go in PostgreSQL config values" — followed
  today by every collector/transform. No separate policy folder needed.
- **Logging**: policy is "structured setup lives in `shared/logging/`" —
  already followed. No separate policy folder needed.
- **Monitoring**: health/collector/database status already has a real
  `monitoring` schema (see `database/migrations/003_naming_and_platform_schemas.sql`).
  An independently deployable monitoring *service* reading that schema is
  still unbuilt (see Services below).
- **Security**: "warehouse-wide access, secret-handling, least-privilege" —
  policy already followed via env-var-only secrets and the
  `system.api_credentials` no-secret-values constraint. No code gap here to
  track separately.

## Services (previously `services/{monitoring,notification}`)

- **Monitoring service**: an independently deployable service reading the
  `monitoring` schema. Not built. The schema itself already exists and is
  usable via direct SQL today.
- **Notification service**: approved email/Slack/Teams/escalation delivery,
  destinations kept in runtime secret storage. Not built. `api_scripts/attendance`
  and the legacy-ported jobs' own email alerting (where it existed in the
  original scripts) was intentionally not carried into this warehouse's
  ingestion layer — see each job's README for what was simplified away and why.

## Dashboards (previously `dashboards/{backend,frontend}`)

Not built. Needs: a confirmed tool decision (Power BI assumed, not
confirmed), and a Gold layer to read from (see above). The backend, if
built, must be a controlled, authenticated read API — never expose Bronze
payloads or database credentials directly to a frontend.

## Docker (previously `docker/{monitoring,nginx}`)

- **Monitoring containers**: deferred until there's an actual monitoring
  service (see above) and a server-capacity review.
- **Nginx**: the current production reverse-proxy (Caddy) and webhook
  routing are outside this repository's scope — this folder was reserved
  for a dashboard/service ingress that doesn't exist yet.

## Reserved API jobs (unchanged, still tracked in `api_scripts/`, not here)

`api_scripts/sessions/`, `api_scripts/teachers/`, `api_scripts/transactions/`
remain as their own reserved folders (not folded into this file) because
they follow the job-registry pattern every other `api_scripts/` folder uses,
and each needs its own redacted endpoint contract before it can be built —
see their individual READMEs and `documentation/API_JOBS.md`.
