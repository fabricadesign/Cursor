"""Recharge (subscriptions) API client — read-only.

Looks up a customer's subscriptions by email so Bea can tell them their
status, next charge date, and what's in their subscription. No write access:
change requests (pause/skip/swap/cancel) are escalated to the team instead.
"""

import httpx
from config import settings

BASE = "https://api.rechargeapps.com"


def _headers() -> dict:
    return {
        "X-Recharge-Access-Token": settings.recharge_api_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def configured() -> bool:
    return bool(settings.recharge_api_token)


async def find_customer_by_email(email: str) -> dict | None:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{BASE}/customers",
            headers=_headers(),
            params={"email": email, "limit": 1},
        )
        resp.raise_for_status()
        customers = resp.json().get("customers", [])
        return customers[0] if customers else None


async def get_subscriptions(customer_id: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{BASE}/subscriptions",
            headers=_headers(),
            params={"customer_id": customer_id, "limit": 25},
        )
        resp.raise_for_status()
        return resp.json().get("subscriptions", [])


def summarize_subscription(sub: dict) -> dict:
    """Pull the customer-relevant fields out of a Recharge subscription."""
    return {
        "product": sub.get("product_title", ""),
        "variant": sub.get("variant_title", ""),
        "quantity": sub.get("quantity"),
        "status": sub.get("status", ""),
        "next_charge_date": (sub.get("next_charge_scheduled_at") or "")[:10],
        "frequency": f"every {sub.get('order_interval_frequency', '')} {sub.get('order_interval_unit', '')}".strip(),
    }
