# Attendance data

Groups the 3 jobs ported from the legacy "Attendance data" folder's 3-stage
pipeline (course catalogue -> class ID resolution -> per-session
attendance). These jobs have a real run-order dependency:

1. `attendance_data.catalogue` -> `bronze.course_catalog`
2. `attendance_data.class_id_lookup` -> `bronze.class_id_lookup` (reads `bronze.course_catalog`)
3. `attendance_data.class_session_attendance` -> `bronze.class_session_attendance` (reads `bronze.class_id_lookup`)

See each subfolder's own README for endpoint/config/table detail. This is
one of six top-level folders under `api_scripts/`, each mapping 1:1 to one
of the original legacy script folders the extract/transform logic was
ported from -- see `documentation/API_JOBS.md` for the full picture.
