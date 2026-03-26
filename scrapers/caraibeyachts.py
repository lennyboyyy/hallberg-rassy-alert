from __future__ import annotations

import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from scrapers.base import (
    BaseScraper,
    Listing,
    convert_to_eur,
    parse_length_m,
    parse_price,
)

logger = logging.getLogger(__name__)


class CaraibeYachtsScraper(BaseScraper):
    name = "caraibeyachts"
    base_url = "https://www.caraibe-yachts.com"

    SEARCH_URL = "https://www.caraibe-yachts.com/en/bateaux/used-boats/"

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []

        html = self.fetch(self.SEARCH_URL)
        if not html:
            logger.info(f"[{self.name}] Found 0 listings")
            return listings

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article.wpgb-card")

        for card in cards:
            try:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.warning(f"[{self.name}] Failed to parse card: {e}")

        logger.info(f"[{self.name}] Found {len(listings)} listings")
        return listings

    def _parse_card(self, card) -> Optional[Listing]:
        # Extract post ID from class
        classes = card.get("class", [])
        post_id = None
        for cls in classes:
            m = re.match(r"wpgb-post-(\d+)", cls)
            if m:
                post_id = m.group(1)
                break
        if not post_id:
            return None

        listing_id = f"caraibeyachts_{post_id}"

        # Title and URL
        title_el = card.select_one(".wpgb-block-14 > a")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        url = href if href.startswith("http") else f"{self.base_url}{href}"

        if "hallberg" not in title.lower():
            return None

        # Price
        price_eur = None
        price_el = card.select_one(".wpgb-block-4")
        currency_el = card.select_one(".wpgb-block-19")
        if price_el:
            price_text = price_el.get_text(strip=True)
            currency_text = currency_el.get_text(strip=True) if currency_el else "EUR"
            amount, currency = parse_price(f"{price_text} {currency_text}")
            price_eur = convert_to_eur(amount, currency)

        # Location
        location = ""
        loc_el = card.select_one(".wpgb-block-3")
        if loc_el:
            location = loc_el.get_text(strip=True)

        # Length - fetch from detail page
        length_m = self._fetch_length(url)

        return Listing(
            title=title,
            price_eur=price_eur,
            length_m=length_m,
            url=url,
            source=self.name,
            listing_id=listing_id,
            location=location,
        )

    def _fetch_length(self, url: str) -> Optional[float]:
        """Fetch boat length from detail page specs."""
        html = self.fetch(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")
        # Specs are in span.elementor-icon-list-text with format "Label: Value"
        for span in soup.select("span.elementor-icon-list-text"):
            text = span.get_text(strip=True)
            if text.lower().startswith("length"):
                # e.g. "Length: 13.22 M"
                parts = text.split(":", 1)
                if len(parts) == 2:
                    return parse_length_m(parts[1].strip())
        return None
