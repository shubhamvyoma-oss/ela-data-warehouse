from __future__ import annotations

import inspect

from processing.silver.runner import transform_registry


def test_transform_registry_has_expected_entries() -> None:
    assert set(transform_registry()) == {"students", "class_id_lookup", "enrollment_reports"}


def test_each_transform_has_the_expected_signature() -> None:
    # Each transform takes a single `database` positional argument and
    # returns (rows_read, rows_written). Full behavioral coverage needs a
    # live Postgres fixture, which doesn't exist yet in this suite -- same
    # documented gap as the DB-dependent api_scripts collectors
    # (class_id_lookup, course_enrollments, class_session_attendance).
    for name, fn in transform_registry().items():
        params = list(inspect.signature(fn).parameters)
        assert params == ["database"], f"{name} transform has unexpected signature {params}"
