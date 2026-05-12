"""
Monthly draw scheduler.

Runs on the configured day/time each month (default: 1st at 09:00 PDT).
The job pulls data, qualifies, draws, and sends winner emails — completely
unattended. Winners without emails are queued for manager resolution.

Uses APScheduler with an AsyncIOScheduler so it integrates cleanly with
the FastAPI/asyncio event loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.core.draw import secure_draw
from app.core.qualify import run_qualification
from app.db.database import AsyncSessionLocal
from app.db.models import AuditLog, DrawHistory, MissingEmailQueue
from app.email.notify import send_winner_notifications
from app.integrations.genetec import GenetecClient
from app.integrations.t2_flex import T2FlexClient
from app.integrations.t2_iris import T2IrisClient

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=settings.campus_timezone)


def start_scheduler() -> None:
    scheduler.add_job(
        _monthly_draw_job,
        trigger=CronTrigger(
            day=settings.draw_day_of_month,
            hour=settings.draw_hour,
            minute=settings.draw_minute,
            timezone=settings.campus_timezone,
        ),
        id="monthly_draw",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Monthly draw scheduler started: day=%s %02d:%02d %s",
        settings.draw_day_of_month,
        settings.draw_hour,
        settings.draw_minute,
        settings.campus_timezone,
    )


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)


async def _monthly_draw_job() -> None:
    now = datetime.now(timezone.utc)
    year, month = now.year, now.month
    month_str = f"{year}-{month:02d}"

    logger.info("Monthly draw job starting for %s", month_str)

    try:
        reads     = await GenetecClient().fetch_reads(year, month)
        payments  = await T2IrisClient().fetch_payments(year, month)
        citations = await T2FlexClient().fetch_citations(year, month)
        permits   = await T2FlexClient().fetch_permits()

        qualifiers, summary = run_qualification(reads, payments, citations, permits)

        if not qualifiers:
            logger.warning("No qualifiers found for %s — draw skipped.", month_str)
            return

        winners = secure_draw(qualifiers, settings.num_winners)
        drawn_at = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            db.add(DrawHistory(
                month=month_str,
                drawn_at=drawn_at,
                drawn_by="scheduler",
                num_winners=settings.num_winners,
                winners=winners,
                pool_size=len(qualifiers),
                is_redraw=False,
                summary=summary,
            ))

            db.add(AuditLog(
                action="draw",
                month=month_str,
                actor="scheduler",
                details={"winners": [w["plate"] for w in winners], "pool_size": len(qualifiers)},
            ))

            missing = [w["plate"] for w in winners if not w.get("email")]
            for plate in missing:
                db.add(MissingEmailQueue(month=month_str, plate=plate))

            await db.commit()

        if missing:
            logger.warning(
                "Draw complete for %s but %d winner(s) have no email. "
                "Manager must resolve via POST /api/draw/resolve-email.",
                month_str, len(missing),
            )
        else:
            await send_winner_notifications(winners, month_str)
            logger.info("Winner notifications sent for %s.", month_str)

    except Exception:
        logger.exception("Monthly draw job failed for %s", month_str)
        raise
