"""
Qualifier enrichment -- fill in name/email for qualifiers that lack them,
using T2 Flex query 4726 (customer lookup by plate, one call per plate).

Results are cached in SQLite (reads.db / customer_cache): found customers
are kept forever, not-found results are re-checked after 30 days. So the
first monthly run does a few hundred lookups; later months mostly hit cache.

Qualifiers with no customer record keep blank fields -- the manager knows
"blank = we have no information" (agreed design).
"""

from __future__ import annotations

import logging

from app.config import settings
from app.store import reads_db

logger = logging.getLogger(__name__)


async def enrich_qualifiers(qualifiers: list[dict]) -> dict:
    """
    Mutates qualifiers in place (fills name/email/subclassification/
    customer_id where found). Returns stats for the report.
    """
    from app.integrations.t2_flex import fetch_customer_by_plate

    stats = {"needed": 0, "cache_hits": 0, "looked_up": 0, "found": 0, "errors": 0}

    if settings.use_stubs:
        logger.info("Enrichment skipped: T2 Flex is in stub mode")
        return stats

    for q in qualifiers:
        if q.get("email"):
            continue
        stats["needed"] += 1
        plate = q["plate"]

        record = reads_db.cache_get_customer(plate)
        if record is not None:
            stats["cache_hits"] += 1
        else:
            try:
                customer = await fetch_customer_by_plate(plate)
            except Exception as exc:
                # One bad lookup must not sink the whole run.
                stats["errors"] += 1
                logger.warning("Customer lookup failed for %s: %s", plate, exc)
                continue
            reads_db.cache_put_customer(plate, customer)
            stats["looked_up"] += 1
            record = customer if customer else {"found": False}

        if record.get("found", True) and (record.get("name") or record.get("email")):
            stats["found"] += 1
            q["name"] = q.get("name") or record.get("name", "")
            q["email"] = q.get("email") or (record.get("email") or None)
            q["subclassification"] = record.get("subclassification", "")
            q["customer_id"] = record.get("primary_id", "")

    logger.info("Enrichment: %(needed)d needed, %(cache_hits)d cached, "
                "%(looked_up)d looked up, %(found)d found, %(errors)d errors", stats)
    return stats
