# Edmingle API layer

Every confirmed Edmingle API job owns a dedicated folder. Collectors contain only source
collection logic; shared HTTP, retry, checkpoint, Bronze, and audit behavior lives in `common/`.

| Collector | Folder | Schedule template | State partition |
| --- | --- | --- | --- |
| Attendance | `attendance/` | daily | `daily` |
| Course catalogue | `course_catalogue/` | weekly | `default` |
| Master batches | `master_batches/` | weekly | `default` |
| Enrollments | `enrollments/` | weekly | `default` |

Run one job with:

```bash
python warehouse_cli.py collect attendance
```

The folders `students/`, `teachers/`, `sessions/`, and `transactions/` are intentionally
reserved. Their source endpoints were not present in the supplied scripts, so their collectors
will be implemented only after redacted request and response contracts are provided.

All collectors store the untouched source record in `bronze.edmingle_api_records`, attach only
request context needed to understand it, and checkpoint in the same transaction as the Bronze
write. They never create CSV extracts or perform business transformations.
