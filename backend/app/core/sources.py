"""
Fetch all four data sources with errors translated into messages an office
staff member can act on (not stack traces).

Used by both /api/analyze and /api/draw so the two endpoints can never
disagree about how data is loaded.
"""

from __future__ import annotations

import logging

import httpx

from app.integrations.base import Citation, Payment, PermitHolder, PlateRead
from app.integrations.genetec import GenetecClient, ReadsFileError
from app.integrations.t2_flex import T2FlexClient
from app.integrations.t2_iris import PaymentsFetchError, T2IrisClient

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """Carries the failing source name + a human-readable message."""

    def __init__(self, source: str, message: str):
        self.source = source
        super().__init__(message)


async def fetch_all_sources(
    year: int, month: int
) -> tuple[list[PlateRead], list[Payment], list[Citation], list[PermitHolder]]:
    reads = await _fetch("plate reads", GenetecClient().fetch_reads(year, month))
    payments = await _fetch("payments (T2 Iris)", T2IrisClient().fetch_payments(year, month))
    citations = await _fetch("citations (T2 Flex)", T2FlexClient().fetch_citations(year, month))
    permits = await _fetch("permits (T2 Flex)", T2FlexClient().fetch_permits())

    # A live source returning nothing is almost always a problem worth
    # stopping for -- never silently run a draw on partial data.
    if not permits:
        raise SourceError(
            "permits (T2 Flex)",
            "The permits query returned zero permit holders. That can't be "
            "right -- check that query UID 4738 still exists in T2 Flex "
            "Query Manager.",
        )
    if not payments:
        raise SourceError(
            "payments (T2 Iris)",
            "T2 Iris returned zero payments for the month. That can't be "
            "right for a full month -- check the Iris API status before "
            "running a draw.",
        )

    return reads, payments, citations, permits


async def _fetch(source: str, coro):
    try:
        return await coro
    except (ReadsFileError, PaymentsFetchError) as exc:
        raise SourceError(source, str(exc)) from exc
    except httpx.ConnectError as exc:
        raise SourceError(
            source,
            f"Could not connect while fetching {source}. Are you on the UBC "
            "network or VPN?",
        ) from exc
    except httpx.TimeoutException as exc:
        raise SourceError(
            source,
            f"Timed out fetching {source}. The server may be slow -- try again "
            "in a minute.",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error fetching %s", source)
        raise SourceError(source, f"Unexpected error fetching {source}: {exc}") from exc
