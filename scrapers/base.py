from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

import requests

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# Approximate conversion rates to EUR
CURRENCY_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.17,
    "SEK": 0.088,
    "DKK": 0.134,
    "NOK": 0.086,
    "CHF": 1.05,
}


@dataclass
class Listing:
    title: str
    price_eur: Optional[float]
    length_m: Optional[float]
    url: str
    source: str
    listing_id: str
    location: str = ""

    def matches_criteria(self, min_length_m: float = 12.0, max_price_eur: float = 100_000) -> bool:
        if self.price_eur is not None and self.price_eur > max_price_eur:
            return False
        if self.length_m is not None and self.length_m < min_length_m:
            return False
        return True


def parse_price(text: str) -> tuple[Optional[float], str]:
    """Extract a numeric price and currency from text. Returns (amount, currency_code)."""
    if not text:
        return None, "EUR"

    text = text.strip().replace("\xa0", " ").replace(",", "").replace(".", "")

    currency = "EUR"
    for code in CURRENCY_TO_EUR:
        if code in text.upper():
            currency = code
            break
    if "£" in text or "GBP" in text.upper():
        currency = "GBP"
    elif "$" in text or "USD" in text.upper():
        currency = "USD"
    elif "kr" in text.lower() or "SEK" in text.upper():
        currency = "SEK"
    elif "DKK" in text.upper():
        currency = "DKK"
    elif "NOK" in text.upper():
        currency = "NOK"
    elif "CHF" in text.upper():
        currency = "CHF"

    numbers = re.findall(r"\d+", text)
    if not numbers:
        return None, currency

    amount = int("".join(numbers))
    # Heuristic: if the number is very large it's probably in cents or minor units
    # Most boat prices are between 1000 and 10_000_000
    if amount > 50_000_000:
        amount = amount / 100

    return float(amount), currency


def convert_to_eur(amount: Optional[float], currency: str) -> Optional[float]:
    if amount is None:
        return None
    rate = CURRENCY_TO_EUR.get(currency, 1.0)
    return round(amount * rate, 2)


def parse_length_m(text: str) -> Optional[float]:
    """Extract length in meters from text."""
    if not text:
        return None
    text = text.strip().replace(",", ".")

    # Try meters first (e.g., "12.50 m", "12.5m", "12,50m")
    m = re.search(r"(\d+[.,]?\d*)\s*m(?:eter|etre)?s?\b", text, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # Try feet (e.g., "41 ft", "41'")
    ft = re.search(r"(\d+[.,]?\d*)\s*(?:ft|feet|')", text, re.IGNORECASE)
    if ft:
        return round(float(ft.group(1)) * 0.3048, 2)

    # Just a bare number — assume meters if reasonable
    bare = re.search(r"(\d+[.,]?\d*)", text)
    if bare:
        val = float(bare.group(1))
        if 5 < val < 100:
            return val

    return None


try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class BaseScraper:
    """Base class for boat listing scrapers."""

    name: str = "base"
    base_url: str = ""
    use_cloudscraper: bool = False
    use_playwright: bool = False  # Use headless browser for aggressive bot protection

    def __init__(self):
        if self.use_cloudscraper and HAS_CLOUDSCRAPER:
            self.session = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
        else:
            self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
        })

    def fetch(self, url: str, timeout: int = 30) -> Optional[str]:
        # Try Playwright first if enabled
        if self.use_playwright and HAS_PLAYWRIGHT:
            return self._fetch_playwright(url, timeout)

        try:
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            # Fallback to Playwright on 403/503
            if HAS_PLAYWRIGHT and hasattr(e, "response") and e.response is not None:
                if e.response.status_code in (403, 503):
                    logger.info(f"[{self.name}] Got {e.response.status_code}, retrying with Playwright...")
                    return self._fetch_playwright(url, timeout)
            logger.warning(f"[{self.name}] Failed to fetch {url}: {e}")
            return None

    def _fetch_playwright(self, url: str, timeout: int = 30) -> Optional[str]:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    locale="en-US",
                    viewport={"width": 1920, "height": 1080},
                )
                page = context.new_page()
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                # Wait a bit for dynamic content
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logger.warning(f"[{self.name}] Playwright fetch failed for {url}: {e}")
            return None

    def scrape(self) -> List[Listing]:
        raise NotImplementedError
