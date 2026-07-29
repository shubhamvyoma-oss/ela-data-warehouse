from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoreResult:
    status: str
    stored_in_database: bool
    queued: bool
    duplicate: bool
