from __future__ import annotations

import base64
import codecs
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


class Boat24Scraper(BaseScraper):
    name = "boat24"
    base_url = "https://www.boat24.com"
    use_playwright = True

    SEARCH_URL = (
        "https://www.boat24.com/en/sailingboats/hallberg-rassy/"
        "?prs_max=100000&lge_min=12"
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

        for page_offset in range(0, 200, 20):  # 20 per page, max 10 pages
            url = f"{self.SEARCH_URL}&page={page_offset}" if page_offset > 0 else self.SEARCH_URL
            html = self.fetch(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("div.blurb--strip, div.blurb--singleline")
            if not cards:
                # Fallback: any div with data-link attribute
                cards = soup.find_all("div", attrs={"data-link": True})

            if not cards:
                break

            for card in cards:
                try:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                except Exception as e:
                    logger.warning(f"[boat24] Failed to parse card: {e}")

            # Check if there are more pages
            pagination = soup.select_one("div.pagination")
            if not pagination or "next" not in pagination.get_text(strip=True).lower():
                break

        logger.info(f"[boat24] Found {len(listings)} listings")
        return listings

    def _decode_link(self, encoded: str) -> str:
        """Decode boat24's base64(ROT13) obfuscated links."""
        try:
            decoded_b64 = base64.b64decode(encoded).decode("utf-8")
            return codecs.decode(decoded_b64, "rot_13")
        except Exception:
            return ""

    def _parse_card(self, card) -> Listing | None:
        # Title
        title_el = card.select_one("h3.blurb__title")
        if not title_el:
            title_el = card.select_one("h3")
        title = title_el.get_text(strip=True) if title_el else card.get("title", "")

        if not title or "hallberg" not in title.lower():
            return None

        # Detail URL
        url = ""
        # Try the button link first
        link_el = card.select_one("a.blurb__button[href]")
        if link_el:
            href = link_el.get("href", "")
            url = f"{self.base_url}{href}" if href.startswith("/") else href

        # Fallback: decode the data-link attribute
        if not url:
            data_link = card.get("data-link", "")
            if data_link:
                decoded = self._decode_link(data_link)
                if decoded:
                    url = f"{self.base_url}{decoded}" if decoded.startswith("/") else decoded

        if not url:
            return None

        # Listing ID from URL or data-id
        bookmark = card.select_one("[data-id]")
        if bookmark:
            listing_id = f"boat24_{bookmark.get('data-id')}"
        else:
            id_match = re.search(r"/detail/(\d+)", url)
            listing_id = f"boat24_{id_match.group(1)}" if id_match else f"boat24_{url}"

        # Price
        price_el = card.select_one("p.blurb__price")
        price_eur = None
        if price_el:
            amount, currency = parse_price(price_el.get_text())
            price_eur = convert_to_eur(amount, currency)

        # Length from dimensions fact
        length_m = None
        facts = card.select("li.blurb__fact")
        for fact in facts:
            key_el = fact.select_one("span.blurb__key")
            val_el = fact.select_one("span.blurb__value")
            if key_el and val_el:
                key_text = key_el.get_text(strip=True).lower()
                val_text = val_el.get_text(strip=True)
                if "dimension" in key_text or "length" in key_text:
                    # Dimensions format: "12.50 x 3.80 m" — take the first number
                    m = re.search(r"(\d+[.,]\d+)", val_text)
                    if m:
                        length_m = float(m.group(1).replace(",", "."))

        # Location
        loc_el = card.select_one("p.blurb__location")
        location = loc_el.get_text(strip=True) if loc_el else ""
        location = location.replace(">>", ",").strip()

        return Listing(
            title=title,
            price_eur=price_eur,
            length_m=length_m,
            url=url,
            source=self.name,
            listing_id=listing_id,
            location=location,
        )
