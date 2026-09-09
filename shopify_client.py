"""Shopify Admin API client with automatic token management.

Uses the Client Credentials grant to obtain and refresh access tokens.
Tokens expire every 24 hours and are refreshed automatically.

Fábrica and HUMANO are separate Shopify stores, each with its own
credentials, so each brand gets its own ShopifyStore instance below.
"""

import time
import httpx
from config import settings

API_VERSION = "2024-10"
PRODUCTS_CACHE_TTL = 300  # seconds


class ShopifyStore:
    """A single Shopify store's Admin API client (own token + product cache)."""

    def __init__(self, name: str, domain: str, client_id: str, client_secret: str):
        self.name = name
        self.domain = domain
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = f"https://{domain}/admin/api/{API_VERSION}"
        self._token_cache = {"token": None, "expires_at": 0}
        self._products_cache = {"products": None, "expires_at": 0}

    @property
    def configured(self) -> bool:
        return bool(self.domain and self.client_id and self.client_secret)

    async def _get_access_token(self) -> str:
        now = time.time()
        if self._token_cache["token"] and now < self._token_cache["expires_at"] - 60:
            return self._token_cache["token"]

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://{self.domain}/admin/oauth/access_token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()

        self._token_cache["token"] = data["access_token"]
        self._token_cache["expires_at"] = now + data.get("expires_in", 86399)
        return self._token_cache["token"]

    async def _headers(self) -> dict:
        token = await self._get_access_token()
        return {
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        }

    async def search_order(self, order_number: str) -> dict | None:
        """Search for an order by its display number (e.g. '#1042')."""
        clean_number = order_number.lstrip("#")
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/orders.json",
                headers=headers,
                params={"name": clean_number, "status": "any"},
            )
            resp.raise_for_status()
            orders = resp.json().get("orders", [])
            return orders[0] if orders else None

    async def get_order(self, order_id: int) -> dict:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/orders/{order_id}.json",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()["order"]

    async def get_customer(self, customer_id: int) -> dict:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/customers/{customer_id}.json",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()["customer"]

    async def get_fulfillments(self, order_id: int) -> list[dict]:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/orders/{order_id}/fulfillments.json",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json().get("fulfillments", [])

    async def search_orders_by_email(self, email: str) -> list[dict]:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/orders.json",
                headers=headers,
                params={"email": email, "status": "any", "limit": 5},
            )
            resp.raise_for_status()
            return resp.json().get("orders", [])

    async def search_customers(self, query: str) -> list[dict]:
        """Search customers directly (not via an order) using Shopify's customer
        search syntax, e.g. 'email:x@y.com', 'phone:+351...', or a free-text name."""
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/customers/search.json",
                headers=headers,
                params={"query": query, "limit": 5},
            )
            resp.raise_for_status()
            return resp.json().get("customers", [])

    async def _fetch_active_products(self) -> list[dict]:
        """Fetch all active products (paginating as needed), with a short TTL cache
        so repeated customer questions don't hammer the Shopify API."""
        now = time.time()
        if self._products_cache["products"] is not None and now < self._products_cache["expires_at"]:
            return self._products_cache["products"]

        headers = await self._headers()
        products = []
        url = f"{self.base_url}/products.json"
        params = {
            "status": "active",
            "limit": 250,
            "fields": "id,title,handle,product_type,tags,status,variants",
        }
        async with httpx.AsyncClient() as client:
            while url:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                products.extend(resp.json().get("products", []))

                # Follow Shopify's Link header for pagination; params only apply
                # to the first request, subsequent URLs already include them.
                next_url = None
                link_header = resp.headers.get("Link", "")
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        next_url = part.split(";")[0].strip().strip("<>")
                url = next_url
                params = None

        self._products_cache["products"] = products
        self._products_cache["expires_at"] = now + PRODUCTS_CACHE_TTL
        return products

    async def search_products(self, query: str) -> list[dict]:
        """Search active products by keyword against title, product_type and tags."""
        products = await self._fetch_active_products()
        q = query.strip().lower()
        if not q:
            return products
        matches = []
        for p in products:
            haystack = " ".join([
                p.get("title", ""),
                p.get("product_type", ""),
                p.get("tags", ""),
            ]).lower()
            if q in haystack:
                matches.append(p)
        return matches


fabrica = ShopifyStore(
    "Fábrica",
    settings.shopify_store_domain,
    settings.shopify_client_id,
    settings.shopify_client_secret,
)
humano = ShopifyStore(
    "HUMANO",
    settings.humano_shopify_store_domain,
    settings.humano_shopify_client_id,
    settings.humano_shopify_client_secret,
)

STORES = {"fabrica": fabrica, "humano": humano}
SITE_URLS = {"fabrica": "https://fabricacoffeeroasters.com", "humano": "https://humano.coffee"}


def get_store(brand: str) -> ShopifyStore:
    return STORES.get(brand, fabrica)


# --- Backward-compatible module-level functions (default to the Fábrica store) ---

async def search_order(order_number: str) -> dict | None:
    return await fabrica.search_order(order_number)


async def get_order(order_id: int) -> dict:
    return await fabrica.get_order(order_id)


async def get_customer(customer_id: int) -> dict:
    return await fabrica.get_customer(customer_id)


async def get_fulfillments(order_id: int) -> list[dict]:
    return await fabrica.get_fulfillments(order_id)


async def search_orders_by_email(email: str) -> list[dict]:
    return await fabrica.search_orders_by_email(email)


async def search_products(query: str) -> list[dict]:
    return await fabrica.search_products(query)
