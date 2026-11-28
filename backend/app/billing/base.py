"""Billing provider interface.

The platform keeps its own source of truth (``subscriptions`` table). A provider only:
1. creates a customer / checkout for an organization (optional, may return no URL), and
2. translates its webhooks into ``BillingEvent``s that update the subscription.

Only the ``manual`` provider (invoice / bank transfer, statuses set by platform operators)
is implemented. A card/merchant-of-record provider must be chosen by the founder first
(costs and availability in Morocco differ widely); it then implements this interface and is
selected with ``BILLING_PROVIDER``. No provider SDK is installed.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BillingEvent:
    organization_id: int
    status: str                       # one of subscriptions.STATUSES
    plan: str | None = None
    current_period_end: datetime | None = None
    provider_subscription_id: str | None = None


class BillingProvider(ABC):
    name: str = "abstract"
    supports_webhooks: bool = False

    @abstractmethod
    def checkout_url(self, organization, plan: str) -> str | None:
        """Where an organization admin pays for ``plan``; None if payment is offline."""

    @abstractmethod
    def cancel(self, subscription) -> None:
        """Cancel at the provider (no-op for manual)."""

    def parse_webhook(self, body: bytes, headers: dict) -> list[BillingEvent]:
        """Verify the signature and translate a webhook. Must raise on invalid signatures."""
        raise NotImplementedError


class ManualBillingProvider(BillingProvider):
    """Invoices and bank transfers handled outside the platform; platform operators record
    payment by setting the subscription status / period end in the platform console."""

    name = "manual"

    def checkout_url(self, organization, plan: str) -> str | None:
        return None

    def cancel(self, subscription) -> None:
        return None


_PROVIDERS = {"manual": ManualBillingProvider}


def get_provider(name: str | None = None) -> BillingProvider:
    name = name or os.getenv("BILLING_PROVIDER", "manual")
    if name not in _PROVIDERS:
        raise RuntimeError(f"Billing provider '{name}' is not implemented. Available: {', '.join(_PROVIDERS)}")
    return _PROVIDERS[name]()
