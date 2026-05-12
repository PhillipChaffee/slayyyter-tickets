from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo


PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass
class Alert:
    rule: str
    title: str
    body: str
    severity: str  # info, warn, critical
    urls: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def now_pt(now_utc: datetime | None = None) -> datetime:
    return (now_utc or datetime.now(timezone.utc)).astimezone(PACIFIC)


_LISTING_COUNT_SOURCES = ("seatgeek", "vivid_seats")


def pair_signal(latest: dict, threshold_listings: int) -> str:
    """Return PAIR_LIKELY | SINGLE_ONLY | UNKNOWN based on the first source that reports a listing count."""
    sources = latest.get("by_source", {})
    for src_name in _LISTING_COUNT_SOURCES:
        count = (sources.get(src_name) or {}).get("listing_count")
        if count is not None:
            return "PAIR_LIKELY" if count >= threshold_listings else "SINGLE_ONLY"
    return "UNKNOWN"


def total_listings(latest: dict) -> int | None:
    """Best-known total listing count from sources that report it."""
    sources = latest.get("by_source", {})
    for src_name in _LISTING_COUNT_SOURCES:
        count = (sources.get(src_name) or {}).get("listing_count")
        if count is not None:
            return count
    return None


def in_cooldown(last_at: datetime | None, cooldown_hours: float, now_utc: datetime) -> bool:
    if last_at is None:
        return False
    return (now_utc - last_at) < timedelta(hours=cooldown_hours)


def fired_today(rule: str, alert_log: list[dict], now_utc: datetime) -> bool:
    today_pt = now_pt(now_utc).date()
    for a in alert_log:
        if a.get("rule") != rule:
            continue
        a_pt = datetime.strptime(a["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(PACIFIC).date()
        if a_pt == today_pt:
            return True
    return False


def has_fired_since(rule: str, alert_log: list[dict], since_utc: datetime) -> bool:
    for a in alert_log:
        if a.get("rule") != rule:
            continue
        a_utc = datetime.strptime(a["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if a_utc >= since_utc:
            return True
    return False


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def evaluate(
    *,
    cfg: dict,
    latest: dict,
    history: list[dict],
    alert_log: list[dict],
    now_utc: datetime | None = None,
) -> list[Alert]:
    """Run all enabled rules and return alerts that should fire now."""
    now_utc = now_utc or datetime.now(timezone.utc)
    alerts_cfg = cfg["alerts"]
    rules_cfg = alerts_cfg["rules"]
    cooldown_h = float(alerts_cfg.get("cooldown_hours", 6))
    sanity_floor = float(alerts_cfg.get("sanity_floor_usd", 30))
    threshold_usd = float(alerts_cfg.get("threshold_usd", 170))
    pair_min = int(alerts_cfg.get("pair_listing_count_min", 5))

    out: list[Alert] = []
    if cfg.get("paused"):
        return out

    lowest = (latest or {}).get("lowest_anywhere")
    lowest_price = lowest["price"] if lowest else None
    if lowest_price is not None and lowest_price < sanity_floor:
        # Treat as anomaly: no rules fire on it.
        lowest = None
        lowest_price = None

    signal = pair_signal(latest or {}, pair_min) if latest else "UNKNOWN"
    listing_total = total_listings(latest or {}) or 0
    urls = _build_urls(cfg, latest or {})

    # Rule 1: threshold pair-likely
    r = rules_cfg.get("threshold_pair_likely") or {}
    if r.get("enabled") and lowest_price is not None and lowest_price <= threshold_usd and signal == "PAIR_LIKELY":
        if not in_cooldown(_last_at("threshold_pair_likely", alert_log), cooldown_h, now_utc):
            out.append(Alert(
                rule="threshold_pair_likely",
                title=f"Slayyyter ${lowest_price:.0f} [PAIR LIKELY]",
                body=_format_body(latest, "PAIR LIKELY: 2 tickets at ~${:.0f} each".format(lowest_price), urls),
                severity="critical",
                urls=urls,
                metadata={"lowest": lowest_price, "source": lowest["source"]},
            ))

    # Rule 2: threshold single only OR unknown availability
    r = rules_cfg.get("threshold_single_only") or {}
    if r.get("enabled") and lowest_price is not None and lowest_price <= threshold_usd and signal in ("SINGLE_ONLY", "UNKNOWN"):
        if not in_cooldown(_last_at("threshold_single_only", alert_log), cooldown_h, now_utc):
            if signal == "SINGLE_ONLY":
                headline = f"SINGLE ONLY at ${lowest_price:.0f} — fallback option, pair availability uncertain ({listing_total} total listings)"
            else:
                headline = f"FLOOR HIT at ${lowest_price:.0f} — pair/single availability unknown (no listing count from SG)"
            out.append(Alert(
                rule="threshold_single_only",
                title=f"Slayyyter ${lowest_price:.0f} [SINGLE ONLY]" if signal == "SINGLE_ONLY" else f"Slayyyter ${lowest_price:.0f} [QTY UNKNOWN]",
                body=_format_body(latest, headline, urls),
                severity="warn",
                urls=urls,
                metadata={"lowest": lowest_price, "source": lowest["source"], "signal": signal},
            ))

    # Rule 3: 24h drop
    r = rules_cfg.get("drop_24h") or {}
    if r.get("enabled"):
        drop_pct = float(r.get("pct", -0.15))
        min_l = int(r.get("min_listings", 5))
        prev = _lowest_at(history, now_utc - timedelta(hours=24))
        if (
            lowest_price is not None
            and prev is not None
            and listing_total > min_l
            and ((lowest_price - prev) / prev) <= drop_pct
        ):
            if not in_cooldown(_last_at("drop_24h", alert_log), cooldown_h, now_utc):
                pct = (lowest_price - prev) / prev
                out.append(Alert(
                    rule="drop_24h",
                    title=f"Slayyyter ↓ ${lowest_price:.0f} ({pct * 100:.0f}% / 24h)",
                    body=_format_body(latest, f"24h ago: ${prev:.0f} → ${lowest_price:.0f} ({pct * 100:.0f}%)", urls),
                    severity="warn",
                    urls=urls,
                    metadata={"lowest": lowest_price, "prev_24h": prev, "pct": pct},
                ))

    # Rule 4: 7d trend
    r = rules_cfg.get("trend_7d") or {}
    if r.get("enabled"):
        thresh_pct = float(r.get("pct", -0.15))
        med = _median_lowest(history, hours=24 * 7)
        if (
            lowest_price is not None
            and med is not None
            and (lowest_price - med) / med <= thresh_pct
        ):
            if not in_cooldown(_last_at("trend_7d", alert_log), cooldown_h, now_utc):
                pct = (lowest_price - med) / med
                out.append(Alert(
                    rule="trend_7d",
                    title=f"Slayyyter ${lowest_price:.0f} (vs 7d median ${med:.0f}, {pct * 100:.0f}%)",
                    body=_format_body(latest, f"7d median: ${med:.0f} → now ${lowest_price:.0f}", urls),
                    severity="info",
                    urls=urls,
                    metadata={"lowest": lowest_price, "median_7d": med, "pct": pct},
                ))

    # Rule 5: last-48h backstop
    r = rules_cfg.get("last_48h_backstop") or {}
    if r.get("enabled"):
        starts = date.fromisoformat(r["starts_local"])
        nowpt = now_pt(now_utc)
        if nowpt.date() >= starts and nowpt.date() <= date.fromisoformat(cfg["event"]["date_local"]):
            for hhmm in r.get("times_local", []):
                if _is_time_match(hhmm, nowpt) and not _backstop_already_fired(alert_log, nowpt, hhmm):
                    threshold_already_hit = has_fired_since(
                        "threshold_pair_likely", alert_log, now_utc - timedelta(days=14)
                    )
                    body_pre = (
                        f"Threshold ${threshold_usd:.0f} has been hit; this is just a redundant heads-up."
                        if threshold_already_hit
                        else f"Threshold ${threshold_usd:.0f} NOT yet hit. Best price right now is ${lowest_price:.0f}." if lowest_price else "No live price data."
                    )
                    out.append(Alert(
                        rule="last_48h_backstop",
                        title=f"BACKSTOP {hhmm} PT - best now: ${lowest_price:.0f}" if lowest_price else f"BACKSTOP {hhmm} PT",
                        body=body_pre + "\n\n" + _format_body(latest, "Buy or skip.", urls),
                        severity="critical",
                        urls=urls,
                        metadata={"slot": hhmm, "lowest": lowest_price},
                    ))

    # Rule 6: mid-campaign check-ins
    r = rules_cfg.get("midcampaign_checkin") or {}
    if r.get("enabled"):
        nowpt = now_pt(now_utc)
        for ds in r.get("dates_local", []):
            if nowpt.date().isoformat() == ds and _is_time_match(r.get("time_local", "09:00"), nowpt):
                if not fired_today("midcampaign_checkin", alert_log, now_utc):
                    out.append(Alert(
                        rule="midcampaign_checkin",
                        title=f"Mid-campaign check-in ({ds})",
                        body=(
                            f"Current floor: ${lowest_price:.0f}\n" if lowest_price else "No live price data.\n"
                        ) + f"Threshold ${threshold_usd:.0f} still active. Edit config.yaml + push to revise.\n\n" + _format_body(latest, "", urls),
                        severity="info",
                        urls=urls,
                        metadata={"checkin_date": ds, "lowest": lowest_price},
                    ))

    # Rule 7: daily heartbeat
    r = rules_cfg.get("daily_heartbeat") or {}
    if r.get("enabled"):
        nowpt = now_pt(now_utc)
        if _is_time_match(r.get("time_local", "09:00"), nowpt) and not fired_today("daily_heartbeat", alert_log, now_utc):
            sources_summary = ", ".join(
                f"{s}=${v.get('price'):.0f}" if v.get("price") else f"{s}=NA"
                for s, v in (latest or {}).get("by_source", {}).items()
            )
            manual_block = _manual_check_block(cfg)
            out.append(Alert(
                rule="daily_heartbeat",
                title=f"Heartbeat {nowpt.date().isoformat()} — floor ${lowest_price:.0f}" if lowest_price else f"Heartbeat {nowpt.date().isoformat()}",
                body=(
                    f"Sources: {sources_summary}\n\n"
                    + manual_block
                    + _format_body(latest, "", urls)
                ),
                severity="info",
                urls=urls,
                metadata={"lowest": lowest_price},
            ))

    # Rule 8: inventory drying up
    r = rules_cfg.get("inventory_drying") or {}
    if r.get("enabled"):
        starts = date.fromisoformat(r.get("starts_local", "2026-08-09"))
        threshold = int(r.get("threshold", 10))
        nowpt = now_pt(now_utc)
        if nowpt.date() >= starts and listing_total > 0 and listing_total < threshold:
            if not in_cooldown(_last_at("inventory_drying", alert_log), cooldown_h, now_utc):
                out.append(Alert(
                    rule="inventory_drying",
                    title=f"Inventory drying: {listing_total} listings",
                    body=f"Total listings (SeatGeek): {listing_total}.\n" + _format_body(latest, "", urls),
                    severity="warn",
                    urls=urls,
                    metadata={"listings": listing_total},
                ))

    return out


# ---- helpers ----

def _last_at(rule: str, alert_log: list[dict]) -> datetime | None:
    matches = [a for a in alert_log if a.get("rule") == rule]
    if not matches:
        return None
    return _parse_iso(max(a["ts"] for a in matches))


def _lowest_at(history: list[dict], target_utc: datetime) -> float | None:
    """Lowest price within ±2h of target time across sources."""
    window = timedelta(hours=2)
    candidates = []
    for r in history:
        if not r.get("ok") or r.get("lowest_price") is None:
            continue
        ts = _parse_iso(r["ts"])
        if abs(ts - target_utc) <= window:
            candidates.append(r["lowest_price"])
    return min(candidates) if candidates else None


def _median_lowest(history: list[dict], hours: float) -> float | None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    by_bucket: dict[str, list[float]] = {}
    for r in history:
        if not r.get("ok") or r.get("lowest_price") is None:
            continue
        ts = _parse_iso(r["ts"])
        if ts < cutoff:
            continue
        by_bucket.setdefault(r["ts"][:13], []).append(r["lowest_price"])
    if not by_bucket:
        return None
    bucket_lows = [min(v) for v in by_bucket.values()]
    return median(bucket_lows)


def _is_time_match(hhmm: str, nowpt: datetime, tolerance_minutes: int = 60) -> bool:
    """True if nowpt is at or after the target HH:MM (today, in PT).

    Used together with `fired_today` so that even if cron drift skips the
    9–10 AM window entirely, the first run later in the day still catches up.
    The `tolerance_minutes` arg is kept for backwards compat but ignored —
    we now rely on `fired_today` for de-duplication.
    """
    del tolerance_minutes
    target_h, target_m = map(int, hhmm.split(":"))
    target = nowpt.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    return nowpt >= target


def _backstop_already_fired(alert_log: list[dict], nowpt: datetime, hhmm: str) -> bool:
    """True if backstop fired for this same date+slot already."""
    for a in alert_log:
        if a.get("rule") != "last_48h_backstop":
            continue
        if a.get("metadata", {}).get("slot") != hhmm:
            continue
        a_pt = _parse_iso(a["ts"]).astimezone(PACIFIC).date()
        if a_pt == nowpt.date():
            return True
    return False


def _build_urls(cfg: dict, latest: dict) -> list[str]:
    urls = []
    for name in ("ticketmaster", "seatgeek", "vivid_seats", "etc_scraper"):
        u = cfg.get("sources", {}).get(name, {}).get("url")
        if u:
            urls.append(u)
    return urls


def _manual_check_block(cfg: dict) -> str:
    """Block of links the user should eyeball — sources our pipeline doesn't track via API."""
    items: list[tuple[str, str]] = []
    tm_url = cfg.get("sources", {}).get("ticketmaster", {}).get("url")
    if tm_url:
        items.append(("Ticketmaster", tm_url))
    axs = cfg.get("links", {}).get("axs_resale")
    if axs:
        items.append(("AXS resale", axs))
    if not items:
        return ""
    lines = ["👀 MANUAL CHECK (not tracked via API):"]
    width = max(len(name) for name, _ in items)
    for name, url in items:
        lines.append(f"  {name.ljust(width)}  {url}")
    return "\n".join(lines) + "\n\n"


_NO_API_SOURCES = {"ticketmaster", "seatgeek"}


def _format_body(latest: dict, headline: str, urls: list[str]) -> str:
    if not latest:
        return headline
    lines = [headline] if headline else []
    for src, v in (latest or {}).get("by_source", {}).items():
        if v.get("price") is not None:
            lc = v.get("listing_count")
            lines.append(
                f"  {src}: ${v['price']:.0f}" + (f" ({lc} listings)" if lc is not None else "")
            )
        elif v.get("ok"):
            if src in _NO_API_SOURCES:
                lines.append(f"  {src}: not exposed via public API")
            else:
                lines.append(f"  {src}: no listings yet")
        else:
            lines.append(f"  {src}: error")
    trend = latest.get("trend") or {}
    if trend.get("vs_24h_ago") is not None:
        lines.append(f"  vs 24h ago: {trend['vs_24h_ago'] * 100:+.1f}%")
    if trend.get("vs_7d_median") is not None:
        lines.append(f"  vs 7d median: {trend['vs_7d_median'] * 100:+.1f}%")
    if urls:
        lines.append("")
        for u in urls:
            lines.append(f"  {u}")
    return "\n".join(lines)
