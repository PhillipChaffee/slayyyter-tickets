from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from .sources.base import PricePoint


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
PRICES_PATH = DATA_DIR / "prices.ndjson"
LATEST_PATH = DATA_DIR / "latest.json"
ALERTS_PATH = DATA_DIR / "alerts.json"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def append_price_points(points: list[PricePoint]) -> None:
    _ensure_dir()
    with open(PRICES_PATH, "a") as f:
        for p in points:
            f.write(json.dumps(p.to_dict(), separators=(",", ":")) + "\n")


def read_history(since_hours: float | None = None) -> list[dict]:
    _ensure_dir()
    if not PRICES_PATH.exists():
        return []
    cutoff = None
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    rows: list[dict] = []
    with open(PRICES_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if cutoff:
                row_ts = datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if row_ts < cutoff:
                    continue
            rows.append(row)
    return rows


def write_latest(points: list[PricePoint]) -> dict:
    _ensure_dir()
    ok_points = [p for p in points if p.ok and p.lowest_price is not None]
    by_source = {}
    for p in points:
        by_source[p.source] = {
            "price": p.lowest_price,
            "listing_count": p.listing_count,
            "ok": p.ok,
            "ts": p.ts,
        }

    if ok_points:
        cheapest = min(ok_points, key=lambda p: p.lowest_price)
        lowest_anywhere = {"price": cheapest.lowest_price, "source": cheapest.source}
    else:
        lowest_anywhere = None

    trend = _compute_trend()

    payload = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lowest_anywhere": lowest_anywhere,
        "by_source": by_source,
        "trend": trend,
    }
    with open(LATEST_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    return payload


def _compute_trend() -> dict:
    """Return {vs_24h_ago, vs_7d_median} as fractional change vs current."""
    history = read_history(since_hours=24 * 7)
    if not history:
        return {"vs_24h_ago": None, "vs_7d_median": None}

    ok = [r for r in history if r.get("ok") and r.get("lowest_price") is not None]
    if not ok:
        return {"vs_24h_ago": None, "vs_7d_median": None}

    # Lowest across sources at each timestamp; reduce by ~hour bucket.
    by_ts: dict[str, list[float]] = {}
    for r in ok:
        by_ts.setdefault(r["ts"][:13], []).append(r["lowest_price"])  # YYYY-MM-DDTHH bucket
    bucket_lowest = sorted(((k, min(v)) for k, v in by_ts.items()), key=lambda x: x[0])
    if len(bucket_lowest) < 2:
        return {"vs_24h_ago": None, "vs_7d_median": None}

    current_low = bucket_lowest[-1][1]
    now = datetime.now(timezone.utc)

    def pct_change(a: float, b: float) -> float:
        return (b - a) / a if a else 0.0

    # 24h ago
    cutoff_24h = now - timedelta(hours=24)
    older_24h = [v for k, v in bucket_lowest if datetime.strptime(k + ":00:00", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) <= cutoff_24h]
    vs_24h = pct_change(older_24h[-1], current_low) if older_24h else None

    # 7d median
    seven_d = [v for _, v in bucket_lowest]
    vs_7d = pct_change(median(seven_d), current_low) if seven_d else None

    return {"vs_24h_ago": vs_24h, "vs_7d_median": vs_7d}


def read_latest() -> dict | None:
    if not LATEST_PATH.exists():
        return None
    with open(LATEST_PATH) as f:
        return json.load(f)


def append_alert(record: dict) -> None:
    _ensure_dir()
    existing = read_alerts()
    existing.append(record)
    with open(ALERTS_PATH, "w") as f:
        json.dump(existing, f, indent=2)


def read_alerts() -> list[dict]:
    if not ALERTS_PATH.exists():
        return []
    with open(ALERTS_PATH) as f:
        return json.load(f)


def last_alert_at(rule_name: str) -> datetime | None:
    alerts = read_alerts()
    matches = [a for a in alerts if a.get("rule") == rule_name]
    if not matches:
        return None
    last_ts = max(a["ts"] for a in matches)
    return datetime.strptime(last_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
