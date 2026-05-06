from datetime import datetime, timedelta, timezone

import pytest

from monitor.alerts import (
    PACIFIC,
    evaluate,
    fired_today,
    in_cooldown,
    pair_signal,
)


CONFIG = {
    "event": {"date_local": "2026-09-08"},
    "links": {"axs_resale": "https://example.com/axs"},
    "sources": {
        "ticketmaster": {"url": "https://tm.example/ev"},
        "seatgeek": {"url": "https://sg.example/ev"},
    },
    "alerts": {
        "threshold_usd": 170.0,
        "cooldown_hours": 6,
        "sanity_floor_usd": 30.0,
        "pair_listing_count_min": 5,
        "rules": {
            "threshold_pair_likely": {"enabled": True},
            "threshold_single_only": {"enabled": True},
            "drop_24h": {"enabled": True, "pct": -0.15, "min_listings": 5},
            "trend_7d": {"enabled": True, "pct": -0.15},
            "last_48h_backstop": {
                "enabled": True,
                "times_local": ["09:00", "17:00"],
                "starts_local": "2026-09-06",
            },
            "midcampaign_checkin": {
                "enabled": True,
                "dates_local": ["2026-08-01", "2026-08-20"],
                "time_local": "09:00",
            },
            "daily_heartbeat": {"enabled": True, "time_local": "09:00"},
            "inventory_drying": {
                "enabled": True,
                "threshold": 10,
                "starts_local": "2026-08-09",
            },
        },
    },
    "paused": False,
}


def latest_with(price: float | None, sg_listings: int | None = 87, sg_ok: bool = True):
    return {
        "as_of": "2026-08-15T18:00:00Z",
        "lowest_anywhere": {"price": price, "source": "seatgeek"} if price else None,
        "by_source": {
            "ticketmaster": {"price": 312.0, "ok": True, "ts": "2026-08-15T18:00:00Z", "listing_count": None},
            "seatgeek": {"price": price, "ok": sg_ok, "ts": "2026-08-15T18:00:00Z", "listing_count": sg_listings},
        },
        "trend": {"vs_24h_ago": -0.04, "vs_7d_median": 0.02},
    }


def at_pt(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=PACIFIC).astimezone(timezone.utc)


def test_pair_signal_thresholds():
    assert pair_signal(latest_with(150.0, sg_listings=20), 5) == "PAIR_LIKELY"
    assert pair_signal(latest_with(150.0, sg_listings=4), 5) == "SINGLE_ONLY"
    assert pair_signal(latest_with(150.0, sg_listings=None), 5) == "UNKNOWN"


def test_threshold_pair_likely_fires_when_under():
    now = at_pt(2026, 8, 15, 12)  # not heartbeat hour
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(150.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "threshold_pair_likely" in rules
    assert "threshold_single_only" not in rules


def test_threshold_single_only_when_few_listings():
    now = at_pt(2026, 8, 15, 12)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(150.0, sg_listings=2),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "threshold_single_only" in rules
    assert "threshold_pair_likely" not in rules


def test_threshold_fires_with_unknown_signal():
    """When SG has no data (listing_count=None), still fire single_only with QTY UNKNOWN tag."""
    now = at_pt(2026, 5, 15, 12)
    latest = latest_with(160.0, sg_listings=None)
    alerts = evaluate(
        cfg=CONFIG, latest=latest, history=[], alert_log=[], now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "threshold_single_only" in rules
    matching = [a for a in alerts if a.rule == "threshold_single_only"][0]
    assert "QTY UNKNOWN" in matching.title
    assert "FLOOR HIT" in matching.body


def test_threshold_does_not_fire_above():
    now = at_pt(2026, 8, 15, 12)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(200.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "threshold_pair_likely" not in rules


def test_sanity_floor_blocks_anomalous_low_price():
    """A $5 lowest_price should NOT trigger threshold (data anomaly)."""
    now = at_pt(2026, 8, 15, 12)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(5.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "threshold_pair_likely" not in rules
    assert "threshold_single_only" not in rules


def test_cooldown_suppresses_repeat_threshold():
    now = at_pt(2026, 8, 15, 12)
    alert_log = [{
        "ts": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": "threshold_pair_likely",
        "metadata": {},
    }]
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(150.0, sg_listings=20),
        history=[],
        alert_log=alert_log,
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "threshold_pair_likely" not in rules


def test_24h_drop_fires():
    now = at_pt(2026, 8, 15, 12)
    history = [{
        "ts": (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "seatgeek",
        "lowest_price": 300.0,
        "listing_count": 50,
        "ok": True,
    }]
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(240.0, sg_listings=20),
        history=history,
        alert_log=[],
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "drop_24h" in rules


def test_24h_drop_blocked_by_low_listing_count():
    now = at_pt(2026, 8, 15, 12)
    history = [{
        "ts": (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "seatgeek",
        "lowest_price": 300.0,
        "listing_count": 50,
        "ok": True,
    }]
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(240.0, sg_listings=2),  # too few listings
        history=history,
        alert_log=[],
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "drop_24h" not in rules


def test_heartbeat_fires_at_9am_pt():
    now = at_pt(2026, 6, 1, 9)  # 9am PT
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(300.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert "daily_heartbeat" in {a.rule for a in alerts}


def test_heartbeat_does_not_fire_at_3am_pt():
    now = at_pt(2026, 6, 1, 3)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(300.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert "daily_heartbeat" not in {a.rule for a in alerts}


def test_heartbeat_only_fires_once_per_day():
    now_morning = at_pt(2026, 6, 1, 9, 5)
    log_morning = [{
        "ts": at_pt(2026, 6, 1, 9, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": "daily_heartbeat",
        "metadata": {},
    }]
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(300.0, sg_listings=20),
        history=[],
        alert_log=log_morning,
        now_utc=now_morning,
    )
    assert "daily_heartbeat" not in {a.rule for a in alerts}


def test_midcampaign_checkin_fires_on_aug_1():
    now = at_pt(2026, 8, 1, 9)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(280.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    rules = {a.rule for a in alerts}
    assert "midcampaign_checkin" in rules


def test_midcampaign_checkin_does_not_fire_on_aug_2():
    now = at_pt(2026, 8, 2, 9)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(280.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert "midcampaign_checkin" not in {a.rule for a in alerts}


def test_backstop_fires_at_9am_on_show_week():
    now = at_pt(2026, 9, 7, 9)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(220.0, sg_listings=8),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert "last_48h_backstop" in {a.rule for a in alerts}


def test_backstop_does_not_fire_before_starts():
    now = at_pt(2026, 9, 5, 9)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(220.0, sg_listings=8),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert "last_48h_backstop" not in {a.rule for a in alerts}


def test_inventory_drying_fires():
    now = at_pt(2026, 8, 15, 12)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(280.0, sg_listings=4),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert "inventory_drying" in {a.rule for a in alerts}


def test_inventory_drying_only_after_aug_9():
    now = at_pt(2026, 7, 15, 12)
    alerts = evaluate(
        cfg=CONFIG,
        latest=latest_with(280.0, sg_listings=4),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert "inventory_drying" not in {a.rule for a in alerts}


def test_paused_short_circuits():
    cfg = {**CONFIG, "paused": True}
    now = at_pt(2026, 8, 15, 12)
    alerts = evaluate(
        cfg=cfg,
        latest=latest_with(150.0, sg_listings=20),
        history=[],
        alert_log=[],
        now_utc=now,
    )
    assert alerts == []


def test_in_cooldown_logic():
    now = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
    assert in_cooldown(now - timedelta(hours=2), 6, now) is True
    assert in_cooldown(now - timedelta(hours=8), 6, now) is False
    assert in_cooldown(None, 6, now) is False
