"""
Phase 2 source: Event Tickets Center (ETC) scraper.

Off by default. ETC has no public API but currently holds the resale floor
($216 as of May 6 2026) so it's a candidate to add if real-world data shows
APIs persistently miss the actual lowest price.

Risks:
  - Page structure can change without notice; we'll fail open (PricePoint with ok=False).
  - Aggressive scraping risks IP block. Single GET per poll, default User-Agent.
  - Respect robots.txt; do not bypass any access controls.

Strategy: parse JSON-LD structured data (`<script type="application/ld+json">`),
which most ticket-listing pages emit and which gives `offers.lowPrice` reliably
without depending on render-time HTML.
"""

from __future__ import annotations

import json
import re

import httpx

from .base import PricePoint, SourceClient


TIMEOUT = httpx.Timeout(20.0, connect=10.0)
DEFAULT_UA = "slayyyter-tickets-monitor/0.1 (personal price tracker; respects robots.txt)"


class EtcScraper(SourceClient):
    name = "etc_scraper"

    def fetch(self) -> PricePoint:
        if not self.config.get("enabled"):
            return PricePoint.now(self.name, ok=False, error="disabled in config")

        url = self.config.get("url")
        if not url:
            return PricePoint.now(self.name, ok=False, error="missing url; set in config.yaml")

        headers = {"User-Agent": DEFAULT_UA, "Accept": "text/html"}
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
                r = client.get(url, headers=headers)
            r.raise_for_status()
            html = r.text
        except httpx.HTTPError as e:
            return PricePoint.now(self.name, ok=False, error=f"http: {e}")

        return self._parse(html)

    def _parse(self, html: str) -> PricePoint:
        for block in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            try:
                payload = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            for offer in _extract_offers(payload):
                low = offer.get("lowPrice") or offer.get("price")
                if low is None:
                    continue
                high = offer.get("highPrice")
                return PricePoint.now(
                    self.name,
                    lowest_price=float(low),
                    highest_price=float(high) if high else None,
                    currency=offer.get("priceCurrency", "USD"),
                    ok=True,
                )
        return PricePoint.now(self.name, ok=False, error="no JSON-LD offer found")

    def event_url(self) -> str | None:
        return self.config.get("url")


def _extract_offers(node) -> list[dict]:
    """Recurse a parsed JSON-LD node and collect every dict that looks like an offer.

    Handles cases where the Event is nested inside `@graph`, `mainEntity`,
    `itemListElement`, or wrapped in arrays.
    """
    out: list[dict] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_extract_offers(item))
        return out
    if not isinstance(node, dict):
        return out
    offers = node.get("offers")
    if offers:
        offers_list = offers if isinstance(offers, list) else [offers]
        for o in offers_list:
            if isinstance(o, dict):
                out.append(o)
    for nested_key in ("@graph", "mainEntity", "itemListElement", "subEvent"):
        if nested_key in node:
            out.extend(_extract_offers(node[nested_key]))
    return out
