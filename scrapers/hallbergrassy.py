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


class HallbergRassyScraper(BaseScraper):
    name = "hallbergrassy"
    base_url = "https://www.hallberg-rassy.com"

    SEARCH_URL = "https://www.hallberg-rassy.com/yachts/pre-owned-yachts-for-sale"

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []

        html = self.fetch(self.SEARCH_URL)
        if not html:
            logger.info(f"[{self.name}] Found 0 listings")
            return listings

        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("table.table.table-striped")
        if not table:
            logger.warning(f"[{self.name}] Could not find listings table")
            logger.info(f"[{self.name}] Found 0 listings")
            return listings

        rows = table.select("tbody tr")
        for row in rows:
            try:
                listing = self._parse_row(row)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.warning(f"[{self.name}] Failed to parse row: {e}")

        logger.info(f"[{self.name}] Found {len(listings)} listings")
        return listings

    def _parse_row(self, row) -> Optional[Listing]:
        cells = row.find_all("td")
        if len(cells) < 4:
            return None

        # Column 1: Boat type with link
        link = cells[0].find("a")
        if not link:
            return None

        title = link.get_text(strip=True)
        href = link.get("href", "")
        url = f"{self.base_url}{href}" if href.startswith("/") else href

        # Listing ID from URL slug
        slug = href.rstrip("/").split("/")[-1]
        listing_id = f"hallbergrassy_{slug}"

        # Column 2: Price
        price_text = cells[1].get_text(strip=True)
        price_eur = None
        if price_text and "application" not in price_text.lower():
            amount, currency = parse_price(price_text)
            price_eur = convert_to_eur(amount, currency)

        # Column 3: Location
        location = cells[2].get_text(strip=True)

        # Column 4: Year (not needed but good to know)

        # Length - infer from model name or fetch detail page
        length_m = self._length_from_title(title)
        if length_m is None:
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

    @staticmethod
    def _length_from_title(title: str) -> Optional[float]:
        """Infer length from HR model number in title."""
        # Known HR model lengths
        model_lengths = {
            "29": 8.82, "31": 9.47, "310": 9.47, "312": 9.50,
            "34": 10.39, "340": 10.39, "342": 10.39, "35": 10.39, "352": 10.65,
            "36": 10.85, "37": 11.35, "372": 11.35, "38": 11.55,
            "382": 11.55, "39": 11.98, "40": 12.12, "400": 12.12,
            "41": 12.42, "42": 12.78, "43": 13.10, "44": 13.39,
            "45": 13.83, "46": 14.02, "462": 14.02, "48": 14.75,
            "49": 14.93, "50": 15.25, "53": 16.24, "54": 16.68,
            "55": 16.94, "57": 17.40, "62": 18.90, "64": 19.50,
            "69": 21.14,
        }
        m = re.search(r"hallberg[- ]rassy\s+(\d+)", title, re.IGNORECASE)
        if m:
            model = m.group(1)
            if model in model_lengths:
                return model_lengths[model]
        return None

    def _fetch_length(self, url: str) -> Optional[float]:
        """Fetch length from detail page if not in model lookup."""
        html = self.fetch(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")
        # Look for length in spec lists
        for li in soup.select("li"):
            text = li.get_text(strip=True)
            if re.match(r"l(ength|oa)\b", text, re.IGNORECASE):
                return parse_length_m(text)
        return None
