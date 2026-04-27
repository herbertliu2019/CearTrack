"""Base class contract for test modules."""

from abc import ABC, abstractmethod
from typing import List, Tuple


class TestModule(ABC):
    name: str
    display_name: str
    icon: str

    @abstractmethod
    def extract_envelope(self, raw_payload: dict) -> dict: ...

    @abstractmethod
    def compute_verdict(self, envelope: dict) -> dict: ...

    @abstractmethod
    def get_display_schema(self) -> dict: ...

    def validate(self, raw_payload: dict) -> Tuple[bool, str]:
        return True, "OK"

    def extract_searchable_sns(self, envelope: dict) -> List[dict]:
        """Every SN string in this envelope that search should match.

        Default: just the primary system SN. Subclasses override to add
        secondary SNs (e.g. each storage device's serial for laptop).
        Format: [{"sn": "...", "kind": "system" | "storage" | ...}]
        """
        return [{"sn": envelope.get("sn", ""), "kind": "system"}]
