from __future__ import annotations

import httpx

from .base import PricePoint, SourceClient


BASE = "https://app.ticketmaster.com/discovery/v2"
TIMEOUT = httpx.Timeout(15.0, connect=10.0)


class TicketmasterClient(SourceClient):
    name = "ticketmaster"

    def fetch(self) -> PricePoint:
        api_key = self.secrets.get("TICKETMASTER_API_KEY")
        if not api_key:
            return PricePoint.now(self.name, ok=False, error="missing TICKETMASTER_API_KEY")

        event_id = self.config.get("event_id")
        if not event_id:
            return PricePoint.now(self.name, ok=False, error="missing event_id; run bootstrap")

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.get(f"{BASE}/events/{event_id}.json", params={"apikey": api_key})
            if r.status_code == 404:
                return PricePoint.now(self.name, event_id=event_id, ok=False, error="event 404")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            return PricePoint.now(self.name, event_id=event_id, ok=False, error=f"http: {e}")
        except ValueError as e:
            return PricePoint.now(self.name, event_id=event_id, ok=False, error=f"json: {e}")

        return self._parse(event_id, data)

    def _parse(self, event_id: str, data: dict) -> PricePoint:
        ranges = data.get("priceRanges") or []
        if not ranges:
            return PricePoint.now(
                self.name, event_id=event_id, ok=True, error="no priceRanges"
            )
        # Take the lowest min and the highest max across ranges.
        low = min(pr.get("min", float("inf")) for pr in ranges)
        high = max(pr.get("max", 0) for pr in ranges)
        currency = ranges[0].get("currency", "USD")
        return PricePoint.now(
            self.name,
            event_id=event_id,
            lowest_price=float(low) if low != float("inf") else None,
            highest_price=float(high) if high else None,
            currency=currency,
            ok=True,
        )

    def event_url(self) -> str | None:
        return self.config.get("url")

    @staticmethod
    def search(api_key: str, keyword: str, **params) -> list[dict]:
        """Helper for bootstrap."""
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(
                f"{BASE}/events.json",
                params={"apikey": api_key, "keyword": keyword, **params},
            )
        r.raise_for_status()
        return r.json().get("_embedded", {}).get("events", [])
