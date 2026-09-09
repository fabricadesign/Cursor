"""InvoiceXpress API client — find and retrieve customer invoices.

Invoices in InvoiceXpress carry the Shopify order number in their `reference`
field (e.g. "Order #4104"), which lets us match an invoice to an order.
"""

import httpx
from config import settings

BASE = f"https://{settings.invoicexpress_account}.app.invoicexpress.com"


async def find_invoice_by_order(order_number: str) -> dict | None:
    """Find an invoice whose reference matches the given Shopify order number."""
    clean = order_number.lstrip("#").strip()
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{BASE}/invoices.json",
            params={"api_key": settings.invoicexpress_api_key, "text": clean, "page": 1},
        )
        resp.raise_for_status()
        invoices = resp.json().get("invoices", [])

    if not invoices:
        return None

    # Require the order number to actually appear in the invoice reference,
    # e.g. reference "Order #4104". No loose fallback — avoids returning the
    # wrong customer's invoice when there is no real match.
    for inv in invoices:
        ref = (inv.get("reference") or "").lower()
        if clean.lower() in ref:
            return inv
    return None


async def get_client_fiscal_id(client_id: int) -> str:
    """Return the NIF (fiscal_id) on a client record, or '' if none."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{BASE}/clients/{client_id}.json",
            params={"api_key": settings.invoicexpress_api_key},
        )
        if resp.status_code != 200:
            return ""
        return (resp.json().get("client", {}).get("fiscal_id") or "").strip()


async def get_invoice_pdf_url(invoice_id: int) -> str | None:
    """Get a direct, downloadable PDF URL for an invoice (generates if needed)."""
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(3):
            resp = await client.get(
                f"{BASE}/api/pdf/{invoice_id}.json",
                params={"api_key": settings.invoicexpress_api_key},
            )
            if resp.status_code != 200:
                return None
            output = resp.json().get("output", {})
            url = output.get("pdfUrl")
            if url:
                return url
    return None
