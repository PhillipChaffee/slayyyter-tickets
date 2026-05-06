from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from .alerts import Alert


log = logging.getLogger(__name__)


SEVERITY_PRIORITY = {
    "info": "default",
    "warn": "high",
    "critical": "max",
}
SEVERITY_TAG = {
    "info": "loudspeaker",
    "warn": "warning",
    "critical": "rotating_light",
}


def send_all(alerts: list[Alert], secrets: dict, dry_run: bool = False) -> list[list[dict]]:
    """Send each alert via every configured channel. Returns a list of delivery records per alert (same order as input)."""
    per_alert: list[list[dict]] = []
    for alert in alerts:
        deliveries: list[dict] = []
        if dry_run:
            log.info("[dry-run] would send alert: %s", alert.title)
            print(f"\n--- DRY RUN ALERT [{alert.rule}] ---")
            print(alert.title)
            print(alert.body)
            print("---")
            deliveries.append({"channel": "dry_run", "ok": True})
            per_alert.append(deliveries)
            continue
        if secrets.get("NTFY_TOPIC"):
            ok, err = _ntfy(alert, secrets["NTFY_TOPIC"])
            deliveries.append({"channel": "ntfy", "ok": ok, "error": err})
        if secrets.get("SMTP_USER") and secrets.get("SMTP_PASS") and secrets.get("SMTP_TO"):
            ok, err = _smtp(alert, secrets)
            deliveries.append({"channel": "smtp", "ok": ok, "error": err})
        per_alert.append(deliveries)
    return per_alert


def _ntfy(alert: Alert, topic: str) -> tuple[bool, str | None]:
    headers = {
        "Title": alert.title,
        "Priority": SEVERITY_PRIORITY.get(alert.severity, "default"),
        "Tags": SEVERITY_TAG.get(alert.severity, "bell"),
    }
    if alert.urls:
        headers["Click"] = alert.urls[0]
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                f"https://ntfy.sh/{topic}",
                content=alert.body.encode("utf-8"),
                headers=headers,
            )
        r.raise_for_status()
        return True, None
    except httpx.HTTPError as e:
        log.warning("ntfy delivery failed: %s", e)
        return False, str(e)


def _smtp(alert: Alert, secrets: dict) -> tuple[bool, str | None]:
    msg = EmailMessage()
    msg["Subject"] = f"[slayyyter-tickets] {alert.title}"
    msg["From"] = secrets["SMTP_USER"]
    msg["To"] = secrets["SMTP_TO"]
    msg.set_content(alert.body)
    host = secrets.get("SMTP_HOST", "smtp.gmail.com")
    port = int(secrets.get("SMTP_PORT", 587))
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            s.login(secrets["SMTP_USER"], secrets["SMTP_PASS"])
            s.send_message(msg)
        return True, None
    except (smtplib.SMTPException, OSError) as e:
        log.warning("smtp delivery failed: %s", e)
        return False, str(e)
