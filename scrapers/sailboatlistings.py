from __future__ import annotations

import logging
import re
from typing import List

from bs4 import BeautifulSoup

from scrapers.base import (
    BaseScraper,
    Listing,
    convert_to_eur,
    parse_price,
)

logger = logging.getLogger(__name__)


class SailboatListingsScraper(BaseScraper):
    name = "sailboatlistings"
    base_url = "https://www.sailboatlistings.com"

    SEARCH_URL = "https://www.sailboatlistings.com/sailboats/Hallberg-Rassy"

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []

        html = self.fetch(self.SEARCH_URL)
        if not html:
            return listings

        soup = BeautifulSoup(html, "lxml")

        # Each listing is a <table> containing a span.sailheader with the boat link
        headers = soup.find_all("span", class_="sailheader")

        for header in headers:
            try:
                listing = self._parse_listing(header)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.warning(f"[sailboatlistings] Failed to parse listing: {e}")

        logger.info(f"[sailboatlistings] Found {len(listings)} listings")
        return listings

    def _parse_listing(self, header_span) -> Listing | None:
        # Title link inside span.sailheader
        link = header_span.find("a", class_="sailheader")
        if not link:
            return None

        title = link.get_text(strip=True)
        if not title or "hallberg" not in title.lower():
            return None

        href = link.get("href", "")
        url = href if href.startswith("http") else f"{self.base_url}{href}"

        # Extract ID from URL (e.g., /view/68423)
        id_match = re.search(r"/view/(\d+)", href)
        listing_id = f"sailboatlistings_{id_match.group(1)}" if id_match else f"sailboatlistings_{href}"

        # Find the parent table that contains all the details
        table = header_span.find_parent("table")
        if not table:
            return None

        # Extract data from span.sailvb (labels) and span.sailvk (values)
        price_eur = None
        length_m = None
        location = ""

        labels = table.find_all("span", class_="sailvb")
        for label in labels:
            label_text = label.get_text(strip=True).rstrip(":")

            # Value is in a span.sailvk in the next <td> cell of the same <tr>
            value_span = None
            tr = label.find_parent("tr")
            if tr:
                tds = tr.find_all("td")
                for td in tds:
                    vs = td.find("span", class_="sailvk")
                    if vs:
                        value_span = vs
                        break

            if not value_span:
                continue

            value_text = value_span.get_text(strip=True)

            if "length" in label_text.lower():
                # Format: "54.11'" (feet with apostrophe)
                ft_match = re.search(r"(\d+\.?\d*)'", value_text)
                if ft_match:
                    length_m = round(float(ft_match.group(1)) * 0.3048, 2)
                else:
                    m_match = re.search(r"(\d+\.?\d*)\s*m", value_text, re.IGNORECASE)
                    if m_match:
                        length_m = float(m_match.group(1))

            elif "asking" in label_text.lower():
                amount, currency = parse_price(value_text)
                price_eur = convert_to_eur(amount, currency)

            elif "location" in label_text.lower():
                location = value_text

        return Listing(
            title=title,
            price_eur=price_eur,
            length_m=length_m,
            url=url,
            source=self.name,
            listing_id=listing_id,
            location=location,
        )
