from __future__ import annotations

import httpx

from .base import PricePoint, SourceClient


BASE = "https://api.seatgeek.com/2"
TIMEOUT = httpx.Timeout(15.0, connect=10.0)


class SeatGeekClient(SourceClient):
    name = "seatgeek"

    def fetch(self) -> PricePoint:
        client_id = self.secrets.get("SEATGEEK_CLIENT_ID")
        if not client_id:
            return PricePoint.now(self.name, ok=False, error="missing SEATGEEK_CLIENT_ID")

        event_id = self.config.get("event_id")
        if not event_id:
            return PricePoint.now(self.name, ok=False, error="missing event_id; run bootstrap")

        params: dict[str, str] = {"client_id": client_id}
        if self.secrets.get("SEATGEEK_CLIENT_SECRET"):
            params["client_secret"] = self.secrets["SEATGEEK_CLIENT_SECRET"]

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.get(f"{BASE}/events/{event_id}", params=params)
            if r.status_code == 404:
                return PricePoint.now(self.name, event_id=str(event_id), ok=False, error="event 404")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            return PricePoint.now(self.name, event_id=str(event_id), ok=False, error=f"http: {e}")
        except ValueError as e:
            return PricePoint.now(self.name, event_id=str(event_id), ok=False, error=f"json: {e}")

        return self._parse(str(event_id), data)

    def _parse(self, event_id: str, data: dict) -> PricePoint:
        stats = data.get("stats") or {}
        lowest = stats.get("lowest_price")
        highest = stats.get("highest_price")
        avg = stats.get("average_price")
        listing_count = stats.get("listing_count")
        if lowest is None and listing_count in (0, None):
            return PricePoint.now(
                self.name,
                event_id=event_id,
                listing_count=listing_count,
                ok=True,
                error="no listings",
            )
        return PricePoint.now(
            self.name,
            event_id=event_id,
            lowest_price=float(lowest) if lowest is not None else None,
            highest_price=float(highest) if highest is not None else None,
            average_price=float(avg) if avg is not None else None,
            listing_count=int(listing_count) if listing_count is not None else None,
            ok=True,
        )

    def event_url(self) -> str | None:
        return self.config.get("url")

    @staticmethod
    def search(client_id: str, q: str, **params) -> list[dict]:
        """Helper for bootstrap."""
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.get(
                f"{BASE}/events",
                params={"client_id": client_id, "q": q, **params},
            )
        r.raise_for_status()
        return r.json().get("events", [])
