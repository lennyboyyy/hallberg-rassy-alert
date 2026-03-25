from __future__ import annotations

import json
import logging
import re
from typing import List

from bs4 import BeautifulSoup

from scrapers.base import (
    BaseScraper,
    Listing,
    convert_to_eur,
    parse_length_m,
    parse_price,
)

logger = logging.getLogger(__name__)


class YachtWorldScraper(BaseScraper):
    name = "yachtworld"
    base_url = "https://www.yachtworld.com"
    use_playwright = True

    SEARCH_URL = "https://www.yachtworld.com/boats-for-sale/type-sail/make-hallberg-rassy/"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        })

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []

        for page in range(1, 6):  # max 5 pages
            url = f"{self.SEARCH_URL}?page={page}" if page > 1 else self.SEARCH_URL
            html = self.fetch(url)
            if not html:
                break

            page_listings = self._parse_html(html)
            if not page_listings:
                # Try to extract from __NEXT_DATA__ JSON (Next.js)
                page_listings = self._parse_next_data(html)

            if not page_listings:
                break

            listings.extend(page_listings)

        logger.info(f"[yachtworld] Found {len(listings)} listings")
        return listings

    def _parse_html(self, html: str) -> List[Listing]:
        listings = []
        soup = BeautifulSoup(html, "lxml")

        # Try the known listing card structure
        cards = soup.select("div.search-right-col a[href*='/boats-for-sale/']")
        if not cards:
            # Alternative: look for any boat listing links
            cards = soup.find_all("a", href=re.compile(r"/boats-for-sale/.*hallberg.*rassy", re.IGNORECASE))
        if not cards:
            # Try broader pattern
            cards = soup.find_all("a", href=re.compile(r"/boats-for-sale/\d+/"))

        for card in cards:
            try:
                listing = self._parse_card(card, soup)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.warning(f"[yachtworld] Failed to parse card: {e}")

        return listings

    def _parse_card(self, card, soup) -> Listing | None:
        href = card.get("href", "")
        if not href:
            return None

        url = f"{self.base_url}{href}" if href.startswith("/") else href

        # Extract listing ID from URL
        id_match = re.search(r"/(\d+)/", href)
        listing_id = f"yachtworld_{id_match.group(1)}" if id_match else f"yachtworld_{href}"

        # Title
        name_div = card.select_one("[property='name'], .listing-card-title, h3, h2")
        title = name_div.get_text(strip=True) if name_div else card.get_text(strip=True)[:100]

        if not title or "hallberg" not in title.lower():
            return None

        # Price
        price_el = card.select_one(".price, .listing-card-price, [class*='price']")
        price_eur = None
        if price_el:
            amount, currency = parse_price(price_el.get_text())
            price_eur = convert_to_eur(amount, currency)

        # Length
        length_el = card.select_one(".listing-card-length-year, [class*='length']")
        length_m = None
        if length_el:
            length_m = parse_length_m(length_el.get_text())

        # Location
        loc_el = card.select_one(".listing-card-location, [class*='location']")
        location = loc_el.get_text(strip=True) if loc_el else ""

        return Listing(
            title=title,
            price_eur=price_eur,
            length_m=length_m,
            url=url,
            source=self.name,
            listing_id=listing_id,
            location=location,
        )

    def _parse_next_data(self, html: str) -> List[Listing]:
        """Try to extract listings from Next.js __NEXT_DATA__ JSON."""
        listings = []
        match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not match:
            return listings

        try:
            data = json.loads(match.group(1))
            # Navigate the Next.js data structure to find boat listings
            props = data.get("props", {}).get("pageProps", {})
            search_results = props.get("searchResults", props.get("boats", props.get("listings", [])))

            if isinstance(search_results, dict):
                search_results = search_results.get("results", search_results.get("boats", []))

            for boat in search_results:
                if not isinstance(boat, dict):
                    continue
                try:
                    title = boat.get("boatName", boat.get("title", boat.get("makeModel", "")))
                    if "hallberg" not in title.lower():
                        continue

                    price = boat.get("price", {})
                    if isinstance(price, dict):
                        amount = price.get("amount", price.get("value"))
                        currency = price.get("currency", "EUR")
                    else:
                        amount = price
                        currency = "EUR"

                    price_eur = convert_to_eur(float(amount), currency) if amount else None

                    length = boat.get("length", {})
                    if isinstance(length, dict):
                        length_m = length.get("meters", length.get("m"))
                        if not length_m and length.get("feet"):
                            length_m = float(length["feet"]) * 0.3048
                    else:
                        length_m = float(length) if length else None

                    loc = boat.get("location", {})
                    if isinstance(loc, dict):
                        location = f"{loc.get('city', '')}, {loc.get('country', '')}".strip(", ")
                    else:
                        location = str(loc) if loc else ""

                    url_path = boat.get("url", boat.get("listingUrl", ""))
                    url = f"{self.base_url}{url_path}" if url_path.startswith("/") else url_path
                    boat_id = boat.get("id", boat.get("listingId", url_path))

                    listings.append(Listing(
                        title=title,
                        price_eur=price_eur,
                        length_m=round(length_m, 2) if length_m else None,
                        url=url,
                        source=self.name,
                        listing_id=f"yachtworld_{boat_id}",
                        location=location,
                    ))
                except Exception as e:
                    logger.warning(f"[yachtworld] Failed to parse boat from JSON: {e}")

        except json.JSONDecodeError:
            logger.warning("[yachtworld] Failed to parse __NEXT_DATA__ JSON")

        return listings
