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


class BotenTeKoopScraper(BaseScraper):
    name = "botentekoop"
    base_url = "https://www.botentekoop.nl"
    use_playwright = True

    SEARCH_URL = "https://www.botentekoop.nl/boten/soort-zeilboten/merk-hallberg-rassy/"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []

        html = self.fetch(self.SEARCH_URL)
        if not html:
            return listings

        soup = BeautifulSoup(html, "lxml")

        # Primary: find listing links with data-ssr-meta attribute
        cards = soup.select("a.grid-listing-link")
        if not cards:
            # Fallback: any link to /boot/ detail pages
            cards = soup.find_all("a", href=re.compile(r"/boot/.+-\d+/"))

        for card in cards:
            try:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.warning(f"[botentekoop] Failed to parse card: {e}")

        logger.info(f"[botentekoop] Found {len(listings)} listings")
        return listings

    def _parse_card(self, card) -> Listing | None:
        href = card.get("href", "")
        if not href:
            return None

        url = f"{self.base_url}{href}" if href.startswith("/") else href

        # Extract listing ID
        id_match = re.search(r"-(\d+)/$", href)
        listing_id = f"botentekoop_{id_match.group(1)}" if id_match else f"botentekoop_{href}"

        # Try data-ssr-meta first: "Make|boat-type|length_m|location_code|price_eur"
        ssr_meta = card.get("data-ssr-meta", "")
        title = ""
        price_eur = None
        length_m = None
        location = ""

        if ssr_meta:
            parts = ssr_meta.split("|")
            if len(parts) >= 5:
                try:
                    length_m = float(parts[2]) if parts[2] else None
                except (ValueError, IndexError):
                    pass
                try:
                    price_eur = float(parts[4]) if parts[4] else None
                except (ValueError, IndexError):
                    pass

        # Title from data-e2e="listingName" or h2
        title_el = card.select_one("[data-e2e='listingName']")
        if not title_el:
            title_el = card.find("h2")
        if title_el:
            title = title_el.get_text(strip=True)

        if not title:
            # Try from product ID reporting attribute
            title = card.get("title", "")

        if not title or "hallberg" not in title.lower():
            return None

        # Price from data-e2e="listingPrice"
        if price_eur is None:
            price_el = card.select_one("[data-e2e='listingPrice']")
            if price_el:
                amount, currency = parse_price(price_el.get_text())
                price_eur = convert_to_eur(amount, currency)

        # Location from seller content
        seller_el = card.select_one("[data-e2e='listingSellerContent']")
        if seller_el:
            seller_text = seller_el.get_text(strip=True)
            # Format: "Dealer Name | City, Region"
            if "|" in seller_text:
                location = seller_text.split("|")[-1].strip()
            else:
                location = seller_text

        return Listing(
            title=title,
            price_eur=price_eur,
            length_m=length_m,
            url=url,
            source=self.name,
            listing_id=listing_id,
            location=location,
        )
