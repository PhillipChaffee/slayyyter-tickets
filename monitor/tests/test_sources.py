from monitor.sources.etc_scraper import EtcScraper
from monitor.sources.seatgeek import SeatGeekClient
from monitor.sources.ticketmaster import TicketmasterClient


def test_tm_parse_basic():
    client = TicketmasterClient({"event_id": "abc"}, {})
    data = {
        "priceRanges": [
            {"min": 312.50, "max": 580.00, "currency": "USD"},
        ]
    }
    p = client._parse("abc", data)
    assert p.ok
    assert p.lowest_price == 312.50
    assert p.highest_price == 580.00
    assert p.currency == "USD"


def test_tm_parse_no_price_ranges():
    client = TicketmasterClient({"event_id": "abc"}, {})
    p = client._parse("abc", {})
    assert p.ok
    assert p.lowest_price is None
    assert p.error == "no priceRanges"


def test_tm_parse_multiple_ranges_takes_min_and_max():
    client = TicketmasterClient({"event_id": "abc"}, {})
    data = {
        "priceRanges": [
            {"min": 200, "max": 400, "currency": "USD"},
            {"min": 150, "max": 600, "currency": "USD"},
        ]
    }
    p = client._parse("abc", data)
    assert p.lowest_price == 150
    assert p.highest_price == 600


def test_sg_parse_basic():
    client = SeatGeekClient({"event_id": 123}, {})
    data = {
        "stats": {
            "lowest_price": 285.00,
            "highest_price": 580.0,
            "average_price": 412.30,
            "listing_count": 87,
        }
    }
    p = client._parse("123", data)
    assert p.ok
    assert p.lowest_price == 285.00
    assert p.average_price == 412.30
    assert p.listing_count == 87


def test_sg_parse_no_listings():
    client = SeatGeekClient({"event_id": 123}, {})
    data = {"stats": {"listing_count": 0}}
    p = client._parse("123", data)
    assert p.ok
    assert p.lowest_price is None
    assert p.listing_count == 0


def test_etc_parse_jsonld_lowprice():
    scraper = EtcScraper({"enabled": True, "url": "https://example.com"}, {})
    html = """<html><head>
<script type="application/ld+json">
{"@type": "Event", "name": "X",
 "offers": {"@type": "AggregateOffer", "lowPrice": 216.0, "highPrice": 565.0, "priceCurrency": "USD"}}
</script>
</head></html>"""
    p = scraper._parse(html)
    assert p.ok
    assert p.lowest_price == 216.0
    assert p.highest_price == 565.0


def test_etc_parse_no_offer_returns_not_ok():
    scraper = EtcScraper({"enabled": True, "url": "https://example.com"}, {})
    p = scraper._parse("<html><body>nothing here</body></html>")
    assert not p.ok
    assert p.error == "no JSON-LD offer found"


def test_etc_disabled_short_circuits():
    scraper = EtcScraper({"enabled": False, "url": "https://example.com"}, {})
    p = scraper.fetch()
    assert not p.ok
    assert p.error == "disabled in config"


def test_etc_parse_finds_offer_nested_in_graph():
    """Regression: many sites wrap Event in @graph; offer extraction must recurse."""
    scraper = EtcScraper({"enabled": True, "url": "https://example.com"}, {})
    html = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"BreadcrumbList"},
  {"@type":"Event","name":"X","offers":{"@type":"AggregateOffer","lowPrice":199.0,"highPrice":480.0,"priceCurrency":"USD"}}
]}
</script></head></html>"""
    p = scraper._parse(html)
    assert p.ok
    assert p.lowest_price == 199.0
    assert p.highest_price == 480.0


def test_etc_parse_finds_offer_in_subevent():
    """Some sites put offers under subEvent."""
    scraper = EtcScraper({"enabled": True, "url": "https://example.com"}, {})
    html = """<script type="application/ld+json">
{"@type":"Event","name":"Tour",
 "subEvent":[{"@type":"Event","offers":{"lowPrice":250,"priceCurrency":"USD"}}]}
</script>"""
    p = scraper._parse(html)
    assert p.ok
    assert p.lowest_price == 250.0
