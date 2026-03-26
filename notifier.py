from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from scrapers.base import Listing

logger = logging.getLogger(__name__)


def send_email_alert(listings: List[Listing]) -> bool:
    """Send an email alert for new boat listings."""
    email_address = os.environ.get("EMAIL_ADDRESS")
    email_password = os.environ.get("EMAIL_PASSWORD")
    email_to = os.environ.get("EMAIL_TO", email_address)  # Default: send to self

    if not email_address or not email_password:
        logger.error("EMAIL_ADDRESS or EMAIL_PASSWORD not set")
        return False

    if not listings:
        return True

    subject = f"🚢 {len(listings)} new Hallberg-Rassy boat{'s' if len(listings) > 1 else ''} found!"

    # Build HTML email body
    html_parts = [
        "<html><body>",
        f"<h2>{len(listings)} new Hallberg-Rassy listing{'s' if len(listings) > 1 else ''} matching your criteria</h2>",
        "<p>Criteria: Hallberg-Rassy, &gt;12m, &lt;&euro;100,000</p>",
        "<hr>",
    ]

    for listing in listings:
        price_str = f"€{listing.price_eur:,.0f}" if listing.price_eur else "Price unknown"
        length_str = f"{listing.length_m:.1f}m" if listing.length_m else "Length unknown"
        location_str = listing.location or "Location unknown"

        html_parts.append(f"""
        <div style="margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
            <h3 style="margin-top: 0;">
                <a href="{listing.url}" style="color: #0066cc; text-decoration: none;">{listing.title}</a>
            </h3>
            <table style="border-collapse: collapse;">
                <tr><td style="padding: 2px 10px 2px 0; font-weight: bold;">Price:</td><td>{price_str}</td></tr>
                <tr><td style="padding: 2px 10px 2px 0; font-weight: bold;">Length:</td><td>{length_str}</td></tr>
                <tr><td style="padding: 2px 10px 2px 0; font-weight: bold;">Location:</td><td>{location_str}</td></tr>
                <tr><td style="padding: 2px 10px 2px 0; font-weight: bold;">Source:</td><td>{listing.source}</td></tr>
            </table>
            <p><a href="{listing.url}" style="color: #0066cc;">View listing →</a></p>
        </div>
        """)

    html_parts.append("</body></html>")
    html_body = "\n".join(html_parts)

    # Plain text fallback
    text_parts = [
        f"{len(listings)} new Hallberg-Rassy listing(s) found!\n",
        "Criteria: Hallberg-Rassy, >12m, <€100,000\n",
        "---\n",
    ]
    for listing in listings:
        price_str = f"€{listing.price_eur:,.0f}" if listing.price_eur else "Price unknown"
        length_str = f"{listing.length_m:.1f}m" if listing.length_m else "Length unknown"
        text_parts.append(
            f"{listing.title}\n"
            f"  Price: {price_str}\n"
            f"  Length: {length_str}\n"
            f"  Location: {listing.location or 'Unknown'}\n"
            f"  Source: {listing.source}\n"
            f"  Link: {listing.url}\n\n"
        )
    text_body = "\n".join(text_parts)

    # Build email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_address
    msg["To"] = email_to

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    # Try Gmail first, then Outlook as fallback
    smtp_configs = [
        ("smtp.gmail.com", 587),
        ("smtp-mail.outlook.com", 587),
        ("smtp.office365.com", 587),
    ]

    for host, port in smtp_configs:
        try:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(email_address, email_password)
                server.send_message(msg)
            logger.info(f"Email sent successfully via {host}")
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.warning(f"Auth failed on {host}: {e}")
            continue
        except Exception as e:
            logger.warning(f"Failed to send via {host}: {e}")
            continue

    logger.error("Failed to send email via all SMTP servers")
    return False
