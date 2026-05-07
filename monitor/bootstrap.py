"""
One-time setup: discover the event ID for our show on each source.

Usage:
    python -m monitor.bootstrap                  # interactive: pick from candidates
    python -m monitor.bootstrap --auto           # auto-select if exactly one date-match
    python -m monitor.bootstrap --keyword Slayyyter --date 2026-09-08
"""

from __future__ import annotations

import argparse
import sys

from .config import load_config, load_secrets, save_config
from .sources.seatgeek import SeatGeekClient
from .sources.ticketmaster import TicketmasterClient


def search_tm(api_key: str, keyword: str, date_iso: str) -> list[dict]:
    # Use TM's localStartDateTime / localEndDateTime (no timezone) so a
    # late-evening show isn't pushed past the UTC end-of-day boundary.
    return TicketmasterClient.search(
        api_key,
        keyword,
        localStartDateTime=f"{date_iso}T00:00:00",
        localEndDateTime=f"{date_iso}T23:59:59",
        size="50",
    )


def search_sg(client_id: str, q: str, date_iso: str) -> list[dict]:
    return SeatGeekClient.search(
        client_id, q, **{"datetime_local.gte": date_iso, "datetime_local.lte": date_iso}
    )


def matches_venue(venue_name: str, target_venue: str | None, target_city: str | None) -> bool:
    """Heuristic: venue name contains target venue OR target city (case-insensitive)."""
    if not venue_name:
        return False
    name = venue_name.lower()
    if target_venue and target_venue.lower() in name:
        return True
    if target_city and target_city.lower() in name:
        return True
    return False


def pick(prompt: str, items: list[tuple[str, str, str]]) -> int | None:
    if not items:
        print(f"  no candidates")
        return None
    print(f"\n{prompt}")
    for i, (eid, name, date) in enumerate(items):
        print(f"  [{i}] {date}  {name}  (id={eid})")
    if len(items) == 1:
        print(f"  → only one match, selecting [0]")
        return 0
    choice = input("  pick number (or blank to skip): ").strip()
    if not choice:
        return None
    try:
        n = int(choice)
        if 0 <= n < len(items):
            return n
    except ValueError:
        pass
    print("  invalid, skipping")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", default=None)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD local")
    parser.add_argument(
        "--auto", action="store_true", help="auto-select if exactly one date-match"
    )
    args = parser.parse_args()

    cfg = load_config()
    secrets = load_secrets()
    keyword = args.keyword or cfg["event"]["name"].split(" at ")[0]
    date_iso = args.date or cfg["event"]["date_local"]
    target_venue = cfg["event"].get("venue")
    target_city = cfg["event"].get("city")

    print(f"Searching for: keyword={keyword!r} date={date_iso} venue~{target_venue!r} city~{target_city!r}")

    # Ticketmaster
    if cfg["sources"]["ticketmaster"]["enabled"]:
        tm_key = secrets.get("TICKETMASTER_API_KEY")
        if not tm_key:
            print("\n[ticketmaster] skipped: TICKETMASTER_API_KEY not set")
        else:
            try:
                events = search_tm(tm_key, keyword, date_iso)
            except Exception as e:
                print(f"\n[ticketmaster] error: {e}")
                events = []
            cands = []
            cand_events = []
            for e in events:
                venue_name = e.get("_embedded", {}).get("venues", [{}])[0].get("name", "")
                if target_venue and not matches_venue(venue_name, target_venue, target_city):
                    continue
                ts = e.get("dates", {}).get("start", {}).get("localDate", "?")
                name = e.get("name", "?") + (f" @ {venue_name}" if venue_name else "")
                eid = e.get("id", "?")
                cands.append((eid, name, ts))
                cand_events.append(e)
            events = cand_events  # only these are valid for url extraction below
            idx = (
                0
                if args.auto and len(cands) == 1
                else pick("[ticketmaster] candidates:", cands)
            )
            if idx is not None:
                eid = cands[idx][0]
                cfg["sources"]["ticketmaster"]["event_id"] = eid
                cfg["sources"]["ticketmaster"]["url"] = events[idx].get("url")
                cfg["links"]["ticketmaster_event"] = events[idx].get("url")
                print(f"  → set ticketmaster.event_id = {eid}")

    # SeatGeek
    if cfg["sources"]["seatgeek"]["enabled"]:
        sg_id = secrets.get("SEATGEEK_CLIENT_ID")
        if not sg_id:
            print("\n[seatgeek] skipped: SEATGEEK_CLIENT_ID not set")
        else:
            try:
                events = search_sg(sg_id, keyword, date_iso)
            except Exception as e:
                print(f"\n[seatgeek] error: {e}")
                events = []
            cands = []
            cand_events = []
            for e in events:
                venue_name = e.get("venue", {}).get("name", "")
                if target_venue and not matches_venue(venue_name, target_venue, target_city):
                    continue
                ts = e.get("datetime_local", "?")
                name = e.get("title", "?") + (f" @ {venue_name}" if venue_name else "")
                eid = str(e.get("id", "?"))
                cands.append((eid, name, ts))
                cand_events.append(e)
            events = cand_events
            idx = (
                0
                if args.auto and len(cands) == 1
                else pick("[seatgeek] candidates:", cands)
            )
            if idx is not None:
                eid = cands[idx][0]
                cfg["sources"]["seatgeek"]["event_id"] = int(eid)
                cfg["sources"]["seatgeek"]["url"] = events[idx].get("url")
                cfg["links"]["seatgeek_event"] = events[idx].get("url")
                print(f"  → set seatgeek.event_id = {eid}")

    save_config(cfg)
    print("\nWrote config.yaml")
    print("Commit + push, then trigger 'poll' workflow on GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
