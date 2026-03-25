from __future__ import annotations

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


class TheYachtMarketScraper(BaseScraper):
    name = "theyachtmarket"
    base_url = "https://www.theyachtmarket.com"
    use_playwright = True

    SEARCH_URL = (
        "https://www.theyachtmarket.com/en/boats-for-sale/hallberg-rassy/"
        "?minlength=12&maxprice=100000&currency=eur"
    )

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []

        for page in range(1, 6):  # max 5 pages
            url = f"{self.SEARCH_URL}&page={page}" if page > 1 else self.SEARCH_URL
            html = self.fetch(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")

            # Listings are <a> tags inside div.gridlayout
            grid = soup.select_one("div.gridlayout")
            if grid:
                cards = grid.find_all("a", href=re.compile(r"/en/boats-for-sale/"))
            else:
                # Fallback: find all boat links
                cards = soup.find_all("a", href=re.compile(r"/en/boats-for-sale/hallberg.rassy/", re.IGNORECASE))

            if not cards:
                break

            for card in cards:
                try:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                except Exception as e:
                    logger.warning(f"[theyachtmarket] Failed to parse card: {e}")

        logger.info(f"[theyachtmarket] Found {len(listings)} listings")
        return listings

    def _parse_card(self, card) -> Listing | None:
        href = card.get("href", "")
        if not href or "contact-seller" in href:
            return None

        url = f"{self.base_url}{href}" if href.startswith("/") else href

        # Extract listing ID from URL (pattern: /id12345/)
        id_match = re.search(r"/id(\d+)/", href)
        listing_id = f"theyachtmarket_{id_match.group(1)}" if id_match else f"theyachtmarket_{href}"

        # Title from h3
        h3 = card.find("h3")
        title = h3.get_text(strip=True) if h3 else ""

        if not title or "hallberg" not in title.lower():
            return None

        # Price
        price_el = card.select_one("p.price")
        price_eur = None
        if price_el:
            amount, currency = parse_price(price_el.get_text())
            price_eur = convert_to_eur(amount, currency)

        # Specs line: "2005 | 12.1m | Diesel | Sail"
        length_m = None
        paragraphs = card.find_all("p")
        for p in paragraphs:
            text = p.get_text(strip=True)
            if "|" in text and "m" in text.lower():
                parts = [part.strip() for part in text.split("|")]
                for part in parts:
                    lm = parse_length_m(part)
                    if lm and lm > 5:
                        length_m = lm
                        break

        # Location: first <p> after <h3>
        location = ""
        if h3 and h3.find_next_sibling("p"):
            loc_p = h3.find_next_sibling("p")
            if loc_p and not loc_p.get("class"):
                loc_text = loc_p.get_text(strip=True)
                if not re.search(r"\d", loc_text):  # Location shouldn't have numbers
                    location = loc_text

        return Listing(
            title=title,
            price_eur=price_eur,
            length_m=length_m,
            url=url,
            source=self.name,
            listing_id=listing_id,
            location=location,
        )
