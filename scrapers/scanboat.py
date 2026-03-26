from __future__ import annotations

import logging
import re
import time
from typing import List

from bs4 import BeautifulSoup

from scrapers.base import (
    BaseScraper,
    Listing,
    convert_to_eur,
    parse_price,
)

logger = logging.getLogger(__name__)


class ScanboatScraper(BaseScraper):
    name = "scanboat"
    base_url = "https://www.scanboat.com"

    SEARCH_URL = (
        "https://www.scanboat.com/en/boat-market/boats"
        "?SearchCriteria.BoatModelText=hallberg-rassy"
        "&SearchCriteria.MinLength=12"
        "&SearchCriteria.MaxPrice=100000"
        "&SearchCriteria.CurrencyID=2"
        "&SearchCriteria.BoatTypeID=1"
        "&SearchCriteria.LengthWidthUnitID=1"
        "&SearchCriteria.SimilarSearch=False"
        "&SearchCriteria.Searched=True"
    )

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []
        for page in range(1, 11):  # max 10 pages
            url = f"{self.SEARCH_URL}&page={page}" if page > 1 else self.SEARCH_URL
            html = self.fetch(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")

            # Listings are <a> tags with hreflang="en" linking to boat detail pages
            cards = soup.find_all("a", href=re.compile(r"/en/boat-market/boats/sailingboat-.+-\d+$"), hreflang="en")
            if not cards:
                # Fallback: any <a> with item__header inside
                cards = [a for a in soup.find_all("a", href=re.compile(r"/en/boat-market/boats/.+-\d+$"))
                         if a.find("header", class_="item__header")]

            if not cards:
                break

            new_count = 0
            for card in cards:
                try:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                        new_count += 1
                except Exception as e:
                    logger.warning(f"[scanboat] Failed to parse card: {e}")

            if new_count == 0:
                break

        logger.info(f"[scanboat] Found {len(listings)} listings")
        return listings

    def _fetch_length(self, url: str) -> float | None:
        """Fetch boat length from the detail page."""
        try:
            time.sleep(0.5)  # Be respectful to the server
            html = self.fetch(url)
            if not html:
                return None
            # Length is embedded in a URL parameter: searchcriteria.length=10.54
            match = re.search(r"searchcriteria\.length=([\d.]+)", html, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    pass
            return None
        except Exception as e:
            logger.warning(f"[scanboat] Failed to fetch length from {url}: {e}")
            return None

    def _parse_card(self, card) -> Listing | None:
        href = card.get("href", "")
        if not href:
            return None

        url = f"{self.base_url}{href}" if href.startswith("/") else href

        # Listing ID from trailing number in URL
        id_match = re.search(r"-(\d+)$", href)
        listing_id = f"scanboat_{id_match.group(1)}" if id_match else f"scanboat_{href}"

        # Title from <h2> inside header
        h2 = card.find("h2")
        title = h2.get_text(strip=True) if h2 else ""

        if not title or "hallberg" not in title.lower():
            return None

        # Price from section.flex-2 > p
        price_eur = None
        price_section = card.find("section", class_="flex-2")
        if price_section:
            price_p = price_section.find("p")
            if price_p:
                amount, currency = parse_price(price_p.get_text())
                price_eur = convert_to_eur(amount, currency)

        # Info from section.item__body > p (e.g., "Sailingboat | Year : 1988 | Country : Denmark")
        location = ""
        body = card.find("section", class_="item__body")
        if body:
            info_p = body.find("p")
            if info_p:
                info_text = info_p.get_text(strip=True)
                country_match = re.search(r"Country\s*:\s*(.+?)(?:\||$)", info_text, re.IGNORECASE)
                if country_match:
                    location = country_match.group(1).strip()

        # Length is not in the listing card, fetch from detail page
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
