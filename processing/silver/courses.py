"""Silver transform: bronze.course_batch_merge -> silver.courses.

This is the first *reconciled* Silver model: three Bronze tables
(bronze.course_catalog, bronze.course_batch_merge, bronze.course_catalogue_raw)
independently port the same catalogue/batch domain from different legacy
scripts with different inclusion rules, and ROADMAP.md deferred building a
single silver.courses until there was a project-owner decision on which one
is authoritative. That decision (see migration 009_silver_courses.sql):

1. Source is bronze.course_batch_merge only -- it already applies the
   keyword-based junk/test-batch filter (batch_name containing "test batch",
   bundle_name containing test/demo/dummy/sample when there's no catalogue
   match) at collection time, which is the filtering rule this Silver model
   trusts. bronze.course_catalog's fixed 20-batch-id exclusion list is not
   re-applied. bronze.course_catalogue_raw has no batch merge at all, so it
   was never a candidate source for this per-batch grain.
2. Archived batches are excluded here, in Silver, via batch_status --
   bronze.course_batch_merge itself keeps them (its own Is_Latest_Batch
   computation needs the full batch history), but silver.courses only
   represents Active/Completed batches plus catalogue-only rows.
"""
from __future__ import annotations

from psycopg2.extras import execute_values

from processing.silver._normalize import clean_text, parse_int
from shared.database import Database

_EXCLUDED_BATCH_STATUSES = ("Archived",)

_SELECT_SQL = """
    SELECT bundle_id, bundle_name, batch_id, batch_name, batch_status,
           has_batch, is_latest_batch, start_date, end_date, tutor_name,
           tutor_id, tutors, tutor_ids, batch_enrollment_count,
           bundle_enrollment_count, course_name, course_ids, subject,
           level, language, examination, course_type, course_division,
           certificate, course_sponsor, course_title_sanskrit,
           number_of_lectures, duration, personas, computer_based_assessment,
           product_id, sss_category, viniyoga, adhyayanam_category,
           term_of_course, position_in_funnel, division, is_catalogue_match,
           catalogue_status, final_status, received_at
    FROM bronze.course_batch_merge
    WHERE (bundle_id IS NOT NULL OR batch_id IS NOT NULL)
      AND (batch_status IS NULL OR batch_status NOT IN %(excluded)s)
"""

_UPSERT_SQL = """
    INSERT INTO silver.courses (
        course_key, bundle_id, bundle_name, batch_id, batch_name, batch_status,
        has_batch, is_latest_batch, start_date, end_date, tutor_name, tutor_id,
        tutors, tutor_ids, batch_enrollment_count, bundle_enrollment_count,
        course_name, course_ids, subject, level, language, examination,
        course_type, course_division, certificate, course_sponsor,
        course_title_sanskrit, number_of_lectures, duration, personas,
        computer_based_assessment, product_id, sss_category, viniyoga,
        adhyayanam_category, term_of_course, position_in_funnel, division,
        is_catalogue_match, catalogue_status, final_status, source_updated_at
    ) VALUES %s
    ON CONFLICT (course_key) DO UPDATE SET
        bundle_id = EXCLUDED.bundle_id,
        bundle_name = EXCLUDED.bundle_name,
        batch_id = EXCLUDED.batch_id,
        batch_name = EXCLUDED.batch_name,
        batch_status = EXCLUDED.batch_status,
        has_batch = EXCLUDED.has_batch,
        is_latest_batch = EXCLUDED.is_latest_batch,
        start_date = EXCLUDED.start_date,
        end_date = EXCLUDED.end_date,
        tutor_name = EXCLUDED.tutor_name,
        tutor_id = EXCLUDED.tutor_id,
        tutors = EXCLUDED.tutors,
        tutor_ids = EXCLUDED.tutor_ids,
        batch_enrollment_count = EXCLUDED.batch_enrollment_count,
        bundle_enrollment_count = EXCLUDED.bundle_enrollment_count,
        course_name = EXCLUDED.course_name,
        course_ids = EXCLUDED.course_ids,
        subject = EXCLUDED.subject,
        level = EXCLUDED.level,
        language = EXCLUDED.language,
        examination = EXCLUDED.examination,
        course_type = EXCLUDED.course_type,
        course_division = EXCLUDED.course_division,
        certificate = EXCLUDED.certificate,
        course_sponsor = EXCLUDED.course_sponsor,
        course_title_sanskrit = EXCLUDED.course_title_sanskrit,
        number_of_lectures = EXCLUDED.number_of_lectures,
        duration = EXCLUDED.duration,
        personas = EXCLUDED.personas,
        computer_based_assessment = EXCLUDED.computer_based_assessment,
        product_id = EXCLUDED.product_id,
        sss_category = EXCLUDED.sss_category,
        viniyoga = EXCLUDED.viniyoga,
        adhyayanam_category = EXCLUDED.adhyayanam_category,
        term_of_course = EXCLUDED.term_of_course,
        position_in_funnel = EXCLUDED.position_in_funnel,
        division = EXCLUDED.division,
        is_catalogue_match = EXCLUDED.is_catalogue_match,
        catalogue_status = EXCLUDED.catalogue_status,
        final_status = EXCLUDED.final_status,
        source_updated_at = EXCLUDED.source_updated_at,
        silver_updated_at = now()
    RETURNING id
"""


def _course_key(batch_id: object, bundle_id: object) -> str | None:
    """batch_id when present; otherwise a synthetic per-bundle key for
    catalogue-only rows (has_batch = false, batch_id NULL) -- see module
    docstring and migration 009 for why this can't just be batch_id."""
    cleaned_batch_id = clean_text(batch_id)
    if cleaned_batch_id:
        return cleaned_batch_id
    cleaned_bundle_id = clean_text(bundle_id)
    if cleaned_bundle_id:
        return f"catalogue-only:{cleaned_bundle_id}"
    return None


def transform_courses(database: Database) -> tuple[int, int]:
    with database.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_SELECT_SQL, {"excluded": _EXCLUDED_BATCH_STATUSES})
        rows = cursor.fetchall()

    rows_read = len(rows)
    values = []
    for row in rows:
        (
            bundle_id, bundle_name, batch_id, batch_name, batch_status,
            has_batch, is_latest_batch, start_date, end_date, tutor_name,
            tutor_id, tutors, tutor_ids, batch_enrollment_count,
            bundle_enrollment_count, course_name, course_ids, subject,
            level, language, examination, course_type, course_division,
            certificate, course_sponsor, course_title_sanskrit,
            number_of_lectures, duration, personas, computer_based_assessment,
            product_id, sss_category, viniyoga, adhyayanam_category,
            term_of_course, position_in_funnel, division, is_catalogue_match,
            catalogue_status, final_status, received_at,
        ) = row

        course_key = _course_key(batch_id, bundle_id)
        if course_key is None:
            continue

        values.append((
            course_key,
            clean_text(bundle_id),
            clean_text(bundle_name),
            clean_text(batch_id),
            clean_text(batch_name),
            clean_text(batch_status),
            has_batch,
            is_latest_batch,
            start_date,
            end_date,
            clean_text(tutor_name),
            clean_text(tutor_id),
            clean_text(tutors),
            clean_text(tutor_ids),
            parse_int(batch_enrollment_count),
            parse_int(bundle_enrollment_count),
            clean_text(course_name),
            clean_text(course_ids),
            clean_text(subject),
            clean_text(level),
            clean_text(language),
            clean_text(examination),
            clean_text(course_type),
            clean_text(course_division),
            clean_text(certificate),
            clean_text(course_sponsor),
            clean_text(course_title_sanskrit),
            clean_text(number_of_lectures),
            clean_text(duration),
            clean_text(personas),
            clean_text(computer_based_assessment),
            clean_text(product_id),
            clean_text(sss_category),
            clean_text(viniyoga),
            clean_text(adhyayanam_category),
            clean_text(term_of_course),
            clean_text(position_in_funnel),
            clean_text(division),
            is_catalogue_match,
            clean_text(catalogue_status),
            clean_text(final_status),
            received_at,
        ))

    if not values:
        return rows_read, 0

    with database.transaction() as conn:
        cursor = conn.cursor()
        returned = execute_values(cursor, _UPSERT_SQL, values, page_size=500, fetch=True)
        rows_written = len(returned)

    return rows_read, rows_written
