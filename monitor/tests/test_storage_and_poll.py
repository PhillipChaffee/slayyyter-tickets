from datetime import datetime, timedelta, timezone

import pytest

from monitor import poll, storage
from monitor.sources.base import PricePoint


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "PRICES_PATH", tmp_path / "prices.ndjson")
    monkeypatch.setattr(storage, "LATEST_PATH", tmp_path / "latest.json")
    monkeypatch.setattr(storage, "ALERTS_PATH", tmp_path / "alerts.json")
    return tmp_path


def test_storage_round_trip(tmp_data_dir):
    p1 = PricePoint(
        ts="2026-08-15T18:00:00Z",
        source="seatgeek",
        event_id="123",
        lowest_price=285.0,
        highest_price=500.0,
        average_price=400.0,
        listing_count=87,
        currency="USD",
        ok=True,
    )
    p2 = PricePoint(
        ts="2026-08-15T18:00:01Z",
        source="ticketmaster",
        event_id="abc",
        lowest_price=312.0,
        highest_price=580.0,
        average_price=None,
        listing_count=None,
        currency="USD",
        ok=True,
    )
    storage.append_price_points([p1, p2])
    rows = storage.read_history()
    assert len(rows) == 2
    assert rows[0]["source"] == "seatgeek"
    assert rows[1]["lowest_price"] == 312.0


def test_write_latest_picks_lowest_anywhere(tmp_data_dir):
    p1 = PricePoint(
        ts="2026-08-15T18:00:00Z", source="seatgeek", event_id="123",
        lowest_price=285.0, highest_price=None, average_price=None,
        listing_count=87, currency="USD", ok=True,
    )
    p2 = PricePoint(
        ts="2026-08-15T18:00:01Z", source="ticketmaster", event_id="abc",
        lowest_price=312.0, highest_price=None, average_price=None,
        listing_count=None, currency="USD", ok=True,
    )
    payload = storage.write_latest([p1, p2])
    assert payload["lowest_anywhere"]["price"] == 285.0
    assert payload["lowest_anywhere"]["source"] == "seatgeek"


def test_write_latest_handles_no_ok_points(tmp_data_dir):
    p = PricePoint(
        ts="2026-08-15T18:00:00Z", source="seatgeek", event_id="123",
        lowest_price=None, highest_price=None, average_price=None,
        listing_count=None, currency="USD", ok=False, error="api down",
    )
    payload = storage.write_latest([p])
    assert payload["lowest_anywhere"] is None


def test_required_cadence_hours_phases():
    from datetime import date, timezone
    from zoneinfo import ZoneInfo

    pt = ZoneInfo("America/Los_Angeles")

    def utc(y, mo, d, h=12):
        return datetime(y, mo, d, h, tzinfo=pt).astimezone(timezone.utc)

    assert poll.required_cadence_hours(utc(2026, 5, 6)) == 6.0
    assert poll.required_cadence_hours(utc(2026, 7, 31)) == 6.0
    assert poll.required_cadence_hours(utc(2026, 8, 1)) == 2.0
    assert poll.required_cadence_hours(utc(2026, 8, 8)) == 2.0
    assert poll.required_cadence_hours(utc(2026, 8, 9)) == 0.25
    assert poll.required_cadence_hours(utc(2026, 8, 10)) == 1.0
    assert poll.required_cadence_hours(utc(2026, 8, 31)) == 1.0
    assert poll.required_cadence_hours(utc(2026, 9, 1)) == 0.5
    assert poll.required_cadence_hours(utc(2026, 9, 7)) == 0.5
    assert poll.required_cadence_hours(utc(2026, 9, 8)) == 0.25


def test_should_poll_now_first_run():
    now = datetime(2026, 5, 6, 18, tzinfo=timezone.utc)
    assert poll.should_poll_now(None, now) is True


def test_should_poll_now_due_after_cadence():
    now = datetime(2026, 6, 1, 18, tzinfo=timezone.utc)
    latest = {"as_of": (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert poll.should_poll_now(latest, now) is True


def test_should_poll_now_skip_when_too_soon():
    now = datetime(2026, 6, 1, 18, tzinfo=timezone.utc)
    latest = {"as_of": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert poll.should_poll_now(latest, now) is False


def test_main_evaluates_alerts_when_not_due(tmp_data_dir, monkeypatch, capsys):
    """If poll is not due, we still evaluate time-gated alerts against existing latest.json."""
    import json
    from zoneinfo import ZoneInfo

    pt = ZoneInfo("America/Los_Angeles")

    # Pretend "now" is 9:05 AM PT — within heartbeat window.
    target_pt = datetime(2026, 6, 15, 9, 5, tzinfo=pt)
    target_utc = target_pt.astimezone(timezone.utc)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return target_utc.astimezone(tz) if tz else target_utc.replace(tzinfo=None)

    monkeypatch.setattr("monitor.poll.datetime", FrozenDatetime)
    monkeypatch.setattr("monitor.alerts.datetime", FrozenDatetime)

    # Pre-seed latest.json from "1 hour ago" so should_poll_now returns False.
    latest = {
        "as_of": (target_utc - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lowest_anywhere": {"price": 300.0, "source": "etc_scraper"},
        "by_source": {
            "etc_scraper": {"price": 300.0, "ok": True, "ts": "2026-06-15T08:00:00Z", "listing_count": None},
        },
        "trend": {"vs_24h_ago": None, "vs_7d_median": None},
    }
    (tmp_data_dir / "latest.json").write_text(json.dumps(latest))

    rc = poll.main(["--dry-run"])
    assert rc == 0

    captured = capsys.readouterr()
    # Heartbeat must fire even though we did not poll — and the body must show
    # the SEEDED price ($300), proving no fetch happened (a live fetch would
    # error out without API keys, or return a different price).
    assert "daily_heartbeat" in captured.out
    assert "$300" in captured.out
