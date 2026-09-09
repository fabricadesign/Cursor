"""Alternative DPD tracking via AfterShip REST API.

If DPD Portugal's SOAP API is difficult to set up, AfterShip provides a simple
REST API that aggregates tracking across 1000+ carriers including DPD Portugal.

To use this instead of the SOAP client:
1. Sign up at aftership.com and get an API key
2. Add AFTERSHIP_API_KEY to your .env
3. In tools.py, change: import dpd_client_aftership as dpd_client
"""

import httpx
from config import settings

BASE_URL = "https://api.aftership.com/v4"


async def track_parcel(tracking_number: str) -> dict | None:
    headers = {
        "aftership-api-key": settings.aftership_api_key,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/trackings/dpd-prt/{tracking_number}",
            headers=headers,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json().get("data", {}).get("tracking", {})
        return data


def format_tracking_info(data: dict) -> dict:
    checkpoints = data.get("checkpoints", [])
    latest = checkpoints[-1] if checkpoints else {}
    return {
        "status": data.get("tag", "Unknown"),
        "latest_event": latest.get("message", "No events yet"),
        "latest_event_date": latest.get("checkpoint_time", "N/A"),
        "latest_event_location": latest.get("location", "N/A"),
        "estimated_delivery": data.get("expected_delivery", "N/A"),
        "total_events": len(checkpoints),
    }
