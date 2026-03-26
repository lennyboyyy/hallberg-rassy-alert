from __future__ import annotations

import logging
import random
import re
import time
from typing import List, Optional

from bs4 import BeautifulSoup

from scrapers.base import (
    BaseScraper,
    Listing,
    USER_AGENTS,
    convert_to_eur,
    parse_length_m,
    parse_price,
)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

logger = logging.getLogger(__name__)

# Known Hallberg-Rassy model lengths in meters (approximate LOA)
HR_MODEL_LENGTHS = {
    "26": 7.92, "27": 8.25, "29": 8.82, "31": 9.47, "310": 9.47,
    "312": 9.50, "34": 10.39, "342": 10.39, "35": 10.39, "352": 10.65,
    "36": 10.85, "37": 11.35, "372": 11.35, "38": 11.55, "382": 11.55,
    "39": 11.98, "40": 12.12, "400": 12.12, "40c": 12.12, "40C": 12.12,
    "41": 12.42, "42": 12.78, "42e": 12.78, "42f": 12.78, "43": 13.10,
    "43 mk i": 13.10, "43 mk ii": 13.10, "44": 13.39, "45": 13.83,
    "46": 14.02, "462": 14.02, "48": 14.75, "49": 14.93, "50": 15.25,
    "53": 16.24, "54": 16.68, "55": 16.94, "57": 17.40, "62": 18.90,
    "64": 19.50, "69": 21.14,
    "monsun 31": 9.47, "rasmus 35": 10.39, "mistral 33": 9.97,
    "rassy 35": 10.39, "rassy 352": 10.65,
}


class BoatsComScraper(BaseScraper):
    name = "boatscom"
    base_url = "https://www.boats.com"

    SEARCH_URL = "https://www.boats.com/boats-for-sale/?make=hallberg-rassy&type=sail"
    MAX_PAGES = 15

    def _fetch_with_playwright(self, url: str, wait_selector: str = None) -> Optional[str]:
        """Fetch using Playwright with optional selector wait."""
        if not HAS_PLAYWRIGHT:
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1920, "height": 1080},
                )
                page = ctx.new_page()
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=15000)
                    except Exception:
                        pass
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logger.warning(f"[boatscom] Playwright fetch failed for {url}: {e}")
            return None

    def scrape(self) -> List[Listing]:
        listings: List[Listing] = []
        seen_ids = set()

        for page_num in range(1, self.MAX_PAGES + 1):
            url = f"{self.SEARCH_URL}&page={page_num}" if page_num > 1 else self.SEARCH_URL
            html = self._fetch_with_playwright(url, wait_selector='div.price')
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            cards = soup.find_all("a", href=re.compile(r"/sailing-boats/.+-\d+/"))

            if not cards:
                break

            new_found = 0
            for card in cards:
                try:
                    listing = self._parse_card(card)
                    if listing and listing.listing_id not in seen_ids:
                        seen_ids.add(listing.listing_id)
                        listings.append(listing)
                        new_found += 1
                except Exception as e:
                    logger.warning(f"[boatscom] Failed to parse card: {e}")

            if new_found == 0:
                break

            # Be polite between pages
            time.sleep(1)

        logger.info(f"[boatscom] Found {len(listings)} listings")
        return listings

    def _parse_card(self, card) -> Optional[Listing]:
        href = card.get("href", "")
        if not href:
            return None

        url = f"{self.base_url}{href}" if href.startswith("/") else href

        # Extract listing ID from URL
        id_match = re.search(r"-(\d+)/$", href)
        if not id_match:
            return None
        listing_id = f"boatscom_{id_match.group(1)}"

        # Title from h2
        h2 = card.find("h2")
        title = h2.get_text(strip=True) if h2 else ""

        if not title or "hallberg" not in title.lower():
            return None

        # Price
        price_eur = None
        price_div = card.find("div", class_="price")
        if price_div:
            price_text = price_div.get_text(strip=True)
            if "request" not in price_text.lower():
                amount, currency = parse_price(price_text)
                price_eur = convert_to_eur(amount, currency)

        # Location
        location = ""
        country_div = card.find("div", class_="country")
        if country_div:
            location = country_div.get_text(strip=True)

        # Infer length from model number in title
        length_m = self._length_from_title(title)

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
        """Infer boat length from known HR model numbers in the title."""
        # Extract model part after "Hallberg-Rassy" or "Hallberg Rassy"
        m = re.search(r"hallberg[- ]rassy\s+(.+)", title, re.IGNORECASE)
        if not m:
            return None
        model_part = m.group(1).strip().lower()

        # Try full model string first, then just the number
        if model_part in HR_MODEL_LENGTHS:
            return HR_MODEL_LENGTHS[model_part]

        # Extract leading number/model identifier
        num_match = re.match(r"(\d+\w*)", model_part)
        if num_match:
            model_key = num_match.group(1).lower()
            if model_key in HR_MODEL_LENGTHS:
                return HR_MODEL_LENGTHS[model_key]

        return None
