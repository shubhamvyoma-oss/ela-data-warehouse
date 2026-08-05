# Attendance collector

Collects Edmingle attendance report type `55` one IST calendar day at a time from
`GET /report/csv`.

The request includes `apikey`, uppercase `ORGID`, `organization_id`, start/end epoch seconds,
and `response_type=1`. The response contract is a `data` list. Each raw row is keyed from the
student, attendance, batch, and class identifiers and written without transformation.

The collector uses the `daily` checkpoint partition and advances `last_completed_date` only
after the day's Bronze transaction commits. `ATTENDANCE_START_DATE` and `ATTENDANCE_END_DATE`
support controlled backfills; otherwise the collector resumes its checkpoint through yesterday.
