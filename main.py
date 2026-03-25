#!/usr/bin/env python3
"""
Hallberg-Rassy Boat Alert System
Scrapes multiple boat listing sites and sends email alerts for new listings.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from scrapers import ALL_SCRAPERS
from scrapers.base import Listing
from notifier import send_email_alert

# Configuration
MIN_LENGTH_M = 12.0
MAX_PRICE_EUR = 100_000
PRUNE_AFTER_DAYS = 90
STATE_FILE = Path(__file__).parent / "seen_listings.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_seen_listings() -> Dict:
    """Load previously seen listings from JSON file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load state file: {e}")
    return {}


def save_seen_listings(seen: Dict) -> None:
    """Save seen listings to JSON file."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def prune_old_listings(seen: Dict) -> Dict:
    """Remove listings older than PRUNE_AFTER_DAYS."""
    cutoff = (datetime.utcnow() - timedelta(days=PRUNE_AFTER_DAYS)).isoformat()
    return {
        lid: data for lid, data in seen.items()
        if data.get("first_seen", "") > cutoff
    }


def run_all_scrapers() -> List[Listing]:
    """Run all scrapers and collect results."""
    all_listings: List[Listing] = []

    for scraper_cls in ALL_SCRAPERS:
        try:
            scraper = scraper_cls()
            logger.info(f"Running {scraper.name}...")
            listings = scraper.scrape()
            all_listings.extend(listings)
        except Exception as e:
            logger.error(f"Scraper {scraper_cls.name} crashed: {e}")

    return all_listings


def filter_listings(listings: List[Listing]) -> List[Listing]:
    """Apply criteria filters to listings."""
    filtered = []
    for listing in listings:
        if listing.matches_criteria(MIN_LENGTH_M, MAX_PRICE_EUR):
            filtered.append(listing)
        else:
            logger.debug(
                f"Filtered out: {listing.title} "
                f"(price={listing.price_eur}, length={listing.length_m})"
            )
    return filtered


def find_new_listings(listings: List[Listing], seen: Dict) -> List[Listing]:
    """Find listings that haven't been seen before."""
    new = []
    for listing in listings:
        if listing.listing_id not in seen:
            new.append(listing)
    return new


def main() -> int:
    logger.info("=" * 60)
    logger.info("Hallberg-Rassy Boat Alert — Starting scan")
    logger.info(f"Criteria: HR > {MIN_LENGTH_M}m, < €{MAX_PRICE_EUR:,.0f}")
    logger.info("=" * 60)

    # Load state
    seen = load_seen_listings()
    logger.info(f"Loaded {len(seen)} previously seen listings")

    # Prune old entries
    seen = prune_old_listings(seen)

    # Scrape all sites
    all_listings = run_all_scrapers()
    logger.info(f"Total raw listings found: {len(all_listings)}")

    # Filter by criteria
    filtered = filter_listings(all_listings)
    logger.info(f"Listings matching criteria: {len(filtered)}")

    # Find new ones
    new_listings = find_new_listings(filtered, seen)
    logger.info(f"New listings: {len(new_listings)}")

    # Send alert if we have new listings
    if new_listings:
        logger.info("Sending email alert...")
        for listing in new_listings:
            logger.info(f"  NEW: {listing.title} — €{listing.price_eur or '?'} — {listing.url}")

        success = send_email_alert(new_listings)
        if not success:
            logger.error("Failed to send email alert!")
    else:
        logger.info("No new listings found this run.")

    # Update seen listings (add all current listings, not just new ones)
    now = datetime.utcnow().isoformat()
    for listing in filtered:
        if listing.listing_id not in seen:
            seen[listing.listing_id] = {
                "first_seen": now,
                "title": listing.title,
                "url": listing.url,
                "price_eur": listing.price_eur,
                "source": listing.source,
            }

    # Save state
    save_seen_listings(seen)
    logger.info(f"Saved {len(seen)} seen listings")
    logger.info("Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
