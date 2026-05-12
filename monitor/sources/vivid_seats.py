"""
Vivid Seats source.

Uses the unauthenticated `hermes/api/v1/productions/{id}` JSON endpoint that
the consumer site calls. No DataDome, no JS rendering, no API key required —
just a normal User-Agent and the production ID.

Response shape (relevant fields):
  {
    "id": 6790581,
    "minPrice": 245.98,         # cheapest listing, pre-fee
    "maxPrice": 528,
    "avgPrice": 367.47,
    "medianPrice": 344,
    "minAipPrice": 334.55,      # all-in (with fees) — what we want to compare to threshold
    "maxAipPrice": 714.94,
    "showAip": true,            # site flag: true means AIP is the user-facing price
    "listingCount": 15,
    "ticketCount": 43,
    ...
  }

We use minAipPrice when showAip is true (matches what the user sees at
checkout); otherwise fall back to minPrice.
"""

from __future__ import annotations

import httpx

from .base import PricePoint, SourceClient


BASE = "https://www.vividseats.com/hermes/api/v1"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class VividSeatsClient(SourceClient):
    name = "vivid_seats"

    def fetch(self) -> PricePoint:
        if not self.config.get("enabled"):
            return PricePoint.now(self.name, ok=False, error="disabled in config")
        prod_id = self.config.get("production_id")
        if not prod_id:
            return PricePoint.now(self.name, ok=False, error="missing production_id; set in config.yaml")

        headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
                r = client.get(f"{BASE}/productions/{prod_id}", headers=headers)
            if r.status_code == 404:
                return PricePoint.now(self.name, event_id=str(prod_id), ok=False, error="production 404")
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            return PricePoint.now(self.name, event_id=str(prod_id), ok=False, error=f"http: {e}")
        except ValueError as e:
            return PricePoint.now(self.name, event_id=str(prod_id), ok=False, error=f"json: {e}")

        return self._parse(str(prod_id), data)

    def _parse(self, prod_id: str, data: dict) -> PricePoint:
        show_aip = bool(data.get("showAip"))
        if show_aip and data.get("minAipPrice") is not None:
            lowest = data.get("minAipPrice")
            highest = data.get("maxAipPrice")
        else:
            lowest = data.get("minPrice")
            highest = data.get("maxPrice")
        avg = data.get("avgPrice")
        listings = data.get("listingCount")

        if lowest is None and not listings:
            return PricePoint.now(
                self.name,
                event_id=prod_id,
                listing_count=0,
                ok=True,
                error="no listings",
            )

        return PricePoint.now(
            self.name,
            event_id=prod_id,
            lowest_price=float(lowest) if lowest is not None else None,
            highest_price=float(highest) if highest is not None else None,
            average_price=float(avg) if avg is not None else None,
            listing_count=int(listings) if listings is not None else None,
            ok=True,
        )

    def event_url(self) -> str | None:
        return self.config.get("url")
