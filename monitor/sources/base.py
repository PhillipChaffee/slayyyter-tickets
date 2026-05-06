from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class PricePoint:
    ts: str
    source: str
    event_id: str | None
    lowest_price: float | None
    highest_price: float | None
    average_price: float | None
    listing_count: int | None
    currency: str
    ok: bool
    error: str | None = None

    @classmethod
    def now(cls, source: str, **kwargs) -> "PricePoint":
        return cls(
            ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            source=source,
            event_id=kwargs.pop("event_id", None),
            lowest_price=kwargs.pop("lowest_price", None),
            highest_price=kwargs.pop("highest_price", None),
            average_price=kwargs.pop("average_price", None),
            listing_count=kwargs.pop("listing_count", None),
            currency=kwargs.pop("currency", "USD"),
            ok=kwargs.pop("ok", True),
            error=kwargs.pop("error", None),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class SourceClient(ABC):
    name: str = "abstract"

    def __init__(self, config: dict, secrets: dict):
        self.config = config
        self.secrets = secrets

    @abstractmethod
    def fetch(self) -> PricePoint:
        """Fetch current price snapshot. Always returns a PricePoint; sets ok=False on failure."""

    @abstractmethod
    def event_url(self) -> str | None:
        """Public-facing URL for the event on this source, if known."""
