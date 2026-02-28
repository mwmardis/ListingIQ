"""Alert dispatcher that routes deal alerts to configured channels."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from listingiq.config import AlertsConfig
from listingiq.models import DealAnalysis, Alert
from listingiq.alerts.channels import (
    ConsoleChannel,
    EmailChannel,
    SMSChannel,
    WebhookChannel,
)

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Dispatches deal alerts to all configured channels."""

    def __init__(self, config: AlertsConfig):
        self.config = config
        self._channels: dict[str, ConsoleChannel | EmailChannel | SMSChannel | WebhookChannel] = {}

        if "console" in config.channels:
            self._channels["console"] = ConsoleChannel()
        if "email" in config.channels and config.email.smtp_host:
            self._channels["email"] = EmailChannel(config.email)
        if "sms" in config.channels and config.sms.account_sid:
            self._channels["sms"] = SMSChannel(config.sms)
        if "webhook" in config.channels and config.webhook.urls:
            self._channels["webhook"] = WebhookChannel(config.webhook)

    async def dispatch(self, deals: list[DealAnalysis]) -> list[Alert]:
        """Send alerts for deals that meet the minimum score threshold."""
        alerts: list[Alert] = []

        qualified = [d for d in deals if d.meets_criteria and d.score >= self.config.min_deal_score]

        if not qualified:
            logger.info("No deals meet alert threshold (min score: %d)", self.config.min_deal_score)
            return alerts

        logger.info("Dispatching alerts for %d deals", len(qualified))

        for deal in qualified:
            sent_channels: list[str] = []

            for name, channel in self._channels.items():
                try:
                    await channel.send(deal)
                    sent_channels.append(name)
                except Exception as e:
                    logger.error("Failed to send alert via %s: %s", name, e)

            alert = Alert(
                deal=deal,
                channels_sent=sent_channels,
                sent_at=datetime.utcnow(),
            )
            alerts.append(alert)

        return alerts

    def dispatch_sync(self, deals: list[DealAnalysis]) -> list[Alert]:
        """Synchronous wrapper for dispatch."""
        return asyncio.run(self.dispatch(deals))
