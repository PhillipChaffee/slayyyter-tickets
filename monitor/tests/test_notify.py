import json
from unittest.mock import MagicMock, patch

from monitor.alerts import Alert
from monitor.notify import _ntfy, send_all


def test_ntfy_sends_json_payload_with_em_dash_title():
    """Regression: titles with em-dash must not raise UnicodeEncodeError.

    Real bug observed in CI on 2026-05-07: ntfy header-publish failed because
    HTTP headers must be ASCII. JSON-body publish has no such constraint.
    """
    alert = Alert(
        rule="daily_heartbeat",
        title="Heartbeat 2026-05-07 — floor $345",  # em-dash
        body="Sources: etc_scraper=$345",
        severity="info",
        urls=["https://example.com/event"],
    )

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = fake_resp

    with patch("monitor.notify.httpx.Client", return_value=fake_client):
        ok, err = _ntfy(alert, "MYTOPIC")

    assert ok is True
    assert err is None

    call = fake_client.__enter__.return_value.post.call_args
    assert call.args[0] == "https://ntfy.sh/"
    payload = call.kwargs["json"]
    assert payload["topic"] == "MYTOPIC"
    assert payload["title"] == "Heartbeat 2026-05-07 — floor $345"
    assert payload["message"] == "Sources: etc_scraper=$345"
    assert payload["priority"] == 3
    assert payload["tags"] == ["loudspeaker"]
    assert payload["click"] == "https://example.com/event"


def test_ntfy_sends_unicode_arrow_in_title():
    """Regression: drop_24h titles use ↓ unicode arrow."""
    alert = Alert(
        rule="drop_24h",
        title="Slayyyter ↓ $245 (-18% / 24h)",
        body="prev: $300, now: $245",
        severity="warn",
        urls=[],
    )
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = fake_resp

    with patch("monitor.notify.httpx.Client", return_value=fake_client):
        ok, _ = _ntfy(alert, "T")

    assert ok is True
    payload = fake_client.__enter__.return_value.post.call_args.kwargs["json"]
    assert "↓" in payload["title"]
    assert payload["priority"] == 4  # warn


def test_ntfy_critical_severity_maps_to_priority_5():
    alert = Alert(
        rule="threshold_pair_likely",
        title="Slayyyter $165 [PAIR LIKELY]",
        body="x",
        severity="critical",
        urls=[],
    )
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = fake_resp

    with patch("monitor.notify.httpx.Client", return_value=fake_client):
        _ntfy(alert, "T")

    payload = fake_client.__enter__.return_value.post.call_args.kwargs["json"]
    assert payload["priority"] == 5
    assert payload["tags"] == ["rotating_light"]


def test_send_all_skips_smtp_when_secrets_absent():
    alert = Alert(rule="r", title="t", body="b", severity="info", urls=[])
    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = fake_resp

    with patch("monitor.notify.httpx.Client", return_value=fake_client):
        per_alert = send_all([alert], {"NTFY_TOPIC": "T"}, dry_run=False)

    assert per_alert == [[{"channel": "ntfy", "ok": True, "error": None}]]


def test_send_all_dry_run_does_not_call_httpx():
    alert = Alert(rule="r", title="t", body="b", severity="info", urls=[])
    with patch("monitor.notify.httpx.Client") as fake_client_cls:
        per_alert = send_all([alert], {"NTFY_TOPIC": "T"}, dry_run=True)
    fake_client_cls.assert_not_called()
    assert per_alert == [[{"channel": "dry_run", "ok": True}]]
