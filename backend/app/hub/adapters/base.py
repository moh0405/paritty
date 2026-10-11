from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from psycopg import Connection

from app.hub.normalize import SubjectKey


class FeedAdapter(ABC):
    """Adapter for one external system: which identifiers it has shown us so far, and how to read them (spec §9.9)."""
    system: str
    entity = "subject"            # subject | site
    full_number = True            # False when the feed carries only part of the subject number (IRT)

    @abstractmethod
    def source_ids(self, conn: Connection, day: date) -> list[str]:
        """Distinct identifiers visible in the feed on `day` (nothing from the future)."""

    @abstractmethod
    def parse(self, source_id: str) -> SubjectKey | None: ...
