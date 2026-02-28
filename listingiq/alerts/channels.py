"""Alert channel implementations."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from listingiq.config import EmailConfig, SMSConfig, WebhookConfig
from listingiq.models import DealAnalysis

logger = logging.getLogger(__name__)


class BaseChannel(ABC):
    @abstractmethod
    async def send(self, deal: DealAnalysis) -> None: ...


class ConsoleChannel(BaseChannel):
    """Prints deal alerts to the terminal with rich formatting."""

    def __init__(self):
        self.console = Console()

    async def send(self, deal: DealAnalysis) -> None:
        listing = deal.listing
        strategy_colors = {
            "brrr": "green",
            "cash_flow": "blue",
            "flip": "yellow",
        }
        color = strategy_colors.get(deal.strategy.value, "white")

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="bold")
        table.add_column("Value")

        table.add_row("Address", listing.full_address)
        table.add_row("Price", f"${listing.price:,.0f}")
        table.add_row("Beds/Baths", f"{listing.beds}bd / {listing.baths}ba")
        table.add_row("Sqft", f"{listing.sqft:,}" if listing.sqft else "N/A")
        table.add_row("Strategy", deal.strategy.value.upper().replace("_", " "))
        table.add_row("Score", f"{deal.score}/100")

        for key, value in deal.metrics.items():
            if isinstance(value, float):
                if "pct" in key or "rate" in key or "return" in key or "roi" in key:
                    table.add_row(key.replace("_", " ").title(), f"{value:.1f}%")
                else:
                    table.add_row(key.replace("_", " ").title(), f"${value:,.0f}")
            elif isinstance(value, (int,)):
                table.add_row(key.replace("_", " ").title(), f"{value:,}")

        if listing.url:
            table.add_row("Link", listing.url)

        title = f"DEAL ALERT: {deal.strategy.value.upper().replace('_', ' ')} - Score {deal.score}"
        self.console.print(Panel(table, title=title, border_style=color))


class EmailChannel(BaseChannel):
    """Sends deal alerts via email using SMTP."""

    def __init__(self, config: EmailConfig):
        self.config = config

    async def send(self, deal: DealAnalysis) -> None:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        if not self.config.to_addresses:
            return

        listing = deal.listing
        subject = (
            f"ListingIQ Deal Alert: {deal.strategy.value.upper()} "
            f"Score {deal.score} - {listing.address}"
        )

        body_parts = [
            f"<h2>Deal Alert: {deal.strategy.value.upper().replace('_', ' ')}</h2>",
            f"<p><strong>Score:</strong> {deal.score}/100</p>",
            f"<h3>{listing.full_address}</h3>",
            f"<p><strong>Price:</strong> ${listing.price:,.0f}</p>",
            f"<p><strong>Beds/Baths:</strong> {listing.beds}bd / {listing.baths}ba</p>",
            f"<p><strong>Sqft:</strong> {listing.sqft:,}</p>" if listing.sqft else "",
            "<h4>Metrics</h4>",
            "<table border='1' cellpadding='5'>",
        ]

        for key, value in deal.metrics.items():
            label = key.replace("_", " ").title()
            if isinstance(value, float):
                if "pct" in key or "rate" in key or "return" in key or "roi" in key:
                    body_parts.append(f"<tr><td>{label}</td><td>{value:.1f}%</td></tr>")
                else:
                    body_parts.append(f"<tr><td>{label}</td><td>${value:,.0f}</td></tr>")

        body_parts.append("</table>")

        if listing.url:
            body_parts.append(f'<p><a href="{listing.url}">View Listing</a></p>')

        body_parts.append(f"<hr><p><em>{deal.summary}</em></p>")

        html_body = "\n".join(body_parts)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.from_address
        msg["To"] = ", ".join(self.config.to_addresses)
        msg.attach(MIMEText(deal.summary, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=self.config.smtp_host,
            port=self.config.smtp_port,
            username=self.config.smtp_user,
            password=self.config.smtp_password,
            use_tls=False,
            start_tls=True,
        )
        logger.info("Email alert sent for %s", listing.address)


class SMSChannel(BaseChannel):
    """Sends deal alerts via SMS using Twilio."""

    def __init__(self, config: SMSConfig):
        self.config = config

    async def send(self, deal: DealAnalysis) -> None:
        if not self.config.to_numbers:
            return

        listing = deal.listing
        message = (
            f"ListingIQ DEAL ALERT\n"
            f"{deal.strategy.value.upper()} Score: {deal.score}/100\n"
            f"{listing.address}\n"
            f"${listing.price:,.0f} | {listing.beds}bd/{listing.baths}ba\n"
        )

        # Add key metric
        if "monthly_cash_flow" in deal.metrics:
            message += f"Cash Flow: ${deal.metrics['monthly_cash_flow']:,.0f}/mo\n"
        if "cash_on_cash_return" in deal.metrics:
            message += f"CoC: {deal.metrics['cash_on_cash_return']:.1f}%\n"
        if "estimated_profit" in deal.metrics:
            message += f"Profit: ${deal.metrics['estimated_profit']:,.0f}\n"

        if listing.url:
            message += listing.url

        # Use httpx to call Twilio API directly (avoids sync twilio client issues)
        async with httpx.AsyncClient() as client:
            for number in self.config.to_numbers:
                await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{self.config.account_sid}/Messages.json",
                    auth=(self.config.account_sid, self.config.auth_token),
                    data={
                        "From": self.config.from_number,
                        "To": number,
                        "Body": message[:1600],  # SMS limit
                    },
                )

        logger.info("SMS alert sent for %s", listing.address)


class WebhookChannel(BaseChannel):
    """Sends deal alerts to webhook URLs (Slack, Discord, etc.)."""

    def __init__(self, config: WebhookConfig):
        self.config = config

    async def send(self, deal: DealAnalysis) -> None:
        listing = deal.listing
        payload = {
            "text": (
                f"*ListingIQ Deal Alert*\n"
                f"*Strategy:* {deal.strategy.value.upper().replace('_', ' ')} | "
                f"*Score:* {deal.score}/100\n"
                f"*Address:* {listing.full_address}\n"
                f"*Price:* ${listing.price:,.0f} | "
                f"{listing.beds}bd/{listing.baths}ba | {listing.sqft:,} sqft\n"
                f"{deal.summary}\n"
                f"{listing.url}"
            ),
            "deal": {
                "strategy": deal.strategy.value,
                "score": deal.score,
                "metrics": deal.metrics,
                "listing": {
                    "address": listing.full_address,
                    "price": listing.price,
                    "beds": listing.beds,
                    "baths": listing.baths,
                    "sqft": listing.sqft,
                    "url": listing.url,
                },
            },
        }

        async with httpx.AsyncClient() as client:
            for url in self.config.urls:
                try:
                    await client.post(url, json=payload, timeout=10.0)
                except Exception as e:
                    logger.error("Webhook failed for %s: %s", url, e)

        logger.info("Webhook alert sent for %s", listing.address)
