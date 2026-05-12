"""
Shared data models and abstract interfaces for all integration clients.

The three clients (Genetec, T2 Iris, T2 Flex) must all return instances
of these dataclasses. Swapping a stub for a real client only requires
updating the client file — the rest of the app is unaffected.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PlateRead:
    plate: str
    timestamp: datetime


@dataclass
class Payment:
    plate: str


@dataclass
class Citation:
    plate: str


@dataclass
class PermitHolder:
    entity_uid: str
    email: str | None
    series_prefix: str
    permit_number: str
    plates: list[str] = field(default_factory=list)
    name: str = ""


# ---------------------------------------------------------------------------
# Abstract client interfaces
# ---------------------------------------------------------------------------

class PlateReadsClient(ABC):
    @abstractmethod
    async def fetch_reads(self, year: int, month: int) -> list[PlateRead]:
        """Return all plate reads for the given calendar month."""


class PaymentsClient(ABC):
    @abstractmethod
    async def fetch_payments(self, year: int, month: int) -> list[Payment]:
        """Return all payments recorded in the given calendar month."""


class CitationsAndPermitsClient(ABC):
    @abstractmethod
    async def fetch_citations(self, year: int, month: int) -> list[Citation]:
        """Return all citations issued in the given calendar month."""

    @abstractmethod
    async def fetch_permits(self) -> list[PermitHolder]:
        """Return all currently active permit holders."""
