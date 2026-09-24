from __future__ import annotations

from pathlib import Path

from api_scripts.runner import job_registry


def test_repository_uses_frozen_component_layout() -> None:
    required = {
        # api_scripts/ has exactly six top-level folders, one per original
        # legacy source folder the extract/transform logic was ported from.
        "api_scripts/attendance",
        "api_scripts/attendance_data",
        "api_scripts/attendance_data/catalogue",
        "api_scripts/attendance_data/class_id_lookup",
        "api_scripts/attendance_data/class_session_attendance",
        "api_scripts/courses_batches",
        "api_scripts/courses_batches/course_batch_merge",
        "api_scripts/courses_batches/course_catalogue_raw",
        "api_scripts/edmingle_api_key_generator",
        "api_scripts/ela_mis_datasets",
        "api_scripts/ela_mis_datasets/students",
        "api_scripts/ela_mis_datasets/course_enrollments",
        "api_scripts/enrollments_reports",
        "services/edmingle_webhook",
        "services/scheduler",
        "processing/silver",
        "processing/gold",
        "docker/compose/development.yml",
        "ROADMAP.md",
        "documentation/decisions/ADR-002-consolidate-placeholder-folders.md",
        "shared/preflight_cli.py",
    }

    assert all(Path(path).exists() for path in required)
    assert not Path("jobs").exists()
    assert not Path("platform/scheduler").exists()

    # These flat, single-job folder names must NOT exist anymore -- they
    # were moved under their parent source-folder (see git history / the
    # session that did this move) so each of the six original legacy
    # folders maps to exactly one api_scripts/ folder.
    removed = {
        "platform",
        "warehouse",
        "dashboards",
        "processing/bronze",
        "processing/quality",
        "processing/replay",
        "processing/validation",
        "services/monitoring",
        "services/notification",
        "docker/monitoring",
        "docker/nginx",
        "api_scripts/catalogue",
        "api_scripts/class_id_lookup",
        "api_scripts/class_session_attendance",
        "api_scripts/course_batch_merge",
        "api_scripts/course_catalogue_raw",
        "api_scripts/students",
        "api_scripts/course_enrollments",
        "api_scripts/enrollment_reports",
    }
    assert not any(Path(path).exists() for path in removed)


def test_job_registry_uses_confirmed_names() -> None:
    assert set(job_registry()) == {
        "attendance",
        "attendance_data.catalogue",
        "attendance_data.class_id_lookup",
        "attendance_data.class_session_attendance",
        "courses_batches.course_batch_merge",
        "courses_batches.course_catalogue_raw",
        "ela_mis_datasets.students",
        "ela_mis_datasets.course_enrollments",
        "enrollment_reports",
    }


def test_naming_convention_is_an_explicit_project_standard() -> None:
    standard = Path("documentation/NAMING_CONVENTIONS.md").read_text(encoding="utf-8")

    for prefix in ("vw_", "mv_", "sp_", "fn_"):
        assert f"`{prefix}`" in standard
    assert "public.webhook_events" in standard
