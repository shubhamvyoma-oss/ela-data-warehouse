# ELA MIS datasets

Groups the 2 jobs ported from the legacy "ela_mis_datasets" folder's single
source script (`edmingle_student_course_sync.py`), split into two jobs
(one responsibility each) with a real run-order dependency:

1. `ela_mis_datasets.students` -> `bronze.students`
2. `ela_mis_datasets.course_enrollments` -> `bronze.course_enrollments` (reads `bronze.students` for its list of eligible user_ids)

See each subfolder's own README for endpoint/config/table detail and the
simplifications made versus the original script (dropped the overlap-page
resume mechanic and the snapshot/atomic-replace pattern in favor of
idempotent upserts -- see each README for why). This is one of six
top-level folders under `api_scripts/`, each mapping 1:1 to one of the
original legacy script folders the extract/transform logic was ported
from -- see `documentation/API_JOBS.md` for the full picture.
