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

**Silver processing** (`processing/silver/`) — fully built for every
Bronze table that currently exists. Typed/normalized transforms exist for
`students`, `class_id_lookup`, `enrollment_reports`, `course_enrollments`,
`report55_batch_attendance_summary`, `report55_session_attendance`, and
`class_session_attendance` (each single Bronze source, no reconciliation
needed), plus `courses` (see below — the one *reconciled* model, resolving
the 3-way catalogue overlap). Nothing is deferred here anymore; the next
Silver work is only for API jobs that don't exist yet (`sessions/`,
`teachers/`, `transactions/`, still reserved pending endpoint contracts).

**Courses/catalogue reconciliation — resolved 2026-09-23.** 3 competing
Bronze tables existed (`course_catalog`, `course_batch_merge`,
`course_catalogue_raw`) with different inclusion rules (Archived batches
in/out, ID-exclusion list vs. keyword filter). Project-owner decision,
implemented in `processing/silver/courses.py` / migration
`009_silver_courses.sql`:
1. Source is `bronze.course_batch_merge` only -- `course_catalog` and
   `course_catalogue_raw` are not inputs to `silver.courses`.
2. Archived batches are excluded (Active/Completed only), filtered in
   Silver even though the Bronze source itself keeps Archived for its own
   `Is_Latest_Batch` history computation.
3. Junk/test-batch filtering trusts `course_batch_merge`'s keyword rule
   (already applied at collection time); `course_catalog`'s fixed
   20-batch-id exclusion list is not reapplied.

`course_catalog` and `course_catalogue_raw` remain in Bronze, unreconciled,
per the original per-job READMEs -- only `silver.courses` had to pick one
source; Bronze keeps all three for anyone who needs the original scripts'
exact historical behavior.

**Attendance and enrollment — resolved 2026-09-23: kept separate, not
merged.** Both pairs measure genuinely different things at different
grains (confirmed by the project owner, matching this file's own earlier
recommendation):
- **Attendance**: `report55_batch_attendance_summary` (student-mark
  rollups from report_type=55, session numbered per `batch_id`) and
  `class_session_attendance` (pre-aggregated totals from
  `/organization/attendances`, session numbered per `master_batch_id`) are
  now both typed Silver models (`processing/silver/report55_batch_attendance_summary.py`,
  `processing/silver/report55_session_attendance.py`,
  `processing/silver/class_session_attendance.py`) -- no merge attempted.
- **Enrollment**: `silver.course_enrollments` (per-(student, class)
  attendance summary from the student sync) is now built alongside the
  pre-existing `silver.enrollment_reports` (historical per-enrollment-event
  log, different endpoint) -- kept as two separate models, not merged.

See migration `010_silver_attendance_enrollment.sql` for the full table
definitions.

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
  today by every job/transform. No separate policy folder needed.
- **Logging**: policy is "structured setup lives in `shared/logging/`" —
  already followed. No separate policy folder needed.
- **Monitoring**: health/job/database status already has a real
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

## Shared code (previously `shared/{utils,models}`)

Two more placeholder-only folders, missed by the original ADR-002 consolidation pass, found and
removed 2026-09-23: both held nothing but a one-paragraph "reserved" README, exactly like the
~20 folders ADR-002 already dealt with.

- **`shared/utils/`**: "reserved for genuinely cross-component utilities." Confirmed against the
  current code -- nothing imports `shared.utils` anywhere. Every normalization/formatting helper
  that exists today already lives with its actual owner (`api_scripts/common/`,
  `processing/silver/_normalize.py`) per this repo's own stated policy ("job-specific helpers
  stay with their owner"). Build a real `shared/utils/` only when a second component genuinely
  needs to import the same helper a third one already has -- not before.
- **`shared/models/`**: "reserved for models used by more than one platform component." Confirmed
  against the current code -- nothing imports `shared.models` anywhere; every model in this
  codebase (`api_scripts/common/models.py`, `shared/config/settings.py`) already lives with its
  one actual consumer. Same rule: build it only when a second component genuinely needs one.

## Reserved API jobs (unchanged, still tracked in `api_scripts/`, not here)

`api_scripts/sessions/`, `api_scripts/teachers/`, `api_scripts/transactions/`
remain as their own reserved folders (not folded into this file) because
they follow the job-registry pattern every other `api_scripts/` folder uses,
and each needs its own redacted endpoint contract before it can be built —
see their individual READMEs and `documentation/API_JOBS.md`.
