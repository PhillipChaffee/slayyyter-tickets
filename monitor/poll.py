from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .alerts import evaluate
from .config import load_config, load_secrets
from .notify import send_all
from .sources.base import PricePoint, SourceClient
from .sources.etc_scraper import EtcScraper
from .sources.seatgeek import SeatGeekClient
from .sources.ticketmaster import TicketmasterClient
from .storage import (
    append_alert,
    append_price_points,
    read_alerts,
    read_history,
    read_latest,
    write_latest,
)


PACIFIC = ZoneInfo("America/Los_Angeles")


def required_cadence_hours(now_utc: datetime) -> float:
    """Return the required polling cadence in hours for the given moment (PT-relative)."""
    d = now_utc.astimezone(PACIFIC).date()
    if d == date(2026, 9, 8):
        return 0.25
    if date(2026, 9, 1) <= d <= date(2026, 9, 7):
        return 0.5
    if d == date(2026, 8, 9):
        return 0.25
    if date(2026, 8, 10) <= d <= date(2026, 8, 31):
        return 1.0
    if date(2026, 8, 1) <= d <= date(2026, 8, 8):
        return 2.0
    return 6.0


def should_poll_now(latest: dict | None, now_utc: datetime) -> bool:
    if latest is None:
        return True
    cadence_h = required_cadence_hours(now_utc)
    last = datetime.strptime(latest["as_of"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    elapsed_h = (now_utc - last).total_seconds() / 3600
    # Allow 15 min slop for cron drift.
    return elapsed_h >= cadence_h - 0.25


def build_clients(cfg: dict, secrets: dict) -> list[SourceClient]:
    clients: list[SourceClient] = []
    s = cfg.get("sources", {})
    if s.get("ticketmaster", {}).get("enabled"):
        clients.append(TicketmasterClient(s["ticketmaster"], secrets))
    if s.get("seatgeek", {}).get("enabled"):
        clients.append(SeatGeekClient(s["seatgeek"], secrets))
    if s.get("etc_scraper", {}).get("enabled"):
        clients.append(EtcScraper(s["etc_scraper"], secrets))
    return clients


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="don't send notifications or write history")
    parser.add_argument("--force", action="store_true", help="poll even if not due (skips should_poll_now)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("poll")

    cfg = load_config()
    secrets = load_secrets()
    now_utc = datetime.now(timezone.utc)

    if cfg.get("paused"):
        log.info("config.paused = true; exiting")
        return 0

    latest_payload = read_latest()
    poll_due = args.force or should_poll_now(latest_payload, now_utc)

    if poll_due:
        clients = build_clients(cfg, secrets)
        if not clients:
            log.error("no enabled sources")
            return 2

        points: list[PricePoint] = []
        for c in clients:
            log.info("fetching %s", c.name)
            try:
                p = c.fetch()
            except Exception as e:
                log.exception("fetch failed: %s", c.name)
                p = PricePoint.now(c.name, ok=False, error=f"unhandled: {e}")
            log.info(
                "  %s: ok=%s lowest=%s listings=%s err=%s",
                c.name, p.ok, p.lowest_price, p.listing_count, p.error,
            )
            points.append(p)

        if args.dry_run:
            log.info("[dry-run] not writing history or latest")
            latest_payload = {
                "as_of": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lowest_anywhere": _ephemeral_lowest(points),
                "by_source": {p.source: {"price": p.lowest_price, "listing_count": p.listing_count, "ok": p.ok, "ts": p.ts} for p in points},
                "trend": {"vs_24h_ago": None, "vs_7d_median": None},
            }
        else:
            append_price_points(points)
            latest_payload = write_latest(points)
    else:
        log.info(
            "skip fetch: not due (cadence=%.2fh, last=%s) — still evaluating time-gated alerts",
            required_cadence_hours(now_utc),
            latest_payload.get("as_of") if latest_payload else None,
        )
        if not latest_payload:
            log.info("no latest.json yet; nothing to evaluate")
            return 0

    history = read_history(since_hours=24 * 14)

    alert_log = read_alerts()
    alerts = evaluate(
        cfg=cfg,
        latest=latest_payload,
        history=history,
        alert_log=alert_log,
        now_utc=now_utc,
    )
    log.info("evaluated %d alert(s)", len(alerts))
    for a in alerts:
        log.info("  alert: %s — %s", a.rule, a.title)

    deliveries = send_all(alerts, secrets, dry_run=args.dry_run)

    if not args.dry_run:
        for a, ds in zip(alerts, deliveries):
            append_alert({
                "ts": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "rule": a.rule,
                "severity": a.severity,
                "title": a.title,
                "metadata": a.metadata,
                "deliveries": ds,
            })

    return 0


def _ephemeral_lowest(points: list[PricePoint]) -> dict | None:
    ok = [p for p in points if p.ok and p.lowest_price is not None]
    if not ok:
        return None
    cheapest = min(ok, key=lambda p: p.lowest_price)
    return {"price": cheapest.lowest_price, "source": cheapest.source}


if __name__ == "__main__":
    sys.exit(main())
